"""Server-side diagnostics, including a real stdio handshake and tool call."""

import asyncio
import sys
import tempfile
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from orbit_mcp.indexing import git_output


async def check(path: Path) -> dict:
    from orbit_mcp.server import Adapter, load_config

    checks = {}

    async def probe(name, operation):
        try:
            checks[name] = {"ok": True, **await operation()}
        except Exception as error:
            checks[name] = {"ok": False, "error": str(error)}

    async def configuration():
        nonlocal config
        config = load_config(path)
        return {}

    config = None
    await probe("config", configuration)
    if config is not None:
        adapter = Adapter(config)

        async def version():
            result = await adapter.run(next(iter(config.repositories.values())), ["--version"])
            if result["truncated"] or not result["output"].strip().startswith("orbit "):
                raise ValueError("Unexpected Orbit version response; install the GitLab Orbit CLI")
            return {"version": result["output"].strip(), "tested_version": "1.0.0"}

        async def repositories():
            for root in config.repositories.values():
                await git_output(root, "rev-parse", "--verify", "HEAD")
            return {"aliases": sorted(config.repositories)}

        async def storage():
            config.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.TemporaryFile(dir=config.state_dir) as stream:
                stream.write(b"check")
                stream.flush()
            return {}

        async def mcp():
            transport = StdioServerParameters(
                command=sys.executable,
                args=["-m", "orbit_mcp.server", "--config", str(path.resolve())],
            )
            async with asyncio.timeout(20):
                async with Client(transport, read_timeout_seconds=10) as client:
                    tools = await client.list_tools()
                    expected = {
                        "orbit_repositories",
                        "orbit_search",
                        "orbit_context",
                        "orbit_index",
                        "orbit_status",
                    }
                    if {tool.name for tool in tools.tools} != expected:
                        raise RuntimeError("MCP discovery returned an unexpected tool set")
                    result = await client.call_tool("orbit_repositories", {})
                    if result.is_error:
                        raise RuntimeError("MCP repository-list call failed")
                    return {"tools": len(expected), "repository_call": True}

        await probe("orbit", version)
        await probe("repositories", repositories)
        await probe("state", storage)
        await probe("mcp", mcp)
    return {
        "ok": all(item["ok"] for item in checks.values()),
        "checks": checks,
        "scope": "Server-side stdio connection only; run an SSH check from each desktop client. "
        "Does not index repositories or certify graph freshness.",
    }
