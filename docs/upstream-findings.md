# What GitLab's prerelease history tells us

Research date: 2026-10-30. Reviewed release notes v0.144.0–v1.0.0 and relevant
public issues/MRs through GitLab's API. Issue state is recorded at review time;
an old or still-open report does not prove the problem remains in Orbit 1.0.0.
These are implementation priorities, not claims of full feature parity.

## Why local MCP disappeared

[MR !3234](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/merge_requests/3234)
removes local MCP and directs local agents to `grep`/`context`, while MCP clients
use the hosted endpoint. It lists no related issue and does not attribute the
removal to an inherent protocol defect. **Inference:** a thin adapter around the
maintained CLI is a better maintenance boundary than reviving its old internals.
The MR's discussion endpoint required authentication, so private discussion was
not reviewed. We do not infer undocumented business or engineering motives.

## Prioritized findings

| Priority | Upstream evidence | Implication for this adapter | Current status |
| --- | --- | --- | --- |
| P1 | [#1432](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1432), [!3130](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/merge_requests/3130): cold indexing exceeded common 120-second agent deadlines; parallel reads failed after five seconds | Offer background index start and honest status; distinguish exit 75 (temporary lock timeout), avoid blind retries/rebuilding | CLI 1.0 inherits bounded waits. Adapter has bounded execution and cleanup; background/status workflow remains next work |
| P1 | [#658](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/658), [#1010](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1010): non-repo/empty-repo and environment errors confused users | Validate checkout roots and initial commits; give a repair action; add explicit doctor/connection check | Root validation and real stdio smoke tests implemented; standalone doctor remains next work |
| P1 | [#1384](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1384): setup could succeed without registering any MCP server | Verify actual tool discovery and one tool call; say which client was tested | Implemented SDK transport test and SSH deployment check; Windows/macOS hardware still requires client-side verification |
| P1 | [#1219](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1219), [#1220](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1220), [#885](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/885): Go cross-package calls, TS typed/interface calls and nested tsconfig aliases can miss edges | Tell agents graph results may be incomplete; cross-check source searches. Add reproductions before assuming fixed or broken | Adapter guidance and source search available; resolver repairs belong upstream, not in MCP transport |
| P2 | [#1341](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1341): Bash/HCL/Elixir/Lua/Zig definitions absent from grep in 0.132/0.133 | Add language-specific regression fixtures; offer source-text fallback when graph search misses | Real 1.0 test covers literal Bash/HCL searches; does not establish complete definition coverage for all five languages |
| P2 | [#1251](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1251): hosted MCP spent multiple agent turns discovering tools/schema before queries | Direct named tools, compact schemas, batching; avoid a list-commands/invoke-command hierarchy | Four direct tools and batched context implemented. This is a lesson from hosted MCP, not evidence of the same defect in old local MCP |
| P2 | [#1377](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1377): hosted errors were hidden or not actionable | Preserve command errors, distinguish no matches from failures, provide corrective hints | Tool errors preserve CLI diagnostics; no-match search succeeds; timeout guidance implemented |

## Fixes already inherited from the maintained CLI

- [0.153.0](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/releases/v0.153.0): incremental indexing engine.
- [0.160.0](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/releases/v0.160.0): `workspace index --async/--wait`, waiting reads, refresh-on-read grep/context.
- [0.161.0](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/releases/v0.161.0): cheaper reindexing.
- [0.162.0](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/releases/v0.162.0): additional context graph neighbors.

We reuse these by calling 1.0.0; porting old MCP code would not automatically
inherit them. Edited-file refresh and caller context have real integration tests.

## Problems not to misattribute to this adapter

[#1440](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1440)
reports wrong file content when hosted Gitaly responses deduplicate identical
blobs. Its reproduction explicitly uses Orbit Remote. This adapter does not use
that hosted content resolver; we should not claim to fix it.

Cross-project semantic edges, hosted merge requests/pipelines, and language
resolver accuracy require indexer/backend work. Searching several configured
repositories could help exploration, but would not manufacture missing graph
relationships. A wrapper must never present text matches as proven call edges.

## Recommended next increment

1. Add a background-index/start-and-check workflow around existing CLI features,
   with distinct busy/failed/ready states and cross-session concurrency tests.
2. Add a `--check` command for executable version, configured repos/HEAD, and
   sample MCP discovery; produce per-client setup examples from that result.
3. Add small Go/TypeScript resolution fixtures from the reports and label what
   is reproduced on the installed Orbit version before considering fallbacks.

Keep this first version small. Do not add a SQL engine, hosted API layer, or a
second parser merely because those capabilities existed elsewhere in Orbit.
