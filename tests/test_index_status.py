import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace

import pytest

from orbit_mcp.server import Adapter, Config


@pytest.fixture
def indexing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "init",
        ],
        check=True,
    )
    fake = tmp_path / "orbit"
    manifest = tmp_path / "manifest.json"
    manifest.write_text("[]")
    count = tmp_path / "starts"
    fake.write_text(
        f"#!{sys.executable}\nimport json,sys,subprocess\n"
        f"from pathlib import Path\nmanifest=Path({str(manifest)!r})\n"
        f"count=Path({str(count)!r})\n"
        'if "index" in sys.argv:\n'
        ' count.write_text(count.read_text()+"x" if count.exists() else "x")\n'
        ' p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"], '
        "start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        ' print(json.dumps({"status":"indexing","pid":p.pid,"log":"private.log"}))\n'
        'else:\n print("diagnostic warning",file=sys.stderr)\n print(manifest.read_text())\n'
    )
    fake.chmod(0o755)
    config = Config(str(fake), {"demo": repo}, state_dir=tmp_path / "state")
    adapter = Adapter(config)
    yield adapter, repo, manifest, count
    # Tests create detached children; reap/kill each recorded identity safely.
    from orbit_mcp.indexing import process_identity

    for file in config.state_dir.glob("*.json"):
        record = json.loads(file.read_text())
        if record.get("identity") and process_identity(record["pid"]) == record["identity"]:
            os.kill(record["pid"], 9)


async def test_background_job_is_reused_across_connections(indexing):
    adapter, _, _, count = indexing
    started = await adapter.index("demo")
    assert started["state"] == "indexing"
    again = await Adapter(adapter.config).index("demo")
    assert again["reused"] is True
    assert count.read_text() == "x"
    status = await Adapter(adapter.config).status("demo")
    assert status["worker"] == "running"
    assert status["state"] == "indexing"
    assert "private.log" not in json.dumps(status)


async def test_status_filters_other_repos_and_reports_stale_dirty(indexing):
    adapter, repo, manifest, _ = indexing
    manifest.write_text(
        json.dumps(
            [
                {"repo_path": "/private/other", "status": "indexed", "commit_sha": "secret"},
                {
                    "repo_path": str(repo),
                    "status": "indexed",
                    "commit_sha": "old-head",
                    "database_path": "secret-database",
                },
            ]
        )
    )
    (repo / "new.py").write_text("hello")
    status = await adapter.status("demo")
    assert status["state"] == "stale"
    assert status["dirty"] is True
    assert status["worker"] == "unobserved"
    assert "secret" not in json.dumps(status)


async def test_dead_worker_does_not_remain_indexing(indexing):
    adapter, repo, manifest, _ = indexing
    await adapter.index("demo")
    record = json.loads(next(adapter.config.state_dir.glob("*.json")).read_text())
    os.kill(record["pid"], 9)
    await asyncio.sleep(0.1)
    manifest.write_text(json.dumps([{"repo_path": str(repo), "status": "indexing"}]))
    status = await Adapter(adapter.config).status("demo")
    assert status["worker"] == "ended"
    assert status["state"] == "unknown"
    assert "exit_code" not in status


async def test_unobserved_indexing_is_not_claimed_live(indexing):
    adapter, repo, manifest, _ = indexing
    manifest.write_text(json.dumps([{"repo_path": str(repo), "status": "indexing"}]))
    status = await adapter.status("demo")
    assert status["state"] == "unknown"
    assert status["manifest_state"] == "indexing"


async def test_current_commit_does_not_claim_dirty_files_are_fresh(indexing):
    adapter, repo, manifest, _ = indexing
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    manifest.write_text(
        json.dumps([{"repo_path": str(repo), "status": "indexed", "commit_sha": head}])
    )
    (repo / "new.py").write_text("changed")
    status = await adapter.status("demo")
    assert status["state"] == "indexed"
    assert status["working_tree_freshness"] == "unverified"
    assert status["dirty"] is True


async def test_status_rejects_invalid_or_truncated_json(indexing):
    adapter, _, manifest, _ = indexing
    manifest.write_text("not json")
    with pytest.raises(RuntimeError, match="JSON"):
        await adapter.status("demo")
    manifest.write_text(" " * 40000 + "[]")
    with pytest.raises(RuntimeError, match="truncated"):
        await adapter.status("demo")


