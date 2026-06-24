# agent-benchmark: measure what actually helps an agent

The idea in three points:

- An agent is more than its model. It is **model + the context you give it**:
  docs, skills, MCP servers, system prompts (agent profiles), plugins.
- All of that is cheap to write — and easy to over-claim. Does it really help,
  or does it just add tokens?
- So we test it like an experiment: **change one thing, keep everything else
  fixed, measure the delta — and check it is statistically significant.**

```mermaid
flowchart LR
    Q([same questions]) --> M1[model]
    Q --> M2[model + artifact]
    M1 -- "answers → judge" --> S1([score A])
    M2 -- "answers → judge" --> S2([score B])
    S1 --> D{{"delta = B − A<br/>p-value: real or noise?"}}
    S2 --> D
```

## What can be compared (arms)

| Arm | What it tests |
|---|---|
| `baseline` | the bare model (control) |
| `docs:` / `mcp:` | injected documentation (local files, URL, Context7, real MCP server) |
| `skill:` | a skill (`SKILL.md`) injected as context |
| `profile:` | an agent persona system prompt |
| `agent:` / `skill-agent:` | **agentic** use — the model gets a tool and *decides* whether to fetch docs / load the skill |

Two fine-print notes:

- Plugins (e.g. `plugin:caveman`) are not arms — they go in via `--plugins`
  and apply to every arm in the run.
- Set `--judge-model` / `--judge-provider` to a different model than the
  answerer; the CLI defaults both to the same model, and self-judging
  inflates scores.

## Example results

One skill, four models, same golden question set:

| Model | WITH skill | WITHOUT skill | Delta | p-value | Significant? |
|---|---|---|---|---|---|
| Haiku 4.5 | 66.3 | 56.8 | **+9.5** | 0.0024 | ✅ yes |
| Opus 4.7 | 78.5 | 73.6 | +4.9 | 0.0842 | ❌ |
| Sonnet 4.6 | 74.3 | 69.9 | +4.4 | 0.1797 | ❌ |
| Opus 4.8 | 80.8 | 78.1 | +2.7 | 0.1530 | ❌ |

What this table teaches:

- **Value depends on the model.** The same skill is worth +9.5 to a small
  model and +2.7 to a frontier one — stronger models already know more.
- **No p-value, no claim.** Three deltas are positive but not significant —
  at this sample size they may be judge noise.
- **The conclusion is targeted.** Ship this skill where it provably helps
  (smaller/cheaper models); gather more data for the rest.

*Where the stats come from:* the two-arm (with/without) reports compute the
paired t-test, Wilcoxon, and Cohen's d; the N-way `arms run` report shows
average scores and deltas vs baseline (use `scripts/compare_models.py` for
baseline-vs-one-treatment significance). The full `benchmark run` pipeline
also records a `question_set_hash` to prove question-set reuse across runs.

## How the evaluation flows

```mermaid
flowchart TD
    S1["<b>1 · Questions</b><br/>personas (synthetic users) → generated questions,<br/>or curated golden sets"]
    S2["<b>2 · Answers</b><br/>the same model answers every question once per arm;<br/>agentic arms also record whether the tool was used"]
    S3["<b>3 · Judge</b><br/>a separate LLM scores all answers (0–100) on 5 dimensions;<br/>optional judge panel + RAGAS cross-checks"]
    S4["<b>4 · Results</b><br/>deltas vs baseline · significance tests · gates · dashboards<br/>reported per (model × harness × plugins)"]
    SC(["<b>scorecard</b>: worth +X on model M (p = …) — ship it or cut it"])
    S1 --> S2 --> S3 --> S4 --> SC
```

Two more tracks back this up:

- **Static track** — LLM-free checks on the docs themselves: structure,
  freshness, readability, do the code examples run.
- **Executable task track** — [`terminal-bench-tasks/`](../terminal-bench-tasks/):
  the agent must edit code, compile, and pass tests in Docker. A judge can be
  fooled by prose; a pytest verifier cannot. The
  [coding harnesses guide](coding-harnesses.md) explains how to run Codex,
  Claude Code, or any Harbor agent against these tasks and compare pass rate
  against a baseline harness.

## Why this matters

Marketplaces rank agent artifacts by popularity, which buries niche expert
tooling (focus here: Intel performance libraries — oneTBB, oneDAL, oneMKL).
Here, every shipped skill, doc source, or profile carries the **scorecard
that earned it**, kept alive as models and docs change. See the
[umbrella README](../../README.md) for the bigger
author → build → **measure** → package → discover → serve cycle.

## Explore

- Run a comparison: [evaluating-treatments.md](evaluating-treatments.md) —
  `cli.py arms run` with any mix of arms.
- Full pipeline in one command: [quickstart.md](quickstart.md) — personas →
  questions → answers → judge → report, with cost estimates.
- Design rationale: [decisions/benchmark-methodology.md](decisions/benchmark-methodology.md)
  and [decisions/2026-05-29-evaluating-mcp-skills-personas.md](decisions/2026-05-29-evaluating-mcp-skills-personas.md).

