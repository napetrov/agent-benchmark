# ADR: Per-run telemetry — tokens, cost, cache, and latency as first-class metrics

**Status:** PROPOSED. Extends the
[evaluation-beyond-MCP-docs umbrella](2026-06-10-evaluation-beyond-mcp-docs.md)
(BACKLOG #59). Carves the **metrics-capture slice** out of the
[plugin-and-harness-aware ADR](2026-06-11-plugin-and-harness-aware-benchmarks.md)
so it can land independently, and answers that ADR's open question **O5**
(which cost metrics are required in every result row). Builds on
`agent_benchmarks/llm.py`, `eval/arm_runner.py`, `eval/agent_runner.py`, and the
`agent_benchmarks/metrics/` package.

**Date:** 2026-06-19

**Phase:** C.0 in the umbrella rollout — a prerequisite for the plugin-aware
cells (Phase C). The plugin ADR's §3.3 `metrics{}` block, its Caveman
token/length trade-off report, and its plugin-delta computation all assume a
telemetry record that does not exist yet. This ADR defines that record and lands
it ahead of the harness/plugin rework, so plugin work consumes a ready-made
metrics layer instead of inventing one mid-stream.

---

## 1. Context

The benchmark already conditions every comparison on `(model, harness,
plugin_set)` and forbids deltas across cells. It can compare N treatment arms
and score them with an LLM-as-judge. What it cannot yet do is say how *much*
each answer cost to produce.

Today the only resource signals captured per run are:

- `prompt_tokens`, `completion_tokens`, `total_tokens` — read off
  `resp.usage` in `llm.py:133` (`llm_call_with_usage`) and accumulated per turn
  in `agent_runner.py:75-89`.
- `elapsed_sec` — wall-clock for the whole arm, stamped in
  `arm_runner.py:185,224`.
- For agentic arms: `iterations`, `tool_call_count`, `stopped_reason`.

That is not enough to compare features from the standpoints we care about:

- **Cost.** No dollar figure is recorded. Two arms with equal judge scores but a
  3× cost gap look identical in every current report. A doc-injection arm that
  wins on quality may lose on cost-per-correct-answer, and we cannot see it.
- **Caching.** Prompt caching (Anthropic `cache_creation_input_tokens` /
  `cache_read_input_tokens`; OpenAI `prompt_tokens_details.cached_tokens`) is
  not extracted. A context-heavy arm whose injected docs are cached across
  questions has a very different real cost than its raw token count implies, and
  cache state silently varies between runs — a confound the plugin ADR §3.4
  explicitly warns about ("warm caches … masquerade as a plugin effect").
- **Latency.** Only whole-arm wall-clock exists. There is no per-call latency,
  no time-to-first-token (TTFT), and no per-tool execution time, so we cannot
  separate model latency from tool/harness overhead.
- **Billed vs. raw.** For output-shaping plugins (Caveman), the plugin ADR
  requires both the raw model output size and the post-plugin final size;
  neither is captured, and there is nowhere to put them.

All LLM traffic already funnels through two functions in `llm.py`
(`llm_call_with_usage`, `chat_completion`), so there is exactly one place to add
extraction. This is the cheap moment to do it.

## 2. Decision

Introduce a single normalized telemetry record, `UsageRecord`, that **every**
LLM call returns, and stamp a `metrics{}` block on every result row. The block
uses the field names already specified in the plugin ADR §3.3 so that Phase C
needs no second migration.

Rules:

1. Every call through `llm.py` produces a `UsageRecord`. Extraction is
   defensive: any field a provider does not return defaults to `0` / `None`,
   never an error.
2. Every per-arm result row carries a `metrics{}` block (tokens, cache, cost,
   latency). The legacy `token_usage` dict is retained as an alias so existing
   readers and tests keep working.
3. Cost is computed from the provider response via `litellm.completion_cost`,
   not re-derived from a local price table. When litellm has no pricing for a
   model, cost is `null` (not `0.0`) and the gap is logged — a missing price is
   not the same as a free call.
4. Cache read/write tokens are captured wherever the provider exposes them.
   Cache state is part of the run manifest so a warm-cache run is never silently
   compared to a cold one.
5. Latency is captured per call. TTFT is captured only when streaming is enabled
   (see §3.4) and is `null` otherwise.
6. Accumulation across agentic turns is additive and loss-free: the per-turn
   records sum into a per-arm total, and per-turn detail is retained.

This ADR answers plugin ADR **O5**: the **required** per-row metrics are
`prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd` (nullable),
`latency_sec`, and (agentic) `tool_call_count`. Cache tokens, `reasoning_tokens`,
`ttft_sec`, and raw-vs-final sizes are **recorded when available** but not
required, because not every provider/harness exposes them.

## 3. Detailed design

### 3.1 The `UsageRecord`

A new `agent_benchmarks/metrics/usage.py` defines one frozen dataclass that is
the single shape returned by the `llm.py` chokepoints:

```python
@dataclass(frozen=True)
class UsageRecord:
    # tokens
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0          # o1/o-style; 0 when absent
    # cache (provider-dependent; 0 when not exposed)
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # cost — None means "no pricing available", distinct from 0.0
    cost_usd: float | None = None
    # latency
    latency_sec: float = 0.0
    ttft_sec: float | None = None      # only when streaming; else None
    # provenance / accumulation
    model: str = ""
    provider: str = ""
    n_calls: int = 1

    def __add__(self, other: "UsageRecord") -> "UsageRecord": ...
    def as_metrics_dict(self) -> dict: ...  # emits the §3.3 metrics block
```

`__add__` sums tokens/cost/latency/`n_calls`, takes the **first** non-null
`ttft_sec` (first token of the first turn), and preserves `model`/`provider`.
This replaces the manual dict-summing at `agent_runner.py:86-89`.

### 3.2 Extraction in `llm.py`

A shared helper does provider-aware extraction so both call paths agree:

```python
def _extract_usage(resp, model, provider, latency_sec, ttft_sec=None) -> UsageRecord:
    u = getattr(resp, "usage", None)
    # tokens (defensive getattr, default 0)
    # cache: anthropic cache_creation_input_tokens / cache_read_input_tokens;
    #        openai usage.prompt_tokens_details.cached_tokens
    # reasoning: usage.completion_tokens_details.reasoning_tokens
    cost = _safe_completion_cost(resp, model)   # litellm.completion_cost; None on failure
    return UsageRecord(...)
```

- `llm_call_with_usage` and `chat_completion` wrap the existing
  `completion(...)` call with a `time.time()` span for `latency_sec`, then call
  `_extract_usage`.
- `llm_call_with_usage` returns `(text, UsageRecord)` instead of `(text, dict)`.
  A thin `.as_token_usage_dict()` keeps the old 3-key dict available where
  callers still expect it, so the change is non-breaking.
- `_safe_completion_cost` calls `litellm.completion_cost(completion_response=resp)`
  inside a try/except; on any failure it logs once per model and returns `None`.

### 3.3 The per-row `metrics{}` block

Result rows in `arm_runner.py` (`:168-186`, `:209-225`) gain a `metrics` block
matching plugin ADR §3.3:

```jsonc
"metrics": {
  "prompt_tokens": 1200,
  "completion_tokens": 260,
  "total_tokens": 1460,
  "reasoning_tokens": 0,
  "cache_read_tokens": 900,
  "cache_write_tokens": 0,
  "cost_usd": 0.0043,            // null if litellm has no pricing
  "latency_sec": 3.8,
  "ttft_sec": null,              // set only under streaming
  "n_calls": 1,
  // output-shaper support (raw model output vs final answer):
  "raw_answer_chars": 1100,
  "final_answer_chars": 1100    // == raw until a plugin shortens it
}
```

`token_usage` (the legacy 3-key dict) is kept alongside `metrics` for one schema
generation. For now `raw_*` and `final_*` are equal (no plugin yet); the fields
exist so Phase C's output shapers have a home and reports never have to
back-fill.

### 3.4 TTFT and streaming (behind a flag)

TTFT is only meaningful with token streaming, and streaming complicates the
existing retry/usage path. So:

- Add an optional `stream: bool = False` parameter to the `llm.py` entry points,
  surfaced as a run-level config flag (default **off**). Reports state when TTFT
  is unavailable rather than emitting a fabricated value.
- When `stream=True`: iterate the litellm stream, stamp the time of the first
  content chunk as `ttft_sec`, accumulate the final text, and read usage from
  the terminal chunk (litellm sets `stream_options={"include_usage": True}`).
- When `stream=False`: `ttft_sec` is `null`; everything else is captured exactly
  as today.

Streaming interacts with retries (a stream can fail mid-iteration). The flag
keeps the well-tested non-streaming path as the default; streaming is opt-in for
latency-sensitive sweeps and validated separately.

### 3.5 Per-turn and per-tool detail (agentic)

`agent_runner.run_agent_loop` accumulates a `UsageRecord` per turn (via
`__add__`) and additionally records:

- `per_turn`: a list of `{latency_sec, prompt_tokens, completion_tokens,
  cache_read_tokens}` so cache warm-up across turns is visible.
- per-tool timing: wrap `tool.call(**args)` at `agent_runner.py:126` in a
  `time.time()` span and add `tool_elapsed_sec` to each transcript entry. This
  separates model latency from tool/harness overhead.

### 3.6 Aggregation and schema

- `arm_runner._summarize` (`:317`) gains per-arm rollups: total `cost_usd`, mean
  `latency_sec`, mean `ttft_sec` (when present), summed tokens, and a
  cache-hit ratio (`cache_read_tokens / prompt_tokens`).
- Bump the artifact schema to **`arms.v2`** — purely additive (`metrics` block +
  per-arm cost/latency rollups). `arms.v1` files still load; the version bump
  signals the new fields to readers. The manifest records the cache policy and
  the `stream` flag so runs are comparable.

### 3.7 Reporting and dashboard

`report/` and `dashboard/aggregator.py` surface the new columns: cost per
question, tokens per arm, cache-hit %, and latency/TTFT. These are the inputs the
plugin ADR's Caveman trade-off section (§3.4) consumes — cost/length reduction
weighed against the judge-score and pass-rate tax.

## 4. Implementation tasks

1. `agent_benchmarks/metrics/usage.py`: `UsageRecord`, `__add__`,
   `as_metrics_dict`, `as_token_usage_dict`.
2. `llm.py`: `_extract_usage` + `_safe_completion_cost`; latency span; return
   `UsageRecord`; optional `stream` path for TTFT (default off).
3. `arm_runner.py`: emit `metrics{}` (keep `token_usage` alias); cost/latency
   rollups in `_summarize`.
4. `agent_runner.py`: accumulate `UsageRecord`; `per_turn` list; per-tool timing
   in transcript.
5. Schema `arms.v2.json` (additive); manifest records cache policy + `stream`.
6. Reporting/dashboard columns: cost, tokens, cache-hit %, latency/TTFT.
7. Tests: `tests/test_metrics_usage.py` with a fake litellm response proving
   extraction (tokens, cache, reasoning, cost-None-on-missing-pricing) and
   `__add__` accumulation; a streaming-fake test for `ttft_sec`; an
   `arm_runner` test asserting the `metrics` block and the retained
   `token_usage` alias.

## 5. Consequences

- **Positive:** every comparison gains a cost/latency/cache standpoint, not just
  quality. Cost-per-correct-answer and cache-hit ratio become reportable.
- **Positive:** Phase C inherits a ready `metrics{}` block with the exact field
  names it specified; no second migration.
- **Positive:** one extraction chokepoint (`llm.py`) keeps single-shot and
  agentic paths consistent.
- **Negative:** `litellm.completion_cost` pricing can lag new models, yielding
  `null` cost. Mitigation: `null` is explicit and logged, never silently `0.0`.
- **Negative:** streaming for TTFT adds a second code path with its own retry
  edge cases. Mitigation: off by default; the non-streaming path is unchanged.
- **Negative:** artifacts grow (per-turn, per-tool detail). Mitigation: detail is
  bounded by iteration/tool budgets already in place.

## 6. Open questions

- **O1 — Cost source of truth.** Is `litellm.completion_cost` accurate enough for
  Intel/self-hosted or OpenRouter-routed models, or do we need a local price
  override table for the models we actually sweep?
- **O2 — Cache attribution.** Anthropic and OpenAI report cache tokens
  differently (creation+read vs. a single cached count). Do we normalize to one
  cache-hit ratio, or keep provider-native fields and let reports translate?
- **O3 — TTFT reliability.** Provider/proxy buffering can make TTFT noisy. How
  many repeats before a TTFT number is reportable, and do we gate it behind a
  minimum run count like the plugin ADR does for plugin deltas?
- **O4 — Schema migration.** Do we ship `arms.v2` now and migrate readers, or
  keep emitting `arms.v1` with extra fields until Phase C introduces
  `scorecard.v1`? (Leaning v2-now, additive.)
- **O5 — Per-tool cost.** In-process tools are free, but an `openclaw-agent` or
  `terminal-bench` harness may make billable sub-calls. Should per-tool timing
  grow a per-tool cost field when the harness exposes it?
