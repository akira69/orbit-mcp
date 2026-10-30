import asyncio
import json
import os
import subprocess
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from orbit_mcp.server import Adapter, load_config


@pytest.fixture
def setup(tmp_path):
    repo = tmp_path / "repo with spaces"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "app.py").write_text("def double(n):\n    return n * 2\n")
    subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True)
    fake = tmp_path / "orbit"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, time\n"
        "if 'SLOW' in sys.argv: time.sleep(30)\n"
        "if 'FLOOD' in sys.argv:\n"
        "    print('x' * 100000, flush=True); time.sleep(30)\n"
        "if 'ERROR' in sys.argv:\n"
        "    print('fixture command failed', file=sys.stderr); sys.exit(2)\n"
        "if 'NOMATCH' in sys.argv: sys.exit(1)\n"
        "if 'BUSY' in sys.argv: sys.exit(75)\n"
        "print(json.dumps({'args': sys.argv[1:], 'cwd': os.getcwd()}))\n"
    )
    fake.chmod(0o755)
    config = tmp_path / "config.toml"
    config.write_text(
        f"orbit = {json.dumps(str(fake))}\n"
        "timeout_seconds = 1\nmax_output_bytes = 1024\n"
        f"[repositories]\ndemo = {json.dumps(str(repo))}\n"
    )
    return Adapter(load_config(config)), repo, config


async def test_search_is_literal_scoped_and_no_shell(setup):
    adapter, repo, _ = setup
    query = "--help; $(touch escaped) repo:other/project"
    result = await adapter.search("demo", query)
    payload = json.loads(result["output"])
    assert payload["args"] == ["grep", "--repo", str(repo), "-F", "--", query, str(repo)]
    assert payload["cwd"] == str(repo)
    assert not (repo / "escaped").exists()


async def test_context_uses_validated_local_range(setup):
    adapter, repo, _ = setup
    result = await adapter.context("demo", "app.py", 1, 2)
    assert json.loads(result["output"])["args"] == [
        "context",
        "--repo",
        str(repo),
        "--",
        f"{repo}/app.py:1-2",
    ]


@pytest.mark.parametrize("path", ["../outside.py", "/etc/passwd", "mr:42", "File:123"])
async def test_context_rejects_outside_or_remote_targets(setup, path):
    adapter, _, _ = setup
    with pytest.raises(ValueError):
        await adapter.context("demo", path)


async def test_context_rejects_symlink_escape_and_untracked_file(setup):
    adapter, repo, _ = setup
    (repo / "link.py").symlink_to("/etc/passwd")
    (repo / "secret.env").write_text("do not read")
    for path in ["link.py", "secret.env"]:
        with pytest.raises(ValueError):
            await adapter.context("demo", path)


async def test_invalid_repo_and_ranges(setup):
    adapter, _, _ = setup
    with pytest.raises(ValueError):
        await adapter.search("missing", "x")
    for start, end in [(0, 2), (4, 3), (1, 10001)]:
        with pytest.raises(ValueError):
            await adapter.context("demo", "app.py", start, end)
    with pytest.raises(ValueError):
        await adapter.search("demo", "")


async def test_index_only_uses_configured_repository(setup):
    adapter, repo, _ = setup
    result = await adapter.index("demo")
    assert json.loads(result["output"])["args"] == ["workspace", "index", str(repo)]


async def test_no_match_is_success_and_cli_failure_is_error(setup):
    adapter, _, _ = setup
    result = await adapter.search("demo", "NOMATCH")
    assert result["output"] == ""
    assert not result["truncated"]
    with pytest.raises(RuntimeError, match="fixture command failed"):
        await adapter.search("demo", "ERROR")


async def test_busy_index_has_actionable_retry_error(setup):
    adapter, _, _ = setup
    with pytest.raises(RuntimeError, match="busy.*retry"):
        await adapter.search("demo", "BUSY")


async def test_output_is_bounded_and_timeout_is_reported(setup):
    adapter, _, _ = setup
    result = await asyncio.wait_for(adapter.search("demo", "FLOOD"), 3)
    assert result["truncated"]
    assert len(result["output"].encode()) <= 1024
    with pytest.raises(TimeoutError):
        await adapter.search("demo", "SLOW")


