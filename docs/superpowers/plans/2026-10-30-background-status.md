# Background indexing, status, and diagnostics

Approved scope: implement the requested next increment, verify on devbox, then
investigate additional upstream reports. Work starts at c906be0 in an isolated
worktree; preserve the pre-existing test edit in the original checkout.

## Design

Reuse Orbit 1.0's native `workspace index --async`. Persist only job identity
(PID plus Linux process start time and boot ID) in private adapter state, shared
across MCP sessions. A short file lock prevents simultaneous adapter starts;
Orbit remains responsible for database locking. Repeated starts reuse a live
worker. Detached jobs deliberately survive MCP disconnects.

Status combines the selected repository's manifest row, current Git HEAD, dirty
working tree, and observed worker identity. Manifest state is not proof of worker
liveness or successful completion. In particular, report dead observed workers with an
unfinished manifest as unknown (external jobs may own it); never invent exit codes or progress.
Report other uncertain outcomes explicitly. Do not expose other repositories,
global database paths, or index log contents. Bound all subprocess output.

`--check` emits JSON and an exit status after checking Orbit version, configured
Git roots/initial commits, writable adapter state, and a real MCP handshake plus
repository-list call. It does not index or modify checkouts. Its scope is the
server-side connection; desktop clients still need their own SSH test.

## Tasks

- [x] Tests first: native async launch, cross-session deduplication/status,
      stale/dirty/interrupted states, malformed output and unknown aliases.
- [x] Implement background launch (default), explicit foreground compatibility,
      status tool, private atomic state and bounded structured output handling.
- [x] Tests first and implementation: diagnostic command, useful empty-repo and
      missing executable errors, real MCP discovery, exit status.
- [x] Real Orbit integration, cross-session polling, full tests and lint.
- [x] Further upstream issue/release investigation and small reproductions;
      document evidence and prioritize follow-ups without speculative expansion.
- [ ] One fresh review, fixes, publish, install on devbox, verify SSH transport.

## Decisions / evidence

- Native async always returns PID, status (`queued`, `indexing`, `indexed`) and
  a server log path. Its short startup handshake can fail while the worker lives;
  report uncertain starts and advise checking status before retrying.
- A completed native child has no retrievable exit code after detachment.
  Keep worker state and manifest state separate; an indexed manifest is a
  snapshot, not a success assertion for the latest requested refresh.

## Verification ledger

- New background/status tests failed first on missing state/config support;
  implementation then passed them. Diagnostic tests failed first because
  `--check` was unknown; implementation then passed them.
- Full suite: 41 passed, including real Orbit 1.0 and reconnect/status polling.
  Ruff lint and formatting passed. Real devbox configuration passed `--check`.
- Further probe: Go cross-package and TS concrete-field caller edges present;
  TS interface caller absent from concrete method context; Bash/Elixir/Lua/Zig
  definition queries succeed, HCL output definition query misses. See findings.

- Final review found three important issues; no deferred minor findings.
- Final fix: external worker attribution — new regression failed first, then
  status changed to unknown with explicit last-request worker scope.
- Final fix: inherited stderr exceeded command deadline — regression failed
  first, then stderr drain moved inside timeout with cancellation shielding.
- Final fix: queued launch observation went stale — regression failed first,
  then live queued workers report queued_or_indexing.
- Ruling: native manifest ownership is unavailable, so interrupted/failed versus
  a later external job remains unknown. This sacrifices a definitive failure
  label to avoid incorrectly reporting live work as failed.
