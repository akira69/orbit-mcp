"""Opt-in checks against a separately installed Orbit executable."""

import asyncio
import json
import os
import shutil
import subprocess
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters


@pytest.mark.skipif(os.environ.get("ORBIT_INTEGRATION") != "1", reason="Set ORBIT_INTEGRATION=1")
async def test_real_orbit_over_mcp(tmp_path):
    orbit = shutil.which("orbit")
    assert orbit, "Install Orbit to run integration checks"
    repo = tmp_path / "fixture"
    repo.mkdir()
    (repo / "maths.py").write_text("def double(value):\n    return value * 2\n")
    (repo / "main.py").write_text(
        "from maths import double\n\ndef calculate():\n    return double(21)\n"
    )
    (repo / "helper.sh").write_text('log_info() { echo "hello"; }\n')
    (repo / "infra.tf").write_text('output "bootstrap_bucket" { value = "example" }\n')
    for args in [
        ["git", "init", "-q"],
        ["git", "add", "."],
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
    ]:
        await asyncio.to_thread(subprocess.run, args, cwd=repo, check=True)
    config = tmp_path / "config.toml"
    config.write_text(
        f"orbit = {json.dumps(orbit)}\n[repositories]\ndemo = {json.dumps(str(repo))}\n"
    )
    transport = StdioServerParameters(
        command=sys.executable,
        args=["-m", "orbit_mcp.server", "--config", str(config)],
        env={**os.environ, "ORBIT_DATA_DIR": str(tmp_path / "graph")},
    )
    async with Client(transport, read_timeout_seconds=30) as client:
        result = await client.call_tool("orbit_index", {"repository": "demo"})
        assert not result.is_error, result
        for mode in ["literal", "regex", "definitions"]:
            result = await client.call_tool(
                "orbit_search", {"repository": "demo", "query": "double", "mode": mode}
            )
            assert not result.is_error, result
            assert "maths.py" in str(result)
        result = await client.call_tool(
            "orbit_context", {"repository": "demo", "targets": ["symbol:double", "main.py:1-4"]}
        )
        assert not result.is_error, result
        assert "calculate" in str(result)
        assert "calls" in str(result)
        (repo / "maths.py").write_text("def double(value):\n    return value + value\n")
        result = await client.call_tool(
            "orbit_context", {"repository": "demo", "targets": ["maths.py:1-2"]}
        )
        assert not result.is_error, result
        assert "value + value" in str(result)
        # Upstream #1341 reported these languages missing from local grep.
        for query, filename in [("log_info", "helper.sh"), ("bootstrap_bucket", "infra.tf")]:
            result = await client.call_tool("orbit_search", {"repository": "demo", "query": query})
            assert not result.is_error, result
            assert filename in str(result)
