# ADR: Base model × harness as an evaluation dimension

**Status:** ACCEPTED — IMPLEMENTED (Phase B, PR #82). One of five decisions under
the [evaluation-beyond-MCP-docs umbrella](2026-06-10-evaluation-beyond-mcp-docs.md)
(BACKLOG #59). The answer model and harness are now explicit reported axes: a
`matrix:` config block, a `(model, harness)` `Cell` key threaded through
`eval/arm_runner.py`, report/dashboard columns, and a `terminal-bench` harness
adapter that turns task pass-rate into an arm outcome. Cost-gated, single-cell
default. Builds on `agent_benchmarks/llm.py`, `eval/arm_runner.py`,
`eval/agent_runner.py`, and the terminal-bench track.

**Date:** 2026-06-10

**Phase:** B in the umbrella rollout (land after the coverage contract, before
plugin-aware cells and subjects).

**Extension:** [2026-06-11-plugin-and-harness-aware-benchmarks.md](2026-06-11-plugin-and-harness-aware-benchmarks.md)
adds explicit matrix cells for harness-specific model/plugin support and plugin
sets such as a Caveman-style output reducer.

---

## 1. Context

Every comparison the benchmark makes — `with_docs` vs `without_docs`, or any
arm vs baseline — is implicitly conditioned on two things it never names as
variables:

1. **The base model** that produces the answer (one `--model`, run-wide).
2. **The harness** — the loop that drives the model: a single completion today
   for Q&A, the in-process tool-calling loop in `eval/agent_runner.py` for
   agentic arms, and whatever coding agent Harbor is invoked with for tasks
   (chosen *outside* the benchmark, e.g. `harbor run -a terminus -m …`).

For **coding work this is the dominant effect.** A skill that adds +0.3 judge
points under a weak model and a thin harness can be invisible under a strong
model with a capable agentic harness — and vice-versa. Reporting an artifact's
delta without naming the model and harness it was measured under is reporting a
number whose denominator is hidden. We currently sweep neither axis deliberately
and stamp neither on the result rows, so:

- deltas from different runs are silently incomparable, and
- we cannot answer the question that motivates the whole effort: *how large is
  the model/harness effect relative to the doc/skill effect?*

## 2. Decision

Make **model** and **harness** explicit, first-class, *reported* dimensions that
the runner sweeps and the report holds fixed. Two rules:

1. **Stamp every result row** with its `(model, harness)`.
2. **Refuse to delta across cells:** an arm's delta is only computed *within* one
   `(model, harness)` cell. Cross-cell comparison is variance *of* the axis,
   never a treatment delta.

The set of cells is a `matrix:` block in config; the default is a single cell so
nothing gets more expensive until a user opts in.

## 3. Detailed design

### 3.1 Harness taxonomy

A **harness** is named and versioned. Three to start:

| Harness id | What it is | Where it lives | Outcome |
|---|---|---|---|
| `single-shot` | one completion; injected context prepended | `eval/answerer.py` | judge score over the answer string |
| `agent` | bounded in-process tool-calling loop (read-only doc/skill tools) | `eval/agent_runner.py` | judge score + `tool_use_rate` |
| `terminal-bench:<agent>` | Harbor drives a real coding agent against a task in Docker | new adapter → `terminal-bench-tasks/` | task **pass-rate** |

The harness is a property of a **run**, not a treatment — the same `skill:` arm
can be exercised under any harness. `terminal-bench:<agent>` is the new piece: a
thin adapter that invokes Harbor (`harbor run -p <task> -a <agent> -m <model>`),
parses `/logs/verifier/reward.txt`, and returns pass-rate so a *task outcome*
becomes a first-class arm outcome alongside judge scores.

> **Naming:** bare **`terminal-bench`** refers to the harness *family* (the
> adapter); **`terminal-bench:<agent>`** is a concrete instance pinned to one
> Harbor agent (e.g. `terminal-bench:terminus`). Other ADRs and BACKLOG #59 use
> the bare form when the specific agent is immaterial.

### 3.2 Model axis

`llm.py` already threads a model through; most result rows already carry the
answer model. The change is to (a) lift `--model` to accept a list
(`matrix.models`), (b) make the answer model a *reported dimension* rather than
a run-wide constant assumed equal everywhere, and (c) key results by it. Judge
model stays pinned and separate (a judge swap is a different experiment; never
covary it with the answer model).

### 3.3 The result cube

Reports move from a 1-D arm table to a small cube: **rows = arms/subjects**,
**cells = `(model, harness)`**. Schematically:

```text
                 model = A                     model = B
            ┌───────────┬───────────┐    ┌───────────┬───────────┐
            │single-shot│  agent    │ …  │single-shot│  agent    │
 ───────────┼───────────┼───────────┤    ├───────────┼───────────┤
 baseline   │   3.6     │   3.6     │    │   4.0     │   4.0     │
 skill:foo  │   +0.4    │   +0.3    │    │   +0.1    │   +0.0    │   ← effect shrinks
 ───────────┴───────────┴───────────┘    └───────────┴───────────┘   on the stronger model
```

Reading *down* a column is the treatment effect (what we measured before).
Reading *across* columns/cubes is the **model/harness effect** — now legible for
the first time. The dashboard gains the same keying.

### 3.4 Config surface

```yaml
# in config/products.yaml or a subject descriptor
matrix:
  models: ["<model-a>", "<model-b>"]      # default: [<the single configured model>]
  harnesses: [single-shot, agent]         # default: [single-shot]
  # terminal-bench harness is opt-in and only meaningful where the suite has tasks:
  # harnesses: [single-shot, agent, "terminal-bench:terminus"]
```

`matrix` omitted ⇒ exactly one cell ⇒ today's cost and behavior.

The follow-up plugin ADR keeps this shorthand but also adds an explicit
`matrix.cells` form for real harnesses that support only some models or require
specific runtime plugins. In that form, each cell records its `model`,
`provider`, `harness`, and `plugin_set`.

### 3.5 Changes by module

| Module | Change |
|---|---|
| `eval/arm_runner.py` | iterate over `matrix` cells; thread `(model, harness)` into every emitted row. |
| `eval/answerer.py` / `eval/agent_runner.py` | register under harness ids `single-shot` / `agent`; no behavioral change. |
| `eval/harness/` (new) | `terminal-bench.py` adapter: invoke Harbor, parse reward, return pass-rate. |
| `report/`, `dashboard/` | key tables/JSON by `(model, harness)`; render the cube; never delta across cells. |
| `agent_benchmarks/cli` | `--models` (list) and `--harnesses` flags; `--model` stays as the single-cell shorthand. |
| `artifacts.py` / `runner/manifest.py` | record `models`, `harnesses`, harness versions/config in the run manifest. |

## 4. Methodology — variance decomposition

The payoff is being able to attribute variance. With the cube we can report,
for a fixed suite:

- **Treatment effect:** mean delta of an arm vs baseline *within* each cell.
- **Model effect:** spread of baseline (and of a fixed arm) *across* models.
- **Harness effect:** spread *across* harnesses for a fixed model.

The headline finding the project wants — *"for coding tasks the
model/harness effect dwarfs the doc/skill effect"* (or not) — is then a direct
read, with the confounders held fixed by construction. This is why the
**no-cross-cell-delta rule** (§2.2) is load-bearing, not pedantry.

## 5. Alternatives considered

1. **Leave model/harness out of band (status quo): pick one config, document it
   in prose.** Rejected: makes every artifact delta uninterpretable for coding
   and makes runs silently incomparable — the exact problem the project hit.
2. **Sweep model only, not harness.** Rejected: for coding the harness (agentic
   loop quality, retries, execution) is often the larger lever; omitting it
   would mis-attribute harness effects to the model or the artifact.
3. **Full factorial by default.** Rejected on cost: the matrix is
   multiplicative and task cells are the expensive ones. Default to one cell;
   make sweeps and the terminal-bench harness opt-in and CI-labelled.
4. **Treat harness as just another treatment arm.** Rejected: a harness is *how*
   an answer is produced, not *what context* it is given; conflating them breaks
   the comparability rule (you could no longer hold "everything but the
   treatment" fixed).

## 6. Consequences

- **Positive:** artifact deltas become interpretable; cross-run comparisons
  become valid by construction; the model-vs-harness-vs-artifact question is
  answerable.
- **Positive:** task pass-rate enters the same report as judge scores via the
  `terminal-bench` harness adapter, unifying awareness and work signals.
- **Negative / cost:** combinatorial blowup if swept carelessly; mitigated by a
  single-cell default and opt-in gating.
- **Negative:** "harness effect" can be a mis-configuration artifact — comparing
  harnesses is partly comparing *our* integrations. Mitigated by recording each
  harness's version/config in the manifest and documenting it (O2).

## 7. Open questions

- **O1 — Harness invocation boundary.** `terminal-bench:<agent>` in-process via
  a Harbor adapter, or run out-of-band and import results? (Leaning: adapter, to
  keep one report and one manifest.)
- **O2 — Harness fairness.** What minimum config must be pinned per harness
  (agent version, max iterations, temperature, retries) for a "harness effect"
  to be a real signal rather than a tuning artifact?
- **O3 — Default cell.** Which single `(model, harness)` is the committed
  default so CI cost stays bounded while the variance question stays answerable
  on demand?
- **O4 — Statistical treatment.** Agentic/task cells are nondeterministic;
  how many trials per cell, and do we report bootstrap CIs (reusing the
  `eval grounding` bootstrap machinery) on the deltas by default?
