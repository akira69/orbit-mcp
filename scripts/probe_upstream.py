"""Reproduce small upstream language-report shapes, without touching real indexes.

Run: python3 scripts/probe_upstream.py > /tmp/orbit-language-probe.json
This records observations, not a claim that the full upstream repro is fixed.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

FILES = {
    "go.mod": "module example.org/probe\n\ngo 1.21\n",
    "api/play.go": "package api\nfunc PlayOrRetryJobs() int { return 1 }\n",
    "main.go": 'package main\nimport "example.org/probe/api"\n'
    "func launchJobs() int { return api.PlayOrRetryJobs() }\n",
    "terminal.ts": "export interface ITerminalChildProcess { start(): void; }\n"
    "export class TerminalProcess implements ITerminalChildProcess {\n"
    '  start(): void { console.log("started"); }\n}\n',
    "service.ts": 'import { TerminalProcess, ITerminalChildProcess } from "./terminal";\n'
    "class Service {\n  private process: TerminalProcess = new TerminalProcess();\n"
    "  launchTyped(): void { this.process.start(); }\n"
    "  launchInterface(pty: ITerminalChildProcess): void { pty.start(); }\n}\n",
    "helper.sh": 'log_info() { echo "hello"; }\n',
    "infra.tf": 'output "bootstrap_bucket" { value = "example" }\n',
    "sample.ex": "defmodule Probe do\n  def greet_elixir(name), do: name\nend\n",
    "sample.lua": "function greet_lua(name)\n  return name\nend\n",
    "sample.zig": "pub fn greet_zig(value: i32) i32 { return value; }\n",
}


def main():
    with tempfile.TemporaryDirectory(prefix="orbit-language-probe-") as directory:
        root = Path(directory)
        repo = root / "repo"
        repo.mkdir()
        for name, content in FILES.items():
            file = repo / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        env = {
            **os.environ,
            "ORBIT_DATA_DIR": str(root / "data"),
            "ORBIT_TELEMETRY_ENABLED": "false",
        }
        for name in ("GITLAB_TOKEN", "GLAB_TOKEN", "GITLAB_URL"):
            env.pop(name, None)

        def run(*args):
            result = subprocess.run(
                args, cwd=repo, env=env, capture_output=True, text=True, timeout=120
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        for args in [
            ("git", "init", "-q"),
            ("git", "add", "."),
            (
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ),
        ]:
            result = run(*args)
            assert result["exit_code"] == 0, result
        observations = {
            "version": run("orbit", "--version"),
            "index": run("orbit", "workspace", "index", str(repo)),
        }
        for name in ("log_info", "bootstrap_bucket", "greet_elixir", "greet_lua", "greet_zig"):
            observations[f"def:{name}"] = run(
                "orbit", "grep", "--repo", str(repo), "--", f"def:{name}"
            )
        for name in ("PlayOrRetryJobs", "TerminalProcess::start"):
            observations[f"context:{name}"] = run(
                "orbit", "context", "--repo", str(repo), "--", name
            )
        print(json.dumps(observations, indent=2).replace(str(root), "<temporary-root>"))


if __name__ == "__main__":
    main()
