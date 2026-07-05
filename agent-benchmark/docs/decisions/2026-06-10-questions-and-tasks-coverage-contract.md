# ADR: A questions-and-tasks coverage contract for every project

**Status:** ACCEPTED — IMPLEMENTED (Phase A, PR #81). One of five decisions under
the [evaluation-beyond-MCP-docs umbrella](2026-06-10-evaluation-beyond-mcp-docs.md)
(BACKLOG #59). Per-product `coverage_status` lives in `products.yaml`; the
product × {questions, tasks} matrix is generated into
`terminal-bench-tasks/COVERAGE.md` by `python -m agent_benchmarks.coverage`; the
drift check (`agent_benchmarks/coverage.py`, wired into `config_check`) fails a
`covered` product with no resolvable task/question. Touches `products.yaml`,
`terminal-bench-tasks/COVERAGE.md`, the dashboard, and the executable
[terminal-bench track](../contributing-terminal-bench-task.md). Two open
questions were resolved in the implementation: **O4** — the contract fields
(`questions`, `coverage_status`) live in the top-level `products.yaml`, not
`config/products.yaml`; and the ADR §5 negative ("a per-product `tasks` list is
a second place task identity lives") was avoided by **deriving** the work signal
from each `task.toml`'s `tags` rather than hand-listing tasks per product, so the
task directory stays the single source of truth.

**Date:** 2026-06-10

**Phase:** A in the umbrella rollout (land first -- cheapest, unblocks the later
matrix, plugin, and subject layers).

---

## 1. Context

The benchmark produces two qualitatively different signals:

- **Awareness** — can the model *talk about* the API correctly? Measured by the
  Q&A track (golden question sets + LLM-as-judge). Every product has, or can
  trivially have, a question set.
- **Work** — can the model *produce code that compiles, runs, and passes a
  verifier*? Measured by the terminal-bench track. Only a handful of oneAPI
  components have tasks (`onetbb-*`, `onemkl-dgemm/fft`, `onedpl-transform-reduce`,
  `ipp-dotprod`, `sklearnex-classification`).

These signals **diverge**. A model can describe `tbb::parallel_reduce` flawlessly
and still write a racy reduction; it can recite the `cblas_dgemm` signature and
still get leading dimensions wrong. The artifacts the project most wants to
certify — skills, setup guides — prove their value in *work*, not *talk*. Yet
today "evaluation" for most products silently means "awareness only," because the
work half simply doesn't exist for them and nothing makes that absence visible.

## 2. Decision

Define a per-project **coverage contract**: every project in scope declares
**both** a question set (awareness) and at least one executable task (work), each
task carrying a documented offline-verifiable validation strategy. Where the work
half is missing, that gap is **surfaced as a checked matrix**, not left implicit.
Enforcement starts **soft** (reported gap) and can tighten to **hard** (CI fails a
project that claims a task suite but ships none) later.

This decision adds *no new answering machinery* — it is a contract, a matrix, and
two dashboard columns. Its value is making the awareness/work split legible and
giving the [subjects](2026-06-10-artifacts-as-evaluation-subjects.md) and
[model × harness](2026-06-10-model-harness-dimension.md) decisions a real *work*
signal to measure against.

## 3. Detailed design

### 3.1 The contract, declared in config

Each registered product/library declares its evaluation surface:

```yaml
# config/products.yaml (or libraries.yaml) — illustrative
oneTBB:
  questions: data/questions/onetbb_golden.json     # awareness (required)
  tasks:                                            # work (required; ≥1 once available)
    - terminal-bench-tasks/onetbb-parallel-reduce
    - terminal-bench-tasks/onetbb-flow-graph
  coverage_status: covered        # covered | questions-only | planned
```

`coverage_status` is the honest self-report: `questions-only` is a *visible TODO*,
not a silent default. A product may be `planned` (neither yet) during onboarding.

The flat top-level product map above is **illustrative only** — it does not
imply the real schema. `config/products.yaml` and `libraries.yaml` have distinct
existing shapes and are drift-checked against each other (#57 P2); which file
actually owns the `questions` / `tasks` / `coverage_status` fields is deliberately
left to open question O4 below.

### 3.2 The coverage matrix

Extend `terminal-bench-tasks/COVERAGE.md` from a oneTBB API/concept matrix into a
**product × {questions, tasks}** table — the single canonical place a reader sees
who has what:

| Product | Questions (awareness) | Tasks (work) | Validation strategy | Status |
|---|---|---|---|---|
| oneTBB | ✅ golden (N) | ✅ 7 tasks | serial-reference signature | covered |
| oneMKL | ✅ golden (N) | ✅ dgemm, fft | analytic / round-trip | covered |
| IPP | ✅ golden (N) | ✅ dotprod | serial reference | covered |
| oneDNN | ✅ golden (N) | ⬜ planned | primitive vs serial | questions-only |
| … | … | … | … | … |

The validation-strategy column reuses the catalogue already proven in #54:
**serial-reference signature**, **analytic expected value**, **round-trip
invariant**, **drop-in comparison**. Adding a task means picking one and pointing
to the verifier.

### 3.3 Dashboard: two columns, two signals

The cross-library dashboard (`agent_benchmarks/dashboard/`) gains two columns per
product:

- **Awareness score** — the existing judge score over the question set.
- **Work pass-rate** — fraction of the product's tasks whose verifier passes
  (under the default `(model, harness)` cell once the
  [model × harness](2026-06-10-model-harness-dimension.md) decision lands; a bare
  oracle/agent pass-rate before that).

Showing them side by side is the point: a product that is green on awareness and
empty (or red) on work is exactly the case the contract exists to expose.

### 3.4 Scoring semantics

- **Awareness** and **work are never blended into one scalar.** They answer
  different questions and have different reliability; a weighted average would
  hide precisely the divergence we want visible.
- **Work pass-rate is the authoritative signal where it exists.** When a subject
  or arm has a task suite, treat task pass-rate as primary and the judge delta as
  a weak proxy (consistent with the under-measurement caveat in the
  [treatment-arm decision](2026-05-29-evaluating-mcp-skills-personas.md) §6).

### 3.5 Changes by module

| Module | Change |
|---|---|
| `config/products.yaml`, `libraries.yaml` | add `questions` / `tasks` / `coverage_status` per product. |
| `terminal-bench-tasks/COVERAGE.md` | promote to the product × {questions, tasks} matrix. |
| `agent_benchmarks/dashboard/` | render awareness and work columns; read tasks from config. |
| `config_check` (existing drift check) | extend to flag a `covered` product with no task path, or a task path that doesn't exist. |
| CI (later, opt-in) | hard mode: fail when `coverage_status: covered` but no resolvable task. |

## 4. Alternatives considered

1. **Keep awareness-only for most products; add tasks ad hoc.** Rejected: this
   is the status quo, and its failure mode is exactly the invisible gap — nobody
   notices that "evaluation" meant "talk only" until an artifact ships untested
   on work.
2. **Require a task for all 22 registered libraries on day one.** Rejected as
   impractical and not the point: the contract is about *explicitness and tracked
   gaps*, not a flag-day backfill. `questions-only` is a legitimate, visible
   state.
3. **Blend awareness + work into a single coverage score.** Rejected: collapses
   the divergence the whole decision is meant to surface.
4. **Track coverage only in prose/BACKLOG, not a checked matrix.** Rejected:
   prose drifts; a config-backed matrix with a drift check stays honest.

## 5. Consequences

- **Positive:** "text-only" products become a visible, tracked TODO instead of a
  silent default; the dashboard tells the truth about awareness vs work.
- **Positive:** gives subjects and the model × harness matrix a real behavioral
  signal to measure artifacts against; gives skills/setup-guides a bar to clear.
- **Positive:** cheap — no new eval machinery, reuses the existing task track,
  validation-strategy catalogue, drift check, and dashboard.
- **Negative:** authoring tasks for under-covered products is real work
  (Docker + oracle + verifier per task); the contract makes the cost visible but
  does not pay it. Hence soft enforcement first.
- **Negative:** a per-product `tasks` list is a second place task identity lives
  (alongside the task directories); the drift check must keep them in sync.

## 6. Open questions

- **O1 — Soft vs hard enforcement timeline.** Start soft (reported gap); when, if
  ever, does `coverage_status: covered` with no resolvable task become a CI
  failure?
- **O2 — Coverage target.** Is the goal "every *in-scope* product" (a small
  curated set) or "every *registered* library" (all 22)? (Leaning: in-scope set
  first, registered libraries as aspiration.)
- **O3 — Minimum task bar.** One task per product, or coverage of the product's
  *core* APIs (the existing oneTBB COVERAGE matrix sets a high bar)? (Leaning:
  one solid task to clear `questions-only`, core-API coverage as a stretch.)
- **O4 — Where the contract lives.** `config/products.yaml` vs `libraries.yaml`
  (currently drift-checked against each other, #57 P2). Pick one home for the
  `tasks`/`coverage_status` fields to avoid a third sync surface.
