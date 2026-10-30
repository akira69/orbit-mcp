# What GitLab's prerelease history tells us

Research date: 2026-10-30. Reviewed release notes v0.144.0–v1.0.0 and relevant
public issues/MRs through GitLab's API. Latest release rechecked: v1.0.0,
published 2026-10-29. Issue state is recorded at review time;
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
| P1 | [#1432](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1432), [!3130](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/merge_requests/3130): cold indexing exceeded common 120-second agent deadlines; parallel reads failed after five seconds | Offer background index start and honest status; distinguish exit 75 (temporary lock timeout), avoid blind retries/rebuilding | CLI 1.0 inherits bounded waits. Adapter has bounded execution and cleanup; native background launch, persistent worker observations and conservative status implemented in 0.2.0 |
| P1 | [#658](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/658), [#1010](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1010): non-repo/empty-repo and environment errors confused users | Validate checkout roots and initial commits; give a repair action; add explicit doctor/connection check | Root validation and real stdio smoke tests implemented; `--check` now validates initial commits and performs real MCP discovery/call |
| P1 | [#1384](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1384): setup could succeed without registering any MCP server | Verify actual tool discovery and one tool call; say which client was tested | Implemented SDK transport test and SSH deployment check; Windows/macOS hardware still requires client-side verification |
| P1 | [#1219](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1219), [#1220](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1220), [#885](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/885): Go cross-package calls, TS typed/interface calls and nested tsconfig aliases can miss edges | Tell agents graph results may be incomplete; cross-check source searches. Add reproductions before assuming fixed or broken | Adapter guidance and source search available; resolver repairs belong upstream, not in MCP transport |
| P2 | [#1341](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1341): Bash/HCL/Elixir/Lua/Zig definitions absent from grep in 0.132/0.133 | Add language-specific regression fixtures; offer source-text fallback when graph search misses | Real 1.0 test covers literal Bash/HCL searches; does not establish complete definition coverage for all five languages |
| P2 | [#1251](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1251): hosted MCP spent multiple agent turns discovering tools/schema before queries | Direct named tools, compact schemas, batching; avoid a list-commands/invoke-command hierarchy | Five direct tools and batched context implemented. This is a lesson from hosted MCP, not evidence of the same defect in old local MCP |
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

## Follow-up probes on installed Orbit 1.0.0

Run `python3 scripts/probe_upstream.py` for a disposable, offline reproduction.
These are small shape tests, not the original large application checkouts. The
results do not establish that an entire upstream issue is fixed.

| Report / shape | Observed on 1.0.0 | Decision |
| --- | --- | --- |
| [#1219](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1219): Go qualified cross-package call | `api.PlayOrRetryJobs` context includes `main.launchJobs` as a caller | Do not implement a speculative wrapper fix |
| [#1220](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1220): TS concrete typed field | `TerminalProcess::start` includes `Service::launchTyped` | Small concrete-field shape works |
| Same report: TS interface receiver | The same method's context omits `Service::launchInterface`, although its source calls `pty.start()` | Still a limitation for concrete-method caller questions; use literal search and inspect interface implementations |
| [#1341](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1341): language search coverage | `def:` finds Bash, Elixir, Lua and Zig functions in these fixtures | Old extension-wide failure is not reproduced for these functions |
| Same report: HCL output | `def:bootstrap_bucket` returns no match; literal search finds its Terraform source | A remaining definition-search limitation in this shape; literal search is the available fallback |

## More findings worth considering

- [#1053](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1053)
  requested XDG-aware storage and is now closed. The adapter uses XDG state by default and keeps its
  observations separate from Orbit's graph. It does not migrate upstream data.
- [#1164](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/1164)
  reports JS/TS scoped locals overwhelming graph search results in older builds.
  This is an indexer/ranking concern; blindly filtering names containing `@`
  would also discard valid symbols. Measure representative queries before
  adding any filtering to the adapter.
- Old local query compiler reports
  [#632](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/632) and
  [#637](https://gitlab.com/gitlab-org/orbit/knowledge-graph/-/work_items/637)
  concern hosted-schema assumptions in local SQL/graph traversal. This adapter
  exposes neither raw SQL nor that graph query language; don't import those
  surfaces solely to imitate a deprecated MCP tool list.

## Next priorities after 0.2.0

1. Implemented in 0.2.1: compact no-match guidance, including literal search or
   known-file context after definition misses. No hidden fallback. Real CLI
   probes also found exit 1 used for storage failures; diagnostic-bearing exits
   remain errors. Invalid regexes may be indistinguishable from empty results,
   so regex guidance explicitly suggests checking syntax.
2. A paired real-project benchmark is described in
   [the methodology](benchmark-methodology.md). Count end-to-end usage and grade
   answers; extra schemas, discovery and polling can offset smaller responses.
3. Expand resolution fixtures only for languages and shapes in actual projects,
   especially interfaces and nested TypeScript aliases. Backend fixes belong in
   Orbit; the adapter should remain small.

Do not add a SQL engine, hosted API layer, parser, or persistent indexing daemon
merely because related capabilities existed elsewhere in Orbit.