async def test_empty_repository_has_repair_action(indexing):
    adapter, repo, _, _ = indexing
    empty = repo.parent / "empty"
    subprocess.run(["git", "init", "-q", str(empty)], check=True)
    adapter = Adapter(replace(adapter.config, repositories={"empty": empty}))
    with pytest.raises(ValueError, match="initial commit"):
        await adapter.index("empty")


async def test_status_unknown_alias_cannot_read_global_workspace(indexing):
    adapter, _, _, _ = indexing
    with pytest.raises(ValueError, match="Unknown repository"):
        await adapter.status("../elsewhere")


async def test_concurrent_starts_do_not_duplicate_workers(indexing):
    adapter, _, _, count = indexing
    results = await asyncio.gather(adapter.index("demo"), Adapter(adapter.config).index("demo"))
    assert {r["state"] for r in results} <= {"busy", "indexing"}
    assert count.read_text() == "x"


async def test_reused_pid_is_not_reported_as_our_worker(indexing):
    adapter, repo, manifest, _ = indexing
    from orbit_mcp.indexing import job_path, process_identity, write_job

    path = job_path(adapter.config, repo)
    path.parent.mkdir()
    write_job(
        path,
        {
            "pid": os.getpid(),
            "identity": process_identity(os.getpid()) + "wrong",
            "state": "indexing",
        },
    )
    manifest.write_text(json.dumps([{"repo_path": str(repo), "status": "indexing"}]))
    status = await adapter.status("demo")
    assert status["worker"] == "ended"
    assert status["state"] == "unknown"


async def test_queued_worker_is_reused_and_state_is_private(indexing):
    adapter, _, _, count = indexing
    fake = adapter.config.orbit
    from pathlib import Path

    Path(fake).write_text(
        Path(fake).read_text().replace('"status":"indexing"', '"status":"queued"')
    )
    first = await adapter.index("demo")
    assert first["state"] == "queued"
    assert (await adapter.status("demo"))["state"] == "queued_or_indexing"
    again = await Adapter(adapter.config).index("demo")
    assert again["reused"]
    assert count.read_text() == "x"
    record = next(adapter.config.state_dir.glob("*.json"))
    assert record.stat().st_mode & 0o777 == 0o600
    assert adapter.config.state_dir.stat().st_mode & 0o777 == 0o700


async def test_structured_command_bounds_stderr_without_deadlocking(indexing):
    adapter, _, manifest, _ = indexing
    from pathlib import Path

    fake = Path(adapter.config.orbit)
    fake.write_text(fake.read_text().replace('"diagnostic warning"', '"x" * 1000000'))
    manifest.write_text("[]")
    status = await asyncio.wait_for(adapter.status("demo"), 5)
    assert status["state"] == "not_indexed"


async def test_later_external_index_is_not_misattributed_to_old_job(indexing):
    adapter, repo, manifest, _ = indexing
    await adapter.index("demo")
    record = json.loads(next(adapter.config.state_dir.glob("*.json")).read_text())
    os.kill(record["pid"], 9)
    await asyncio.sleep(0.1)
    # Native CLI or another client starts after our observed job ends. The
    # manifest contains no owner PID, so it cannot be attributed to our old job.
    external = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        manifest.write_text(json.dumps([{"repo_path": str(repo), "status": "indexing"}]))
        status = await adapter.status("demo")
        assert external.poll() is None
        assert status["worker"] == "ended"
        assert status["state"] == "unknown"
    finally:
        external.terminate()
        external.wait(timeout=5)


async def test_stderr_inherited_by_child_stays_within_deadline(indexing):
    adapter, repo, _, _ = indexing
    import time
    from pathlib import Path

    fake = Path(adapter.config.orbit)
    fake.write_text(
        f"#!{sys.executable}\nimport subprocess,sys,time\n"
        'subprocess.Popen([sys.executable,"-c","import os,time; time.sleep(.1); os.close(1); time.sleep(2)"])\n'
        "sys.stdout.close()\n"
    )
    adapter = Adapter(replace(adapter.config, timeout_seconds=0.3))
    before = time.monotonic()
    with pytest.raises(TimeoutError):
        await adapter.run(repo, ["workspace", "list", "--format", "json"], separate_stderr=True)
    assert time.monotonic() - before < 1
