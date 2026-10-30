"""Run paired, independent Codex sessions; retain actual usage and private traces.

This is a small benchmark runner, not an automatic answer grader. Review each
answer against an independently prepared rubric before interpreting savings.
See docs/benchmark-methodology.md. Requires the separately installed Codex CLI.
"""

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path


def summarize_events(events: list[dict]) -> dict:
    usages = [
        event["usage"]
        for event in events
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict)
    ]
    errors = [event for event in events if event.get("type") in {"error", "turn.failed"}]
    items = [event.get("item", {}) for event in events if event.get("type") == "item.completed"]
    result = {
        "completed_turns": len(usages),
        "errors": errors,
        "shell_calls": sum(item.get("type") == "command_execution" for item in items),
        "mcp_calls": sum(item.get("type") == "mcp_tool_call" for item in items),
        "answer": "\n".join(
            item.get("text", "") for item in items if item.get("type") == "agent_message"
        ),
    }
    mcp_items = [item for item in items if item.get("type") == "mcp_tool_call"]

    def failed(item):
        payload = item.get("result") or {}
        return bool(
            item.get("error")
            or item.get("status") == "failed"
            or payload.get("isError")
            or payload.get("is_error")
        )

    result["failed_mcp_calls"] = sum(failed(item) for item in mcp_items)
    result["successful_orbit_retrievals"] = sum(
        item.get("server") == "orbit-bench"
        and item.get("tool") in {"orbit_search", "orbit_context"}
        and item.get("status") == "completed"
        and isinstance(item.get("result"), dict)
        and not failed(item)
        for item in mcp_items
    )
    required = {"input_tokens", "cached_input_tokens", "output_tokens"}
    if usages and all(required <= usage.keys() for usage in usages):
        usage = {key: sum(item[key] for item in usages) for key in required}
        if (
            any(type(value) is not int or value < 0 for value in usage.values())
            or usage["cached_input_tokens"] > usage["input_tokens"]
        ):
            raise ValueError("Invalid reported token usage")
        result["usage"] = {
            **usage,
            "uncached_input_tokens": usage["input_tokens"] - usage["cached_input_tokens"],
            "total_tokens": usage["input_tokens"] + usage["output_tokens"],
        }
    else:
        result["usage"] = None  # Missing usage is not zero tokens or a successful sample.
    return result


def run_one(args, task: dict, mode: str, repeat: int) -> dict:
    stem = f"{task['id']}-{repeat}-{mode}"
    output = args.output / stem
    output.mkdir(mode=0o700)  # Never silently overwrite a prior experiment.
    common = (
        "This is a controlled read-only code-navigation benchmark on a fixed snapshot. "
        "Answer only the question below, with concrete source file and line references. "
        "Do not edit files, run tests, install dependencies, access network/services, read "
        "credentials, inspect other directories or prior benchmark runs, or delegate. "
        "Use targeted searches and minimal relevant source ranges. Be concise (about 180 "
        "words; enough to cover the requested facts). Do not add plans or progress narration. "
    )
    treatment = (
        "Use shell tools (rg and targeted source reads) only. Do not use Orbit or MCP. "
        if mode == "baseline"
        else "Use the orbit-bench MCP tools for initial search and context, repository alias "
        "project. The graph is already indexed; do not index or poll status. Use shell "
        "source reads only if MCP evidence is missing or insufficient; do not call the "
        "Orbit CLI directly. Graph relationships may be incomplete. "
    )
    prompt = common + treatment + "\n\nQuestion: " + task["question"]
    command = [
        args.codex,
        "--no-daemon",
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--json",
        "--color",
        "never",
        "--sandbox",
        "read-only",
        "--cd",
        str(args.project),
        "--model",
        args.model,
        "-c",
        "model_reasoning_effort=" + json.dumps(args.effort),
        "--disable",
        "plugins",
        "--disable",
        "apps",
        "--disable",
        "multi_agent",
        "--enable",
        "skip_host_skill_discovery",
        "-c",
        'web_search="disabled"',
    ]
    if mode == "orbit":
        command += [
            "-c",
            "mcp_servers.orbit-bench.command=" + json.dumps(str(args.adapter)),
            "-c",
            "mcp_servers.orbit-bench.args=" + json.dumps(["--config", str(args.mcp_config)]),
            "-c",
            "mcp_servers.orbit-bench.env.ORBIT_DATA_DIR=" + json.dumps(str(args.orbit_data_dir)),
        ]
        # Authorize only the requested local retrieval tools in this ephemeral
        # benchmark. Do not alter user config or globally relax approvals.
        for tool in ("orbit_repositories", "orbit_search", "orbit_context"):
            command += ["-c", f'mcp_servers.orbit-bench.tools.{tool}.approval_mode="approve"']
        command += ["-c", "mcp_servers.orbit-bench.required=true"]
    command += ["-"]
    (output / "request.json").write_text(
        json.dumps({"command": command, "prompt": prompt}, indent=2)
    )
    started = time.monotonic()
    timed_out = False
    with (output / "events.jsonl").open("w") as stdout, (output / "stderr.log").open("w") as stderr:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            text=True,
        )
        try:
            process.communicate(prompt, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
    events = []
    parse_errors = 0
    for line in (output / "events.jsonl").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            parse_errors += 1
    result = {
        "task": task["id"],
        "mode": mode,
        "repeat": repeat,
        "seconds": time.monotonic() - started,
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "event_parse_errors": parse_errors,
        **summarize_events(events),
    }
    result["valid_run"] = bool(result["usage"]) and not (
        timed_out or process.returncode or result["errors"] or parse_errors
    )
    result["treatment_used"] = (
        result["successful_orbit_retrievals"] > 0 if mode == "orbit" else result["mcp_calls"] == 0
    )
    (output / "result.json").write_text(json.dumps(result, indent=2))
    (output / "answer.txt").write_text(result["answer"])
    print(
        json.dumps(
            {key: value for key, value in result.items() if key not in {"answer", "errors"}}
        ),
        flush=True,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, required=True, help="JSON with tasks [{id,question}]")
    parser.add_argument("--output", type=Path, required=True, help="Private raw-trace directory")
    parser.add_argument("--mcp-config", type=Path, required=True)
    parser.add_argument("--orbit-data-dir", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="high")
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--task", help="Run one task ID (useful for preflight)")
    parser.add_argument("--mode", choices=["baseline", "orbit"], help="Run one arm only")
    args = parser.parse_args()
    os.umask(0o077)
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    tasks = json.loads(args.tasks.read_text())["tasks"]
    tasks = [task for task in tasks if not args.task or task["id"] == args.task]
    if not tasks or args.repeats < 1 or args.timeout <= 0:
        parser.error("Select existing tasks, positive repeats and timeout")
    results = []
    for repeat in range(args.repeats):
        for index, task in enumerate(tasks):
            modes = ["baseline", "orbit"] if (repeat + index) % 2 == 0 else ["orbit", "baseline"]
            for mode in [args.mode] if args.mode else modes:
                result = run_one(args, task, mode, repeat)
                results.append(result)
                (args.output / "results.json").write_text(json.dumps(results, indent=2))
                if not result["valid_run"] or not result["treatment_used"]:
                    raise SystemExit(
                        "Invalid run retained; inspect before spending more benchmark tokens"
                    )


if __name__ == "__main__":
    main()
