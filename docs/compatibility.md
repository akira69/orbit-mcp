# GitLab Orbit compatibility

Checked against Orbit 1.0.0 and the historical v0.164.0 interface on 2026-10-30.
The 1.0.0 release removed local MCP; there is no local 1.0.0 MCP to match. Some
website pages still list it.

| Capability | Adapter | Difference |
| --- | --- | --- |
| Index local graph | `orbit_index` | Native detached indexing by default; foreground opt-in |
| Index status | `orbit_status` | Worker identity, manifest snapshot, HEAD/dirty state |
| Diagnostic | `--check` | Version, repo/state checks and real MCP discovery/call |
| Choose repository | Named allowlist | Does not expose every globally indexed repo |
| Search source | Literal, regex, definitions; path scope | No remote qualifiers; regex excludes colon |
| Definition/caller context | `symbol:Name` | Current `context`, not global graph IDs |
| Batch reads | 20 file/range/symbol targets | One CLI call |
| Working-tree updates | Current CLI handles refresh | Real integration test verifies edited file |
| Empty search | Successful empty response | Other failures become tool errors |
| Large output | Bounded, explicit truncation | Narrow query/range to retrieve more |
| Timeout/disconnect | Kill and reap foreground process group | Explicit background indexes survive disconnects |
| Historical SQL/schema | Omitted | Avoid binding clients to DuckDB internals |
| GitLab MRs/issues/pipelines | Omitted | Separate authenticated hosted service |
| HTTP transport | Omitted | SSH carries stdio on Windows/macOS |

Implementation bug fixed: a single pipe read could lose later output chunks.
The runner now collects until EOF or the output budget, with a staggered-output
regression test. Arguments are passed without a shell and local targets are
validated before command execution.

References:
- [CLI](https://docs.gitlab.com/orbit/cli/)
- [1.0.0 release](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/releases/v1.0.0)
- [Historical MCP](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/blob/v0.164.0/crates/orbit-cli/src/mcp.rs)
- [Hosted MCP](https://docs.gitlab.com/orbit/agents/mcp/)

No historical implementation code is copied or redistributed.