async def test_cancel_reaps_child_process(setup, tmp_path):
    adapter, _, _ = setup
    pidfile = tmp_path / "pid"
    fake = tmp_path / "orbit"
    fake.write_text(
        f"#!{sys.executable}\nimport os,time\n"
        f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\ntime.sleep(30)\n"
    )
    task = asyncio.create_task(adapter.search("demo", "anything"))
    for _ in range(100):
        if pidfile.exists():
            break
        await asyncio.sleep(0.01)
    assert pidfile.exists()
    pid = int(pidfile.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_config_requires_real_git_roots_and_executable(tmp_path):
    config = tmp_path / "bad.toml"
    config.write_text('[repositories]\nbad = "/not/a/checkout"\n')
    with pytest.raises(ValueError):
        load_config(config)


async def test_real_stdio_lists_tools_and_returns_results_and_errors(setup):
    _, _, config = setup
    transport = StdioServerParameters(
        command=sys.executable,
        args=["-m", "orbit_mcp.server", "--config", str(config)],
    )
    async with Client(transport, read_timeout_seconds=10) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "orbit_repositories",
            "orbit_search",
            "orbit_context",
            "orbit_index",
        }
        result = await client.call_tool("orbit_search", {"repository": "demo", "query": "hello"})
        assert not result.is_error
        assert "hello" in str(result)
        error = await client.call_tool(
            "orbit_context", {"repository": "demo", "targets": ["../no"]}
        )
        assert error.is_error


async def test_chunked_output_is_not_lost(setup, tmp_path):
    adapter, _, _ = setup
    fake = tmp_path / "orbit"
    fake.write_text(
        f"#!{sys.executable}\nimport time\n"
        "print('first', flush=True)\ntime.sleep(0.1)\nprint('second', flush=True)\n"
    )
    result = await adapter.search("demo", "x")
    assert result["output"] == "first\nsecond\n"


async def test_batch_context_combines_files_and_symbols(setup):
    adapter, repo, _ = setup
    result = await adapter.context_batch("demo", ["app.py:1-2", "symbol:double"])
    assert json.loads(result["output"])["args"] == [
        "context",
        "--repo",
        str(repo),
        "--",
        f"{repo}/app.py:1-2",
        "double",
    ]


@pytest.mark.parametrize(
    "target", ["symbol:mr:42", "symbol:File:123", "symbol:repo::Foo", "../x:1-2"]
)
async def test_batch_cannot_select_remote_or_other_graph_targets(setup, target):
    adapter, _, _ = setup
    with pytest.raises(ValueError):
        await adapter.context_batch("demo", [target])


async def test_search_modes_and_path_scope(setup):
    adapter, repo, _ = setup
    result = await adapter.search("demo", "double", mode="definitions", path="app.py")
    args = json.loads(result["output"])["args"]
    assert "def:double" in args
    assert args[-1] == str(repo / "app.py")
    result = await adapter.search("demo", "dou.*", mode="regex")
    assert "-F" not in json.loads(result["output"])["args"]
    for mode, query, path in [
        ("regex", "repo:other/project", "."),
        ("definitions", "x mr:42", "."),
        ("literal", "x", ".."),
        ("unknown", "x", "."),
    ]:
        with pytest.raises(ValueError):
            await adapter.search("demo", query, mode=mode, path=path)


async def test_large_flood_does_not_deadlock_during_cleanup(setup, tmp_path):
    adapter, _, _ = setup
    fake = tmp_path / "orbit"
    fake.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.write('x' * 10000000)\n")
    result = await asyncio.wait_for(adapter.search("demo", "x"), 3)
    assert result["truncated"]
    assert len(result["output"]) == 1024


async def test_tracked_check_treats_filename_as_literal(setup):
    adapter, repo, _ = setup
    (repo / "a.env").write_text("tracked")
    (repo / "[a].env").write_text("untracked secret")
    subprocess.run(["git", "-C", str(repo), "add", "a.env"], check=True)
    with pytest.raises(ValueError, match="tracked"):
        await adapter.context_batch("demo", ["[a].env"])


@pytest.mark.parametrize("name", ["secrets.env", "secrets"])
async def test_symbol_cannot_be_reinterpreted_as_a_file(setup, name):
    adapter, repo, _ = setup
    (repo / name).write_text("untracked secret")
    with pytest.raises(ValueError, match="file"):
        await adapter.context_batch("demo", ["symbol:" + name])
