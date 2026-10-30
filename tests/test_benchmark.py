import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "benchmark", Path(__file__).parents[1] / "scripts/benchmark_codex.py"
)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_usage_counts_cached_tokens_once_and_retains_quality_evidence():
    result = benchmark.summarize_events(
        [
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 20},
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 80, "cached_input_tokens": 30, "output_tokens": 10},
            },
            {"type": "item.completed", "item": {"type": "mcp_tool_call"}},
            {"type": "item.completed", "item": {"type": "command_execution"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}},
        ]
    )
    assert result["usage"] == {
        "input_tokens": 180,
        "cached_input_tokens": 70,
        "output_tokens": 30,
        "uncached_input_tokens": 110,
        "total_tokens": 210,
    }
    assert result["mcp_calls"] == result["shell_calls"] == 1
    assert result["answer"] == "answer"


def test_missing_usage_is_not_zero_cost_success():
    result = benchmark.summarize_events([{"type": "turn.failed", "error": {"message": "failure"}}])
    assert result["usage"] is None
    assert result["errors"]


def test_impossible_cache_accounting_is_rejected():
    with pytest.raises(ValueError):
        benchmark.summarize_events(
            [
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 10, "cached_input_tokens": 20, "output_tokens": 1},
                }
            ]
        )


def test_failed_or_unrelated_mcp_calls_do_not_establish_orbit_treatment():
    items = [
        {
            "server": "orbit-bench",
            "tool": "orbit_search",
            "status": "failed",
            "error": {"message": "approval denied"},
            "result": None,
        },
        {
            "server": "orbit-bench",
            "tool": "orbit_repositories",
            "status": "completed",
            "error": None,
            "result": {"content": []},
        },
        {
            "server": "other",
            "tool": "orbit_search",
            "status": "completed",
            "error": None,
            "result": {"content": []},
        },
        {
            "server": "orbit-bench",
            "tool": "orbit_context",
            "status": "completed",
            "error": None,
            "result": {"isError": True, "content": []},
        },
    ]
    result = benchmark.summarize_events(
        [{"type": "item.completed", "item": {"type": "mcp_tool_call", **item}} for item in items]
    )
    assert result["successful_orbit_retrievals"] == 0
    assert result["failed_mcp_calls"] == 2


def test_successful_orbit_retrieval_is_recorded():
    result = benchmark.summarize_events(
        [
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "server": "orbit-bench",
                    "tool": "orbit_search",
                    "status": "completed",
                    "error": None,
                    "result": {"content": [{"type": "text", "text": "source"}]},
                },
            }
        ]
    )
    assert result["successful_orbit_retrievals"] == 1