---

# Documentation index

Start with the top-level [README](../README.md) for the project overview and
CLI surface. The files in this directory go deeper:

## Using agent-benchmark

- [quickstart.md](quickstart.md) — end-to-end LLM evaluation pipeline:
  personas → questions → answers → judge → report. Includes troubleshooting
  and a cost estimate.
- [benchmarking-and-comparison.md](benchmarking-and-comparison.md) — how to
  run static benchmarks, LLM context benchmarks, fair multi-model comparisons,
  treatment-arm comparisons, dashboards, baselines, and PR #60 comparison
  scripts.
- [adding-doc-source.md](adding-doc-source.md) — point the pipeline at local
  files, a single URL, a real MCP server, or a custom client.
- [evaluating-treatments.md](evaluating-treatments.md) — compare
  context-augmentation arms (docs, MCP, skills, agent persona prompts) with
  `cli.py arms run`.
- [coding-harnesses.md](coding-harnesses.md) — run executable coding tasks
  through Codex, Claude Code, or terminal-bench/Harbor harnesses and compare
  verifier pass rate against a baseline.

## Extending agent-benchmark

- [architecture.md](architecture.md) — module map and data flow across the
  static, LLM, and executable-task tracks.
- [contributing-metric.md](contributing-metric.md) — add a new static
  documentation metric (module + spec + tests + docs).
- [contributing-terminal-bench-task.md](contributing-terminal-bench-task.md)
  — add an executable oneTBB / oneAPI task with Docker, oracle, and pytest
  verifier.

## Reference

- [example-execution.md](example-execution.md) — how the `example_pass_rate`
  metric extracts and runs fenced code examples in isolation.
- [ingestion-docling.md](ingestion-docling.md) — ingesting non-Markdown
  documents (PDF, HTML, …) via Docling, installed with the optional `ocr` extra.
- [difficulty-rubric.md](difficulty-rubric.md) — the difficulty/level rubric
  used to grade performance-skill questions and tasks.

## Historical decisions

The `decisions/` directory keeps point-in-time design reviews and
investigations. They reflect the state of the project at their dated time
and may have been partially superseded — each file's header notes its
current status.

- [decisions/2026-02-12-review-devils-advocate.md](decisions/2026-02-12-review-devils-advocate.md)
- [decisions/2026-02-12-review-intel-product.md](decisions/2026-02-12-review-intel-product.md)
- [decisions/2026-02-14-context7-http-vs-mcp.md](decisions/2026-02-14-context7-http-vs-mcp.md)
- [decisions/2026-05-29-evaluating-mcp-skills-personas.md](decisions/2026-05-29-evaluating-mcp-skills-personas.md)
  — assessment + proposal for evaluating MCP docs, skills, and agent persona
  prompts as first-class treatment arms.
- [decisions/2026-06-10-evaluation-beyond-mcp-docs.md](decisions/2026-06-10-evaluation-beyond-mcp-docs.md)
  — **umbrella / index** for extending evaluation beyond MCP docs; states the
  shared motivation and sequences the ADRs below.
  - [decisions/2026-06-10-questions-and-tasks-coverage-contract.md](decisions/2026-06-10-questions-and-tasks-coverage-contract.md)
    — pair every project's question set (awareness) with an executable task set
    (work); surface the gap as a checked matrix. *(Phase A.)*
  - [decisions/2026-06-10-model-harness-dimension.md](decisions/2026-06-10-model-harness-dimension.md)
    — make base model × harness an explicit, swept, reported dimension; deltas
    only comparable within a `(model, harness)` cell. *(Phase B.)*
  - [decisions/2026-06-11-plugin-and-harness-aware-benchmarks.md](decisions/2026-06-11-plugin-and-harness-aware-benchmarks.md)
    — add plugins such as Caveman as explicit runtime behavior modifiers and
    report token/cost gains separately from quality or task-success loss.
    *(Phase C.)*
  - [decisions/2026-06-19-run-telemetry-metrics.md](decisions/2026-06-19-run-telemetry-metrics.md)
    — capture per-run tokens, cost, cache, and latency as a normalized
    `metrics{}` block on every result row; answers the plugin ADR's O5.
    *(Phase C.0 — prerequisite for Phase C.)*
  - [decisions/2026-06-10-artifacts-as-evaluation-subjects.md](decisions/2026-06-10-artifacts-as-evaluation-subjects.md)
    — promote skills/profiles/bundles from arms to first-class evaluation
    *subjects* emitting a per-subject scorecard. *(Phase D.)*
  - [decisions/2026-06-23-exploration-quality-fastcontext.md](decisions/2026-06-23-exploration-quality-fastcontext.md)
    — add exploration quality (citation localization F1, pre-edit cost,
    main-vs-subagent token accounting) as a measurable layer; FastContext skill
    arm + standalone ExploreBench track. *(Item #60.)*
- [decisions/benchmark-methodology.md](decisions/benchmark-methodology.md)
  — current operational methodology for model roles, question types,
  difficulty levels, answer generation, judging, trust checks, and executable
  agent tasks.
