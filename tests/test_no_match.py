import json
import subprocess
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from orbit_mcp.server import Adapter, Config


@pytest.fixture
def cli_result(tmp_path):
    def make(exit_code, output="", stderr=""):
        repo = tmp_path / "repo"
        repo.mkdir()
        calls = tmp_path / "calls.jsonl"
        executable = tmp_path / "orbit"
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            f"with open({str(calls)!r}, 'a') as log:\n"
            "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            f"sys.stdout.write({output!r})\n"
            f"sys.stderr.write({stderr!r})\n"
            f"sys.exit({exit_code})\n"
        )
        executable.chmod(0o755)
        adapter = Adapter(Config(str(executable), {"demo": repo}, max_output_bytes=1024))
        return adapter, calls

    return make


@pytest.mark.parametrize("mode", ["literal", "regex", "definitions"])
async def test_complete_miss_has_guidance_without_fallback(cli_result, mode):
    adapter, calls = cli_result(1, "No matches found\n")
    result = await adapter.search("demo", "calculate", mode=mode)
    assert result["matched"] is False
    assert result["output"] == "No matches found\n"
    assert result["truncated"] is False
    assert "orbit_search" in result["hint"]
    assert "orbit_context" in result["hint"]
    assert "tracked" in result["hint"]
    if mode == "definitions":
        assert "literal" in result["hint"]
        assert "does not prove" in result["hint"]
    elif mode == "regex":
        assert "regex syntax" in result["hint"]
        assert "reported" in result["hint"]
    assert len(calls.read_text().splitlines()) == 1


@pytest.mark.parametrize("output", ["", "No matches found\n", "app.py:1:def calculate():\n"])
async def test_success_does_not_infer_miss_from_human_output(cli_result, output):
    adapter, _ = cli_result(0, output)
    result = await adapter.search("demo", "calculate")
    assert result == {"output": output, "truncated": False, "matched": True}


async def test_empty_exit_one_is_still_a_miss(cli_result):
    adapter, _ = cli_result(1)
    result = await adapter.search("demo", "calculate", mode="definitions")
    assert result["matched"] is False
    assert "literal" in result["hint"]


@pytest.mark.parametrize("mode", ["literal", "regex", "definitions"])
@pytest.mark.parametrize("diagnostic", ["Error: File exists\n", "warning: index unavailable\n"])
async def test_exit_one_with_diagnostics_is_not_reported_as_miss(cli_result, mode, diagnostic):
    adapter, calls = cli_result(1, stderr=diagnostic)
    with pytest.raises(RuntimeError, match="cannot confirm no matches") as failure:
        await adapter.search("demo", "calculate", mode=mode)
    assert diagnostic in str(failure.value)
    assert len(calls.read_text().splitlines()) == 1


async def test_success_keeps_diagnostics_visible(cli_result):
    adapter, _ = cli_result(0, "app.py:1:calculate\n", "warning: fixture\n")
    result = await adapter.search("demo", "calculate")
    assert "app.py:1:calculate" in result["output"]
    assert "warning: fixture" in result["output"]
    assert result["matched"] is True
    assert "hint" not in result


@pytest.mark.parametrize("output", ["", "match\n"])
async def test_success_with_large_diagnostics_stays_bounded(cli_result, output):
    adapter, _ = cli_result(0, output, "x" * 2048)
    result = await adapter.search("demo", "calculate")
    assert result["truncated"] is True
    assert len(result["output"].encode()) <= 1024
    assert "matched" not in result
    assert "hint" not in result


@pytest.mark.parametrize("exit_code", [0, 1, 2])
async def test_truncated_output_has_no_match_claim_or_guidance(cli_result, exit_code):
    adapter, _ = cli_result(exit_code, "x" * 2048)
    result = await adapter.search("demo", "calculate", mode="definitions")
    assert result == {"output": "x" * 1024, "truncated": True}


@pytest.mark.parametrize("exit_code", [2, 75])
async def test_other_exit_codes_remain_errors(cli_result, exit_code):
    adapter, calls = cli_result(exit_code, "fixture error")
    with pytest.raises(RuntimeError, match="fixture error"):
        await adapter.search("demo", "calculate", mode="definitions")
    assert len(calls.read_text().splitlines()) == 1


async def test_generic_runner_does_not_add_search_metadata(cli_result):
    adapter, _ = cli_result(0, "indexed\n")
    result = await adapter.index("demo", background=False)
    assert result == {"output": "indexed\n", "truncated": False}


async def test_real_stdio_returns_definition_miss_guidance(cli_result, tmp_path):
    adapter, calls = cli_result(1)
    # load_config validates that configured roots are Git checkouts.
    repo = adapter.repository("demo")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    config = tmp_path / "config.toml"
    config.write_text(
        f"orbit = {json.dumps(adapter.config.orbit)}\n"
        f"[repositories]\ndemo = {json.dumps(str(repo))}\n"
    )
    transport = StdioServerParameters(
        command=sys.executable,
        args=["-m", "orbit_mcp.server", "--config", str(config)],
    )
    async with Client(transport, read_timeout_seconds=10) as client:
        result = await client.call_tool(
            "orbit_search",
            {"repository": "demo", "query": "calculate", "mode": "definitions"},
        )
        assert not result.is_error
        payload = json.loads(result.content[0].text)
        assert payload["matched"] is False
        assert "literal" in payload["hint"]
        assert len(calls.read_text().splitlines()) == 1
