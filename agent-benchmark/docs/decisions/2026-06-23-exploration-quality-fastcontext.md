# ADR: Exploration quality as a measurable layer (FastContext-informed)

**Status:** ACCEPTED — all 7 slices implemented (see §5). New backlog item
**#60**. Extends the
[evaluation-beyond-MCP-docs umbrella](2026-06-10-evaluation-beyond-mcp-docs.md)
(#59) and consumes the telemetry record defined in the
[per-run telemetry ADR](2026-06-19-run-telemetry-metrics.md) (`UsageRecord`,
`metrics{}`). Builds on `agent_benchmarks/harnesses/` (`OperationRecord`,
`HarnessResult`, `task_runs.v1`), `agent_benchmarks/treatments/factory.py`
(arm specs), and `agent_benchmarks/eval/agent_runner.py`.

**Date:** 2026-06-23

**Phase:** Slots beside Phase C (plugin/harness-aware cells). The first two
slices (citation parser, `exploration_metrics`) are additive to existing
artifacts and can land independently; the standalone ExploreBench track is a
new artifact type and lands last.

---

## 1. Context

[FastContext](https://github.com/microsoft/fastcontext) (Microsoft) trains a
small read-only repository explorer for coding agents. A subagent uses
`Read`/`Glob`/`Grep`, explores in parallel, and returns a compact
`<final_answer>` block of `path:start-end` citations. The paper measures two
things this repo currently does not:

1. **Exploration cost** — how much of a trajectory is spent reading/searching
   *before* the agent does useful work (their trajectories: ~56% of tool-use
   turns and ~46% of main-agent tokens go to read/search; ~6 sequential
   exploration turns and ~15 exploration tool calls before the first edit).
2. **Localization quality, scored standalone** — parse the explorer's
   citations, compare against patch-derived edited locations at
   file/module/function granularity, report precision/recall/F1 — *without*
   requiring the task to be solved.

An external analysis proposed mapping all of this into `agent-benchmark`. This
ADR records which parts are a genuine fit, which are redundant, and the
concrete shape of the parts worth building.

### What the repo already has (so we don't rebuild it)

- **Controlled treatment arms.** `treatments/factory.py` parses
  `baseline`, `docs[:<src>]`, `mcp:<ref>`, `profile:<path>`, `skill:<path>`,
  `agent[:<src>]`, `skill-agent:<path>`. Fair comparison conditions on
  `(model, harness, plugin_set)` and forbids deltas across cells
  (`docs/benchmarking-and-comparison.md`).
- **Generic operation telemetry.** `harnesses/operations.py` already ingests
  `subagent`/`tool`/`loop` events from `operations.jsonl` or
  `AGENT_BENCHMARK_OP {…}` stdout markers into `OperationRecord(type, name,
  status, elapsed_sec, metadata)`. `HarnessResult` carries arbitrary
  `metrics{}` plus a list of `operations`, persisted as `task_runs.v1`.
- **Per-run cost/latency telemetry.** The 2026-06-19 ADR defines `UsageRecord`
  (tokens, cache, `cost_usd`, latency) summing across agentic turns; the
  `metrics{}` block lands on every result row.
- **Agentic loop signals.** `eval/agent_runner.py` already records
  `iterations`, `tool_call_count`, `stopped_reason`, and per-tool
  `tool_elapsed_sec`.
- **Skill fixtures + executable tasks.** `data/skills/*` (e.g.
  `onetbb-quickstart`, `intel-performance-patterns`) and
  `terminal-bench-tasks/intel-perf-*` (Docker + oracle + pytest verifier).

The repo is already built on the right abstraction. FastContext is **not**
another static doc metric and **not** a new model we need to train. Its value
is a missing *analytics layer*: did the agent find the right context
efficiently, before it answered/edited/ran?

## 2. Decision

Add **exploration quality** as a first-class, measurable dimension via three
additive slices and one new track. Reuse existing telemetry plumbing rather
than inventing a parallel mechanism. Specifically:

1. **A citation parser + localization scorer** (`metrics/exploration.py`):
   parse `<final_answer>` `path:start-end` blocks; compute validity,
   compactness, and (where a reference exists) file/line precision/recall/F1.
2. **An `exploration_metrics` block** on `task_runs.v1` result rows, derived
   from the `OperationRecord` stream already collected — pre-edit turns,
   read/search share, repeated-read ratio, broad-search count,
   wasted-search-after-subagent — plus split **main vs subagent token
   accounting**.
3. **A FastContext skill fixture + arm**: `data/skills/fastcontext/SKILL.md`
   evaluated as `skill-agent:` and inside task-harness wrappers, so the
   exploration treatment is comparable to `docs`/`skill`/`mcp` under the
   one-axis-at-a-time rule.
4. **A standalone "ExploreBench" track**: exploration-only tasks where the
   agent outputs citations and is scored against curated/oracle reference
   locations — answering *"can the agent locate the right evidence?"*
   separately from *"can it use it?"*.

Non-goals: training an explorer model; replacing Q&A or terminal-bench tracks;
adopting patch-localization as the sole quality signal (see §6 caveats).

## 3. Detailed design

### 3.1 Citation parser + localization scorer — `metrics/exploration.py`

A new pure module (no I/O, fully unit-testable), modeled on FastContext's
`benchmark/evaluation/utils.py` but adapted to our repo conventions.

```python
@dataclass(frozen=True)
class Citation:
    path: str
    start: int | None      # None == whole-file citation
    end: int | None

@dataclass(frozen=True)
class CitationSet:
    citations: tuple[Citation, ...]
    malformed: tuple[str, ...]       # lines that did not parse
    overlapping: int                 # count of overlapping ranges within a file

def parse_final_answer(text: str) -> CitationSet:
    """Extract the last <final_answer>…</final_answer> block and parse
    `path:start-end` / `path:line` / bare `path` lines. Robust to missing
    tags (fall back to scanning path:line patterns)."""

@dataclass(frozen=True)
class LocalizationScore:
    citation_validity_rate: float    # parsed / (parsed + malformed)
    file_precision: float; file_recall: float; file_f1: float
    line_precision: float; line_recall: float; line_f1: float
    citation_compactness: float      # cited lines / reference lines (lower better)

def score_localization(pred: CitationSet, reference: ReferenceLocations,
                       repo_root: Path | None = None) -> LocalizationScore:
    """Normalize paths, map cited ranges → file/line targets, compute
    instance-wise P/R/F1. `repo_root` (optional) enables a
    `citation_exists` check (cited file/line is in range of the real file)."""
```

`ReferenceLocations` is derived two ways:

- **Oracle-derived** (terminal-bench / SWE-style): files+ranges touched by the
  oracle solution diff, computed *after* inference on the pre-change checkout
  (reference hidden during inference — same protocol as the paper).
- **Curated** (docs/examples): hand-authored `path: [start, end]` entries (see
  ExploreBench task YAML in §3.4).

Granularity: report **file-level** and **line-level** F1. Function/module
granularity is deferred (needs a language-aware mapper) and tracked as O3.

### 3.2 `exploration_metrics` on `task_runs.v1`

Derive an `exploration_metrics` object from the `OperationRecord` stream
already attached to each `HarnessResult` and place it under
`results[].metrics.exploration_metrics`. This is **additive** — `task_runs.v1`
already allows `additionalProperties: true` on `metrics`, so existing readers
keep working; we bump to `task_runs.v2` only to *document* the block, not to
gate it.

A new `harnesses/exploration.py` consumes `list[OperationRecord]` + the
`UsageRecord` split and emits:

```jsonc
"exploration_metrics": {
  // trajectory shape (from operation ordering)
  "pre_edit_turns": 5,
  "pre_edit_tool_calls": 14,
  "time_to_first_edit_sec": 92.4,
  "read_search_token_share": 0.46,       // read+search tokens / main tokens
  "repeated_read_ratio": 0.18,           // re-reads of an already-read path
  "broad_search_count": 3,               // grep -R / find / full-doc dumps
  // delegation health (subagent vs main)
  "subagent_invocation_count": 2,
  "broad_search_after_subagent_count": 1,
  "main_reads_overlap_with_citations": 0.7,
  // citation quality (from §3.1, when a reference exists)
  "citation_validity_rate": 1.0,
  "citation_file_f1": 0.8,
  "citation_line_f1": 0.32,
  // token accounting (see §3.3)
  "main_agent_tokens": 180000,
  "subagent_tokens": 22000,
  "full_system_tokens": 202000
}
```

Detection rules are deliberately conservative and documented:

- **"edit"** = first `OperationRecord` whose `type`/`name` denotes a write
  (`edit`, `write`, `apply_patch`, `str_replace`). Everything before it that is
  a `read`/`search`/`subagent` counts toward `pre_edit_*`.
- **"broad search"** = a search op whose metadata marks a recursive/unbounded
  query (`grep -R`, `find`, no path scope, or a result set over a threshold).
  Wrappers set `metadata.broad = true`; absent that flag we infer from the
  command string and **log the inference** rather than silently guessing.
- **`repeated_read_ratio`** = reads of a path already read / total reads.

If a harness emits no read/search/subagent ops, the block is emitted with
nulls and a `reason: "no exploration telemetry"` — never fabricated.

### 3.3 Main-agent vs subagent token accounting

FastContext's headline caveat: main-agent token *savings* can be real while
total system cost rises, because the subagent's tokens are billed separately.
We must report both or we overstate savings.

`UsageRecord` (2026-06-19 ADR) already sums tokens/cost across turns. Extend
its accumulation with an **attribution tag** so a subagent's usage rolls into a
separate bucket:

- `agent_runner` / harness wrappers tag each `UsageRecord` with
  `role ∈ {"main", "subagent"}`.
- The per-run rollup emits `main_agent_tokens`, `subagent_tokens`,
  `full_system_tokens = main + subagent`, and the cost analogues
  (`main_agent_cost`, `subagent_cost`, `full_system_cost`, nullable as today).
- Derived efficiency columns for dashboards: `score_per_1M_tokens` (full
  system), `pass_per_dollar` (full system).

Subagent telemetry arrives through the **existing** marker path — a wrapper
emits one `AGENT_BENCHMARK_OP` per FastContext invocation:

```jsonc
AGENT_BENCHMARK_OP {
  "type": "subagent", "name": "fastcontext", "status": "ok",
  "elapsed_sec": 8.31,
  "metadata": {
    "query": "Find the false-sharing hotspot and counter update logic",
    "prompt_tokens": 11342, "completion_tokens": 512,
    "tool_calls_by_name": {"Grep": 7, "Glob": 2, "Read": 4},
    "final_answer_valid": true, "citation_count": 3,
    "citation_files": 2, "citation_lines": 94
  }
}
```

`harnesses/operations.py` already parses this into an `OperationRecord`; §3.2
reads its metadata. No new logging mechanism.

### 3.4 Standalone ExploreBench track

A new lightweight task type that scores *localization only*. It answers a
different question from Q&A ("can it answer?") and terminal-bench ("can it
solve?"): **"can it find the right evidence?"**

Task fixture (`data/explore_tasks/<product>/<id>.yaml`):

```yaml
id: onetbb_flow_graph_locate_buffering
product: oneTBB
query: >
  Find the docs and example code that explain how to build a bounded
  flow-graph pipeline.
references:
  - path: docs/flow_graph.md
    lines: [120, 180]
  - path: examples/flow_graph/pipeline.cpp
    lines: [35, 90]
score:
  - citation_validity
  - file_f1
  - line_f1
  - citation_compactness
```

Runner: an agentic arm given **read-only** `Read`/`Glob`/`Grep` over the target
repo/doc tree, prompted to return a `<final_answer>` block. Output is parsed by
§3.1 and scored against `references`. Emits a new `explore_runs.v1` artifact
(schema mirrors `task_runs.v1` shape: `results[]`, `summary.per_arm`,
`summary.comparisons`). Reference locations may be **oracle-derived** (reuse a
terminal-bench task's oracle diff) or **curated** (the YAML above).

Seed set: 5–10 tasks on oneTBB + Intel performance, where
`terminal-bench-tasks/intel-perf-*` already gives oracle solutions whose
touched files/ranges become free reference locations.

### 3.5 FastContext skill fixture + arm

Add `data/skills/fastcontext/SKILL.md` (a curated derivative of the upstream
skill: "invoke exploration before answering/editing/reviewing unfamiliar code;
use it instead of manual grep/glob chains when >1 file or cross-module logic is
involved; read narrow windows after it returns; do not repeat broad search").
This plugs into the **existing** arm machinery unchanged:

- `skill:data/skills/fastcontext` — skill injected as context (static).
- `skill-agent:data/skills/fastcontext` — progressive-disclosure agentic use.

And as a task-harness comparison ladder (the cleanest first experiment — no new
explorer model needed):

```
baseline                          # bare harness
+ fastcontext skill               # exploration treatment alone
+ intel skill                     # domain treatment alone
+ intel skill + fastcontext       # combined
```

Each rung changes one axis; model / question set / judge stay fixed, per
`docs/benchmarking-and-comparison.md`.

### 3.6 Dashboard panels

`report/` + `dashboard/aggregator.py` gain panels fed by §3.2/§3.3:

- **Score–token Pareto** (per arm/harness): `avg_score` vs `full_system_tokens`.
- **Pass-rate vs full-system cost** (not main-agent-only cost).
- **Citation F1** (file + line) per arm and per product.
- **Subagent usage rate** and **wasted-search-after-subagent**.
- A per-arm table:

  | arm/harness | pass_rate | avg_score | main_tokens | full_tokens | cost_usd | score_Δ | token_Δ |
  |---|---|---|---|---|---|---|---|

Rank artifacts by quality gain, token reduction, cost reduction, latency
reduction, pass-rate improvement, and quality-per-token.

## 4. What we deliberately do *not* adopt

- **A trained explorer model.** Out of scope. We measure the *treatment*; the
  cleanest first cut wraps a skill/CLI, not a fine-tune.
- **Patch-localization as the only quality signal.** It under-credits useful
  supporting evidence (tests, callers, config, neighbors). We always pair
  citation F1 with task pass-rate / judge score (§6).
- **A separate telemetry pipeline.** Everything rides `OperationRecord`,
  `AGENT_BENCHMARK_OP`, and `UsageRecord`. No second logging path.

## 5. Implementation tasks (sliced so each lands independently)

1. **[DONE]** `metrics/exploration.py`: `parse_final_answer`,
   `score_localization`, dataclasses; `tests/test_exploration_metrics.py`
   (malformed lines, whole-file citations, overlapping ranges, P/R/F1 fixtures,
   compactness). Line scoring uses interval arithmetic (no per-line set
   materialization), so a thousand-line citation is free.
2. **[DONE]** `harnesses/exploration.py`: derive `exploration_metrics` from
   `list[OperationRecord]` + token split; wired into `HarnessResult.as_dict`
   (emitted only when the stream has exploration signal); the block is
   documented in `task_runs.v1.json` under `metrics` (additive — `metrics`
   already allows `additionalProperties`, so no `v2` bump was needed). Tested
   with synthetic operation streams.
3. **[DONE]** Token attribution: `role` field on `UsageRecord` and a
   `roll_up_by_role` helper (`metrics/usage.py`) emitting `main/subagent/
   full_system` token + cost rollups (cost stays `None` when a bucket is
   unpriced, so an unpriced subagent never zeroes the system cost). Slice 2
   already splits tokens from subagent **operation** metadata; this is the
   LLM-call-path complement.
4. **[DONE]** `data/skills/fastcontext/SKILL.md` fixture; loads via
   `skill:` / `skill-agent:` factory paths (verified by test — no code change
   needed).
5. **[DONE]** Explorer wrapper + subagent telemetry: `explore/explorer.py`
   (`CommandExplorer` runs a CLI explorer and ingests its telemetry;
   `build_subagent_op` / `op_marker_line` emit the §3.3 `AGENT_BENCHMARK_OP`
   subagent event that `summarize_exploration` consumes).
6. **[DONE]** ExploreBench: `explore_runs.v1` schema (registered in
   `artifacts.py`), an `ExploreRunner` under `agent_benchmarks/explore/`, an
   `explore` CLI command group, and 6 seed tasks under `data/explore_tasks/`
   (dogfooding this repo with real-file references; Intel/oneAPI tasks plug in
   with the same schema via oracle-derived references).
7. **[DONE]** Report panels: `report/exploration_report.py` renders the
   ExploreBench leaderboard (file/line F1, validity, compactness, baseline
   deltas) and the trajectory/token panel from a `task_runs` artifact;
   `data/explore_tasks/README.md` documents the track and its fair-comparison
   rules.

All seven slices have landed. Slices 1–4 were additive and low-risk; 5–7 added
the ExploreBench track. Remaining future work is breadth, not new mechanism:
real curated Intel/oneAPI exploration tasks with oracle-derived line ranges, an
LLM-backed explorer arm, and wiring the role-tagged `UsageRecord` rollup into a
subagent-spawning answering arm once one exists.

## 6. Caveats

- **Localization is a proxy.** The paper itself notes edited-location scoring
  under-credits tests, callers, config, and neighboring code. For Intel
  docs/tasks, combine citation F1 with task pass-rate, judge score, and curated
  evidence. Never gate a release on F1 alone.
- **Fair comparison still binds.** Do not compare "FastContext vs docs vs
  skills" while also changing model/harness/question set. One axis at a time
  (`docs/benchmarking-and-comparison.md`).
- **Don't overstate savings.** Always report `full_system_tokens`/cost
  alongside `main_agent_tokens`; a subagent that shifts cost off the main
  trajectory has not necessarily reduced total cost.
- **Broad-search inference is heuristic.** When a wrapper doesn't tag
  `metadata.broad`, the inferred flag is logged, not silently trusted.

## 7. Open questions

- **O1 — Reference granularity.** File + line F1 ships first; do we add
  function/module mapping (needs a language-aware parser per product), or is
  file+line enough for the docs-heavy Intel corpus?
- **O2 — ExploreBench scope.** Curated doc/example references vs oracle-diff
  references — start curated for docs and oracle-derived for perf tasks, or
  standardize on one?
- **O3 — Subagent cost source.** When the exploration step is a real billed
  API call (vs an in-process tool), does `litellm.completion_cost` cover the
  explorer model, or do we need a price override (mirrors telemetry ADR O1)?
- **O4 — Schema timing.** Bump `task_runs.v2` now (additive) or fold the
  `exploration_metrics` documentation into Phase C's `scorecard.v1`?
- **O5 — Read-only enforcement.** ExploreBench needs the agent boxed to
  `Read`/`Glob`/`Grep`. Enforce via tool allow-list in the runner, or rely on
  the harness sandbox?
```
