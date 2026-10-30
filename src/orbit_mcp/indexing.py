"""Small persistent observations of Orbit's own detached workers (Linux only)."""

import asyncio
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path


def default_state_dir() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "orbit-mcp"


def process_identity(pid: int) -> str | None:
    """Avoid treating a zombie or a reused PID (including after reboot) as our job."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in {"Z", "X"}:
            return None
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return f"{boot}:{fields[19]}"
    except (OSError, IndexError):
        return None


def job_path(config, root: Path) -> Path:
    # Orbit data roots are isolated namespaces; clients must share the same environment.
    namespace = (
        os.environ.get("ORBIT_DATA_DIR") or os.environ.get("XDG_DATA_HOME") or str(Path.home())
    )
    key = hashlib.sha256(f"{root}\0{namespace}".encode()).hexdigest()
    return config.state_dir / f"{key}.json"


def read_job(path: Path) -> dict:
    try:
        record = json.loads(path.read_text())
        if not isinstance(record, dict):
            raise ValueError("expected an object")
        return record
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as error:
        raise RuntimeError(
            "Cannot read adapter job state; check state_dir permissions/content"
        ) from error


def write_job(path: Path, record: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(record, stream)
            stream.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def worker_state(record: dict) -> str:
    if not record:
        return "unobserved"
    if not record.get("identity"):
        return "unverified"
    return "running" if process_identity(record["pid"]) == record["identity"] else "ended"


async def git_output(root: Path, *args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(root),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(10):
            # Callers ask for fixed-size metadata, not a full diff or file listing.
            output = await process.stdout.read(4096)
            await process.wait()
        if process.returncode:
            raise ValueError(
                "Repository needs an accessible initial commit; create one before indexing"
            )
        return output.decode().strip()
    finally:
        if process.returncode is None:
            process.kill()
        while await process.stdout.read(65536):
            pass
        await process.wait()


async def git_state(root: Path) -> tuple[str, bool]:
    head = await git_output(root, "rev-parse", "--verify", "HEAD")
    # --porcelain may be large. Stream/discard it, retaining only a boolean.
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(root),
        "status",
        "--porcelain",
        "--untracked-files=normal",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    dirty = False
    try:
        async with asyncio.timeout(10):
            while chunk := await process.stdout.read(65536):
                dirty = dirty or bool(chunk)
            await process.wait()
        if process.returncode:
            raise RuntimeError("Could not inspect Git working tree")
        return head, dirty
    finally:
        if process.returncode is None:
            process.kill()
        while await process.stdout.read(65536):
            pass
        await process.wait()


async def structured(adapter, root: Path, args: list[str]):
    result = await adapter.run(root, args, separate_stderr=True)
    if result["truncated"]:
        raise RuntimeError("Orbit JSON output was truncated; increase max_output_bytes")
    try:
        return json.loads(result["output"])
    except ValueError as error:
        raise RuntimeError("Orbit returned invalid JSON; check CLI version with --check") from error


async def start(adapter, repository: str) -> dict:
    root = adapter.repository(repository)
    head = await git_output(root, "rev-parse", "--verify", "HEAD")
    path = job_path(adapter.config, root)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix(".lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {
                "state": "busy",
                "message": "Another connection is starting this index; check orbit_status.",
            }
        record = read_job(path)
        if worker_state(record) == "running":
            return {
                "state": "queued_or_indexing" if record["state"] == "queued" else "indexing",
                "reused": True,
                "message": "Existing background worker; poll orbit_status.",
            }
        try:
            result = await structured(adapter, root, ["workspace", "index", "--async", str(root)])
        except (RuntimeError, TimeoutError) as error:
            raise RuntimeError(
                f"{error} Background start may have succeeded; check orbit_status before retrying."
            ) from error
        if (
            not isinstance(result, dict)
            or result.get("status") not in {"queued", "indexing", "indexed"}
            or type(result.get("pid")) is not int
            or result["pid"] <= 0
        ):
            raise RuntimeError("Unexpected Orbit async JSON response; check CLI compatibility")
        record = {
            "state": result["status"],
            "pid": result["pid"],
            "identity": process_identity(result["pid"]),
            "requested_head": head,
        }
        write_job(path, record)
        return {
            "state": record["state"],
            "reused": False,
            "message": "Background job survives disconnects; poll orbit_status. No completion percentage is available.",
        }


async def status(adapter, repository: str) -> dict:
    root = adapter.repository(repository)
    head, dirty = await git_state(root)
    rows = await structured(adapter, root, ["workspace", "list", "--format", "json"])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError("Unexpected Orbit workspace JSON response; check CLI compatibility")
    selected = [row for row in rows if row.get("repo_path") == str(root)]
    # Revisions may coexist; prefer the current checkout's commit, otherwise report stale.
    row = next(
        (row for row in selected if row.get("commit_sha") == head), selected[0] if selected else {}
    )
    manifest = row.get("status", "not_indexed")
    commit = row.get("commit_sha")
    record = read_job(job_path(adapter.config, root))
    worker = worker_state(record)
    if worker == "running":
        state = "queued_or_indexing" if record["state"] == "queued" else "indexing"
    elif manifest == "indexing":
        state = "unknown"
    elif manifest == "indexed":
        state = "indexed" if commit == head else "stale"
    elif manifest == "not_indexed":
        state = "unknown" if worker == "ended" else "not_indexed"
    else:
        state = "unknown"
    return {
        "repository": repository,
        "state": state,
        "worker": worker,
        "worker_scope": "last_adapter_request",
        "manifest_state": manifest,
        "head": head,
        "indexed_commit": commit,
        "dirty": dirty,
        "working_tree_freshness": "unverified",
        "last_request": record.get("state"),
        "completion": "confirmed_at_launch" if record.get("state") == "indexed" else "unverified",
        "message": "Manifest is a snapshot; worker exit code and working-tree freshness are not available. "
        "An ended observed worker does not rule out a later external worker. "
        "Use source queries to verify content. Poll while running; check native activity before retrying unknown states. "
        "Do not reset the graph.",
    }
