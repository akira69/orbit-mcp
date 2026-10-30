# No-match guidance and a project token benchmark

User requested both improvements and parallel development. The prior proposed
scope was compact no-match guidance without a hidden fallback, and measured
agent usage on a real project. Continue the authorized implementation directly.

- [ ] Guidance stream: failing-first tests, guidance on true search misses only,
  preserve errors/truncation, no hidden fallback calls, verify through MCP.
- [ ] Benchmark stream: select a real project; fixed snapshot and read-only tasks;
  comparable independent sessions with the same model/settings; baseline source
  tools versus MCP tools; collect reported input/cached/output tokens, time and
  calls; score factual answers before concluding savings.
- [ ] Integrate, review, full tests, publish/install, SSH check.
- [ ] Record benchmark methodology, raw-data locations, quality/limitations and
  an evidence-based next priority. Keep private project code/results out of the
  public repository unless the project is confirmed public.

Choices: explicit short guidance instead of automatically running another query
keeps response cost and graph-versus-text semantics visible. A real agent A/B
experiment is preferred to tokenizing canned tool outputs; the latter is only
an explicitly labelled fallback if agent usage measurements are unavailable.
Use a small initial sample and report variance and limitations rather than a
universal savings claim. Benchmark work must not change the chosen project.

## Verification and decisions

- Guidance tests failed before implementation. Complete searches report matched;
  true misses receive hints. Truncation remains inconclusive, errors remain
  errors, and no automatic query is added.
- Review found two important issues: benchmark counted denied MCP attempts as
  treatment, and native Orbit uses exit 1 for both misses and storage failures.
  Regression tests failed first, then the parser required successful relevant
  retrievals and search stderr handling preserved operational errors.
- Ruling: exit 1 with any stderr is conservatively an error. Harmless warnings
  can therefore require operator inspection; claiming an operational failure
  as a search miss would be worse. Invalid-regex empty output cannot be reliably
  distinguished from a normal miss, so hints describe reported outcomes only.
- Setup trials with MCP approval denials are retained privately and excluded as
  invalid experiments. Per-tool approval settings are now limited to the three
  snapshot retrieval/discovery tools; no global policy or user config changes.
- Private project: use a fixed snapshot; publish only anonymous aggregate
  results. Source, questions, rubrics, and answers remain private.
