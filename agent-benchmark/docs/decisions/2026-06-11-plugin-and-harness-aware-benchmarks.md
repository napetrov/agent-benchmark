# ADR: Plugin and harness-aware benchmark dimensions

**Status:** ACCEPTED — MOSTLY IMPLEMENTED (Phase C). Extends the
[evaluation-beyond-MCP-docs umbrella](2026-06-10-evaluation-beyond-mcp-docs.md)
(BACKLOG #59), especially the
[model x harness dimension](2026-06-10-model-harness-dimension.md). Landed
slices: paired plugin/no-plugin artifact comparison via `arms plugin-delta` and
`plugin_delta.v1` reports (`eval/plugin_delta.py`,
`report/plugin_delta_report.py`); explicit `matrix.cells` descriptors for
`arms run` with harness/plugin compatibility validation before the run; and
`arms matrix-run` multi-cell orchestration writing `matrix_rollup.v1` reports
(`eval/matrix_rollup.py`, `report/matrix_rollup_report.py`) with automatic
paired `plugin_delta.v1` artifacts. **Remaining:** real runner adapters for
non-prompt plugins (memory, tool middleware) — the prompt-plugin path (Caveman)
is wired end-to-end. Builds on the treatment-arm framework
(`agent_benchmarks/treatments/`, `eval/arm_runner.py`, `eval/agent_runner.py`,
`python cli.py arms run`) and the software-packaging track's `AgentConfig`
package shape.

**Date:** 2026-06-11

**Phase:** C in the umbrella rollout. Land after the model x harness matrix
exists, or as an explicit extension while implementing it.

**Prerequisite:** the `metrics{}` block in §3.3, the Caveman token/length
trade-off report in §3.4, and open question O5 are carved out and resolved in
[2026-06-19-run-telemetry-metrics.md](2026-06-19-run-telemetry-metrics.md)
(Phase C.0), which lands the telemetry record (tokens, cost, cache, latency)
independently so this phase consumes it ready-made.

---

## 1. Context

The benchmark has already moved beyond a binary `with_docs` / `without_docs`
comparison. It can compare N treatment arms for docs, MCP sources, skills,
agent profiles, and read-only agentic tool use. A separate ADR proposes making
the answer **model** and execution **harness** explicit matrix dimensions.

That still misses a class of runtime behavior modifiers: **plugins**. Plugins
can change what the model sees, how it is instructed, which tools are exposed,
what tool results look like, or how the final answer is post-processed. The
motivating example is a `Caveman`-style plugin whose purpose is to reduce model
output. This kind of plugin can improve one metric (brevity, token cost,
latency) while degrading another (completeness, citation quality, task success).
If the benchmark does not model it explicitly, its effect is either invisible
or wrongly attributed to the model, docs, skill, or harness.

The current repository has the pieces that make this feasible:

- `Treatment` / `AgentConfig` already represents system prompts, injected
  context, tools, and metadata.
- `ArmRunner` already records per-arm answers, token usage, tool-call counts,
  and judge scores.
- `arms_report.py` already compares arms against a baseline.
- The model x harness ADR already requires every result row to be stamped with
  `(model, harness)` and forbids deltas across cells.

What is missing is a first-class place for plugins and harness-specific model
choices in the experiment descriptor, artifact schema, and report.

## 2. Decision

Add **plugins** as a first-class benchmark dimension, but do not treat them as a
third kind of base model. A plugin is a runtime behavior modifier applied inside
one `(model, harness)` cell.

The comparison key becomes:

```text
subject x product/suite x model x harness x plugin_set x treatment_arm
```

Rules:

1. Stamp every result row with `model`, `harness`, `plugin_set`, and the
   concrete plugin versions/config digests.
2. Compute treatment deltas only inside one `(model, harness, plugin_set)` cell.
3. Compute plugin deltas only by holding `model`, `harness`, suite, and
   treatment fixed.
4. Allow each harness to declare the models it can run. The matrix is a list of
   cells, not just a Cartesian product, because some harnesses are tied to a
   provider, agent runtime, or model family.
5. Track plugin side effects explicitly: output length, token usage, latency,
   tool-use rate, judge score, and task pass-rate where applicable.

For a Caveman-style plugin, the benchmark must answer two separate questions:

- **Does it reduce output/cost/latency?**
- **What quality or task-success tax does that reduction impose?**

It is not enough to report only average judge score.

## 3. Detailed design

### 3.1 Plugin taxonomy

Plugins should declare the layer they modify. Initial taxonomy:

| Plugin kind | Examples | Primary risks | Metrics |
| --- | --- | --- | --- |
| `prompt_middleware` | add/trim system or developer instructions | hidden prompt drift | judge score, refusal/error rate |
| `output_shaper` | Caveman-style brevity/format reducer | under-answering, missing citations | completion tokens, chars, completeness |
| `tool_middleware` | hide/filter/augment tool calls/results | wrong tool evidence, suppressed diagnostics | tool-use rate, retrieval relevance |
| `memory_context` | inject remembered/project context | leakage, stale context | grounding, source coverage |
| `harness_extension` | runtime-specific agent behavior | incomparable harness semantics | task pass-rate, retries, latency |

This taxonomy is metadata first. Implementation can start with a generic
`plugin:<ref>` arm/cell modifier and specialize only when reporting needs a
plugin-kind-specific metric.

### 3.2 Matrix cells, not pure Cartesian products

The existing model x harness ADR sketches:

```yaml
matrix:
  models: ["<model-a>", "<model-b>"]
  harnesses: [single-shot, agent]
```

That is good for simple sweeps, but plugins and real harnesses need richer
cells. Some harnesses only support some models; some plugins only run in an
OpenClaw-style runtime, not in a bare `single-shot` LiteLLM call. Add an
explicit cell form:

```yaml
matrix:
  cells:
    - id: gpt52_single_shot
      model: gpt-5.2
      provider: openai
      harness: single-shot
      plugins: []

    - id: gpt52_openclaw_none
      model: gpt-5.2
      provider: openai
      harness: openclaw-agent
      plugins: []

    - id: gpt52_openclaw_caveman
      model: gpt-5.2
      provider: openai
      harness: openclaw-agent
      plugins:
        - id: caveman
          ref: plugin:caveman
          kind: output_shaper
          config:
            target_style: terse

    - id: sonnet_openclaw_caveman
      model: claude-sonnet-4-6
      provider: anthropic
      harness: openclaw-agent
      plugins:
        - id: caveman
          ref: plugin:caveman
          kind: output_shaper
          config:
            target_style: terse
```

The old `models:` + `harnesses:` shorthand remains valid and expands to cells
with `plugins: []`.

Every plugin-effect report needs paired cells. For example,
`gpt52_openclaw_caveman` can be compared to `gpt52_openclaw_none`, not to
`gpt52_single_shot`, because the latter changes the harness at the same time as
the plugin set.

### 3.3 Plugin sets

Use both a human-readable plugin-set label and a canonical plugin-set id in
result rows. The id is a digest over the ordered plugin refs, resolved
versions/code identities, kinds, and normalized config. Reports aggregate by the
canonical id and display the label for readability.

```jsonc
{
  "model": "gpt-5.2",
  "harness": "openclaw-agent",
  "plugin_set": "caveman-terse",
  "plugin_set_id": "sha256:...",
  "plugins": [
    {"id": "caveman", "version": "0.1.0", "kind": "output_shaper", "config_hash": "sha256:..."}
  ],
  "arm": "skill:onetbb-quickstart",
  "metrics": {
    "judge_aggregate": 82.0,
    "billed_prompt_tokens": 1200,
    "billed_completion_tokens": 260,
    "raw_model_completion_tokens": 260,
    "raw_model_answer_chars": 1100,
    "final_answer_tokens": 180,
    "final_answer_chars": 740,
    "model_elapsed_sec": 3.8,
    "plugin_elapsed_sec": 0.4,
    "elapsed_sec": 4.2
  }
}
```

An empty plugin set is still a named cell (`plugin_set: none`) with a canonical
empty-set id, so baseline comparisons are explicit. For output shapers, storing
both raw model output metrics and final answer metrics is required; otherwise a
plugin can appear to reduce billed tokens when it only shortened the text after
the model had already produced it.

### 3.4 How plugin effects are computed

Plugin effect is not the same as treatment effect:

```text
treatment_delta = score(skill, model, harness, plugin_set)
                - score(baseline, model, harness, plugin_set)

plugin_delta    = score(arm, model, harness, caveman)
                - score(arm, model, harness, none)
```

Plugin deltas are paired by question/task, arm, model, harness, judge model,
generation parameters, retry budget, and cache policy. Runs should be repeated
when the harness is stochastic, and cell order should be interleaved or
randomized so service latency, warm caches, or transient provider behavior do
not masquerade as a plugin effect. Reports should show confidence intervals or
at least run counts whenever repeated trials are available.

For Caveman-style output reduction, reports should show:

- `billed_completion_tokens_delta_pct`
- `final_answer_chars_delta_pct`
- `raw_to_final_chars_delta_pct`
- `judge_aggregate_delta`
- `completeness_delta` when the judge dimensions include completeness
- `task_pass_rate_delta` for terminal-bench cells
- `latency_delta_pct` when timing is reliable enough

A plugin is useful only when the cost/length improvement is worth the quality
or task-success trade-off under the target harness.

### 3.5 Harness adapters

Add a harness abstraction before adding many plugins:

```text
class Harness(Protocol):
    id: str
    def run(self, *, model, provider, agent_config, plugins, task_or_question) -> RunCellResult: ...
```

Initial adapters:

- `single-shot`: current `llm_call_with_usage` path; supports only plugins that
  can be represented as prompt/output middleware in-process.
- `agent`: current `eval/agent_runner.py`; supports tool and prompt plugins
  only if they can be represented as local pre/post hooks.
- `openclaw-agent`: external/runtime adapter that starts or calls an OpenClaw
  session with explicit plugins enabled; required for Caveman if it is an
  OpenClaw runtime plugin.
- `terminal-bench:<agent>`: task harness from the model x harness ADR; plugins
  only apply when that agent runtime can load them.

The descriptor must validate plugin compatibility with harnesses before a run.
Unsupported combinations should be skipped with a reported reason, not silently
coerced into a different behavior.

## 4. Implementation tasks

1. **Schema and descriptor**
   - Extend matrix descriptors with explicit `cells`.
   - Add `plugins` / `plugin_set` fields to the run manifest.
   - Add plugin compatibility metadata: supported harnesses, kind, version,
     config hash.

2. **Harness abstraction**
   - Introduce `agent_benchmarks/eval/harness/` with `single-shot` and `agent`
     adapters wrapping existing code.
   - Add an `openclaw-agent` adapter as the integration point for real plugins
     such as Caveman.
   - Keep `terminal-bench:<agent>` as the behavioral/task adapter.

3. **Plugin representation**
   - Add `agent_benchmarks/plugins/` loader for plugin descriptors.
   - Support a generic `plugin:<ref>` descriptor before implementing
     plugin-specific code.
   - Record plugin provenance and config digests in outputs.

4. **Runner and artifact changes**
   - Move `ArmRunner` from one run-wide model/harness to per-cell execution.
   - Store answers/evaluations under cell ids.
   - Update `arms.v1` or introduce `scorecard.v1` so old artifacts still load.

5. **Reporting**
   - Render both treatment deltas and plugin deltas.
   - Add a Caveman-oriented section: token/character reduction vs score and
     pass-rate tax.
   - Separate billed/raw model metrics from final post-plugin metrics.
   - Add guardrails that warn when a report compares cells with different
     harnesses, models, judge models, or plugin sets as if they were the same.

6. **Validation and tests**
   - Unit-test matrix expansion, duplicate cell ids, unsupported
     plugin/harness combinations, and no-cross-cell-delta behavior.
   - Test that plugin deltas require paired no-plugin cells with the same model
     and harness.
   - Test that plugin-set ids change when plugin order, version, code identity,
     or normalized config changes.
   - Add a fake output-shaper plugin in tests to prove token/length metrics and
     quality trade-off reporting work without depending on a real Caveman
     runtime.

## 5. Consequences

- **Positive:** plugin effects become measurable instead of being hidden in
  model or harness noise.
- **Positive:** harness-specific model support is represented honestly; the
  benchmark can compare real runtime configurations instead of pretending every
  model runs everywhere.
- **Positive:** output-reduction plugins can be judged by the trade-off they
  claim to optimize: fewer tokens and shorter answers at acceptable quality
  loss.
- **Negative:** matrix size grows quickly. Mitigation: default remains one cell
  with `plugins: []`; plugin sweeps are opt-in and should run on golden sets
  first.
- **Negative:** external harness adapters can make results less reproducible.
  Mitigation: record plugin/harness versions, config digests, retry budgets,
  temperatures, and runtime ids in the manifest.

## 6. Open questions

- **O1 -- Caveman integration boundary.** Is Caveman callable as prompt/output
  middleware from Python, or only through an OpenClaw runtime session? If the
  latter, `openclaw-agent` is required before a faithful benchmark.
- **O2 -- Plugin subject vs plugin modifier.** A plugin can be the subject
  under test (is Caveman worth enabling?) or part of the harness environment
  while a skill is the subject. The descriptor should support both, but reports
  must label which question is being answered.
- **O3 -- Brevity judge calibration.** A normal correctness judge may punish
  terse answers inconsistently. Do Caveman runs need a judge rubric with
  explicit completeness-vs-brevity dimensions?
- **O4 -- Runtime trust.** Plugins can execute privileged code in some
  harnesses. Should plugin sweeps be limited to sandboxed runners unless the
  plugin is bundled/trusted?
- **O5 -- Default plugin metrics.** Which cost metrics are required in every
  row: prompt tokens, completion tokens, total tokens, wall time, tool calls,
  retries? **Resolved** in
  [2026-06-19-run-telemetry-metrics.md](2026-06-19-run-telemetry-metrics.md) §2:
  required are `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`
  (nullable), `latency_sec`, and (agentic) `tool_call_count`; cache tokens,
  `reasoning_tokens`, `ttft_sec`, and raw-vs-final sizes are recorded when
  available but not required.
