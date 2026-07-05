# Evaluation beyond MCP docs — overview and decision index

**Status:** ACCEPTED (umbrella) — IN PROGRESS. This is the index for five related
decisions that together extend the benchmark beyond its doc-centric framing as
the project moves toward packaging a *summonable Intel expert* (umbrella #58).
Phases A, B, and C.0 have landed (PRs #81, #82, #84/#85); Phase C is mostly
landed (paired plugin-delta, explicit matrix cells, `arms matrix-run`, and both
in-process plugin kinds — `prompt_middleware` and `output_shaper` — shipped;
remaining are runner adapters for the tool/memory/harness-extension kinds) and
Phase D is in progress (PR #101/#102 stack). Each decision is recorded and reviewable on
its own; this file states the shared motivation, how the decisions fit together,
and the rollout order. Tracked as BACKLOG #59.

**Date:** 2026-06-10

**Supersedes nothing.** Extends
[2026-05-29-evaluating-mcp-skills-personas.md](2026-05-29-evaluating-mcp-skills-personas.md)
(the treatment-arm framework: `agent_benchmarks/treatments/`,
`eval/arm_runner.py`, `cli.py arms run`) and the executable
[terminal-bench track](../contributing-terminal-bench-task.md).

---

## 1. Shared motivation

The benchmark today answers a doc-centric question — *does retrieved
documentation improve a model's answer?* The treatment-arm framework generalized
the mechanism so skills, agent profiles, and MCP servers can each be toggled as
an **arm** layered on a fixed product question set, scored by an LLM-as-judge
delta; behavioral signal lives in a separate handful of terminal-bench tasks.

That substrate is right, but it is still organized around **documentation as the
thing under test**, on **one implicit model and harness**, with **awareness
measured everywhere and work measured almost nowhere**. Structural gaps
follow, and each is large enough — in design surface, in data-model impact, and
in the open questions it raises — to warrant its own decision record. (The
telemetry ADR was later carved out of the plugin-aware decision as Phase C.0, so
this index now spans five records rather than the original four.) A single
shared section would obscure the distinct trade-offs reviewers must weigh
independently, which is why this file is an index rather than one combined
proposal.

## 2. The five decisions

| ADR | Decision | Core question it answers |
|---|---|---|
| [Artifacts as evaluation subjects](2026-06-10-artifacts-as-evaluation-subjects.md) | Promote the **skill / profile / bundle** from an arm to the *subject* under test, measured across a portfolio and emitting a per-subject **scorecard**. | "Is *this artifact* worth shipping?" — the credential the packaging track signs. |
| [Base model × harness dimension](2026-06-10-model-harness-dimension.md) | Make the **answer model** and the **agent harness** explicit, swept, reported axes; deltas are only comparable within one `(model, harness)` cell. | "How big is the model/harness effect vs the doc/skill effect, especially for coding?" |
| [Questions-and-tasks coverage contract](2026-06-10-questions-and-tasks-coverage-contract.md) | Require every project to carry both a **question set (awareness)** and a **task set (work)**, with the gap surfaced as a checked matrix. | "Can the model *do the work*, not just *describe the API*?" |
| [Plugin and harness-aware benchmark dimensions](2026-06-11-plugin-and-harness-aware-benchmarks.md) | Add **plugins** as explicit runtime behavior modifiers and allow explicit matrix cells where each harness can declare its supported model/plugin combinations. | "What does a plugin like Caveman trade off: fewer tokens and shorter output for how much quality or task-success loss?" |
| [Run telemetry — tokens, cost, cache, latency](2026-06-19-run-telemetry-metrics.md) | Capture a normalized per-run `metrics{}` block (tokens, `litellm` cost, cache read/write, latency; TTFT behind a streaming flag) at the `llm.py` chokepoint. *(Phase C.0 — prerequisite for plugin-aware cells.)* | "What did this answer **cost** — tokens, dollars, cache state, latency — not just how good was it?" |

## 3. How they compose

The decisions are deliberately layered, not independent features bolted on:

```text
            ┌───────────────────────────────────────────────┐
            │  Subject  (ADR: artifacts-as-subjects)         │
            │  the skill / profile / bundle under test       │
            └───────────────┬───────────────────────────────┘
                            │ measured over
                            ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  Suite = products × { questions (awareness) , tasks (work) }  │
   │         (ADR: questions-and-tasks coverage contract)          │
   └───────────────┬──────────────────────────────────────────────┘
                   │ each cell run under
                   ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  Matrix = models × harnesses   (ADR: model × harness)         │
   │  single-shot · agent · terminal-bench:<agent>                 │
   └──────────────────────────────────────────────────────────────┘
                   │ optionally modified by
                   ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  Plugins = none · caveman · memory · tool middleware          │
   │  (ADR: plugin and harness-aware dimensions)                   │
   └───────────────┬──────────────────────────────────────────────┘
                   │ yields
                   ▼
        per-(subject, model, harness, plugin_set) scorecard:
        awareness delta  +  work pass-rate delta
```

A **subject** needs a **suite** to be measured against, and the suite's *work*
half is exactly what the **coverage contract** guarantees exists. Both the
awareness and work measurements are only interpretable inside a fixed `(model,
harness, plugin_set)` **cell** from the matrix and plugin decisions. So the
dependency order is: coverage gives subjects something real to stand on, the
matrix makes any number read meaningfully, plugins make runtime behavior
modifiers explicit, and subjects assemble those into the shippable credential.

## 4. Rollout order

1. **[Coverage contract](2026-06-10-questions-and-tasks-coverage-contract.md)**
   (Phase A) first — cheapest, no new eval machinery, and it gives the other two
   a real portfolio (and a *work* signal) to target. **DONE (PR #81).**
2. **[Model × harness](2026-06-10-model-harness-dimension.md)** (Phase B) next —
   makes every existing and future delta comparable and adds the `terminal-bench`
   harness adapter that turns task pass-rate into an arm outcome. **DONE (PR #82).**
3. **[Run telemetry](2026-06-19-run-telemetry-metrics.md)** (Phase C.0) before
   plugins — captures the per-run cost/token/cache/latency `metrics{}` block at
   the `llm.py` chokepoint that the plugin trade-off reports depend on.
   **DONE (PR #84/#85).**
4. **[Plugin-aware cells](2026-06-11-plugin-and-harness-aware-benchmarks.md)**
   (Phase C) next — extends the matrix from a simple Cartesian product to explicit
   cells with harness-specific model support and plugin sets (`none`, `caveman`,
   `truncate`, ...). **Mostly done** — paired plugin-delta, explicit matrix
   cells, `arms matrix-run`, and both in-process plugin kinds
   (`prompt_middleware`, `output_shaper`) have landed; remaining are runner
   adapters for `tool_middleware`/`memory_context`/`harness_extension` and an
   external `openclaw-agent` runtime.
5. **[Subjects](2026-06-10-artifacts-as-evaluation-subjects.md)** (Phase D) last —
   assembles the layers beneath it into the per-subject scorecard the packaging
   track (#58d/#58i) serializes and signs. **IN PROGRESS (PR #101/#102 stack).**

Each leaves the existing two-arm doc flow and `arms run` working, and each is
useful shipped alone. See each ADR for its detailed design, alternatives,
consequences, and open questions.
