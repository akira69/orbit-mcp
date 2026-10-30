# Measuring whether Orbit saves tokens

Use real task completion, not token estimates of hand-picked tool responses.
`scripts/benchmark_codex.py` launches fresh Codex CLI sessions and retains their
reported usage, tool events, answers, timing, and failures for inspection.

## Protocol

1. Freeze a real Git revision into a separate snapshot. Do not benchmark against
   an actively changing working tree or live services. Prepare an isolated Orbit
   data directory and index the snapshot once; record cold index time separately.
2. Write concrete read-only questions and independent factual rubrics before
   running either arm. Keep rubrics out of the answering sessions. Include simple
   lookups and questions that require relationships across files.
3. Use the same model, reasoning effort, question, snapshot and answer scope.
   The baseline uses shell search and targeted file reads. The Orbit arm uses MCP
   for initial retrieval and may fall back to source reads when evidence is
   insufficient. The cost of schemas, tool calls, errors and fallback is included.
4. Run independent sessions, alternating arm order across tasks and repetitions.
   Use at least two repetitions for an initial exploratory sample. Retain every
   run, including incomplete runs. A few questions are not a general benchmark.
5. Require successful Orbit search/context calls, not merely attempts or a
   repository-list call, before treating a sample as an MCP experiment. Stop on
   setup failures rather than silently measuring shell fallback as Orbit.
6. Grade final answers against the rubric with the treatment and token counts
   hidden from the reviewer. Inspect citations and substantive claims. A cheaper
   answer that misses required facts is not a demonstrated improvement.

## Metrics

- **Total model tokens:** reported input tokens plus output tokens, across all
  completed turns. Cached input is already part of input; never add it twice.
- **Uncached input:** input minus cached input. Report it separately because
  cache availability can make total tokens and billing-relevant usage diverge.
- **Output tokens, wall time, shell/MCP calls and failures:** retain separately.
- **Accuracy:** rubric points and unsupported claims, not just answer length.

Missing usage is unknown, not zero cost. No dollar estimates are made without
verified model/account pricing. Cold indexing is CPU/time overhead, not model
usage. Snapshot preparation, task authoring, evaluation and development tokens
are experiment costs, not per-task retrieval savings; record this exclusion.

## Running it

Use a private output directory: traces and answers can contain project source.
Do not commit raw results for private projects to this public repository.

```sh
python3 scripts/benchmark_codex.py \
  --project /tmp/fixed-project-snapshot \
  --tasks /private/benchmark/tasks.json \
  --output /private/benchmark/runs \
  --mcp-config /private/benchmark/mcp.toml \
  --orbit-data-dir /private/benchmark/graph \
  --adapter /absolute/path/orbit-mcp \
  --model YOUR_MODEL --effort high --repeats 2
```

Task input shape (rubrics may be stored alongside, but are never sent):

```json
{"tasks":[{"id":"lookup","question":"Where is Example defined, and what validates it? Cite source lines."}]}
```

The runner uses `codex exec --json`, read-only shell sandboxing, fresh ephemeral
sessions and isolated MCP configuration. It does not change the user's Codex
configuration or enable a general approval bypass. For unattended retrieval,
only the three benchmark MCP retrieval/discovery tools receive a per-tool
approval setting. Codex documents this configuration in its
[configuration reference](https://developers.openai.com/codex/config-reference/).
The MCP account/configuration must be limited to the intended snapshot; shell
sandboxing does not itself restrict a separate MCP server's filesystem access.

The script refuses to overwrite sample directories. `--task` and `--mode` allow
connection preflight; `--timeout` bounds each session. Invalid attempts remain
on disk and must be reported as setup failures, not quietly relabelled as valid
comparisons. A paid model's usage/account limits still apply.

## Scope and limitations

This measures a guided tool choice on code-navigation questions, not editing,
long-running development, every language or every project. The local MCP process
avoids network latency; repeat over the actual SSH route if remote overhead
matters. Prefix caching and model variability remain possible confounders even
with alternating order, so report per-task results and cache usage, not a single
unqualified percentage.

The initial project experiment will be linked here after its quality review.
