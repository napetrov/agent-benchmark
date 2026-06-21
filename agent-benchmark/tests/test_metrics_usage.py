"""Tests for the run-telemetry layer (UsageRecord + llm.py extraction).

Covers the ADR's required guarantees: defensive token/cache/reasoning
extraction, cost-None when litellm has no pricing, additive accumulation across
turns, streaming TTFT, and the per-row metrics{} block plus the retained
token_usage alias.
"""

import agent_benchmarks.llm as llm_mod
from agent_benchmarks.llm import _extract_usage
from agent_benchmarks.metrics.usage import UsageRecord, to_record


# ── fake litellm response shapes ────────────────────────────────────────────
class _Usage:
    def __init__(self, prompt=0, completion=0, total=0, cache_create=None,
                 cache_read=None, prompt_details=None, completion_details=None):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total
        if cache_create is not None:
            self.cache_creation_input_tokens = cache_create
        if cache_read is not None:
            self.cache_read_input_tokens = cache_read
        if prompt_details is not None:
            self.prompt_tokens_details = prompt_details
        if completion_details is not None:
            self.completion_tokens_details = completion_details


class _Resp:
    def __init__(self, usage):
        self.usage = usage


# ── extraction ──────────────────────────────────────────────────────────────
def test_extract_basic_tokens(monkeypatch):
    monkeypatch.setattr(llm_mod, "_safe_completion_cost", lambda r, m: 0.01)
    rec = _extract_usage(_Resp(_Usage(prompt=100, completion=40, total=140)),
                         "gpt-4o", "openai", latency_sec=1.5)
    assert (rec.prompt_tokens, rec.completion_tokens, rec.total_tokens) == (100, 40, 140)
    assert rec.cost_usd == 0.01
    assert rec.latency_sec == 1.5
    assert rec.model == "gpt-4o" and rec.provider == "openai"


def test_extract_anthropic_cache_fields(monkeypatch):
    monkeypatch.setattr(llm_mod, "_safe_completion_cost", lambda r, m: None)
    rec = _extract_usage(
        _Resp(_Usage(prompt=200, completion=30, total=230,
                     cache_create=150, cache_read=900)),
        "claude-sonnet-4-6", "anthropic", latency_sec=0.0)
    assert rec.cache_write_tokens == 150
    assert rec.cache_read_tokens == 900


def test_extract_openai_cached_and_reasoning_tokens(monkeypatch):
    monkeypatch.setattr(llm_mod, "_safe_completion_cost", lambda r, m: None)
    rec = _extract_usage(
        _Resp(_Usage(prompt=300, completion=80, total=380,
                     prompt_details={"cached_tokens": 256},
                     completion_details={"reasoning_tokens": 64})),
        "o1", "openai", latency_sec=0.0)
    assert rec.cache_read_tokens == 256
    assert rec.reasoning_tokens == 64


def test_extract_missing_usage_is_zeroed(monkeypatch):
    monkeypatch.setattr(llm_mod, "_safe_completion_cost", lambda r, m: None)
    rec = _extract_usage(_Resp(None), "m", "p", latency_sec=0.0)
    assert rec.total_tokens == 0 and rec.cost_usd is None


def test_cost_none_when_no_pricing():
    # _safe_completion_cost swallows any failure (raise OR litellm absent) → None.
    from agent_benchmarks.llm import _safe_completion_cost
    pytest_litellm = None
    try:
        import litellm as pytest_litellm  # noqa: F401
    except ImportError:
        pass
    if pytest_litellm is not None:
        # litellm present: a junk response makes completion_cost raise → None.
        orig = pytest_litellm.completion_cost
        try:
            pytest_litellm.completion_cost = lambda **kw: (_ for _ in ()).throw(
                Exception("no pricing"))
            assert _safe_completion_cost(_Resp(_Usage()), "made-up-model") is None
        finally:
            pytest_litellm.completion_cost = orig
    else:
        # litellm absent: import inside the helper fails → None.
        assert _safe_completion_cost(_Resp(_Usage()), "made-up-model") is None


# ── accumulation ─────────────────────────────────────────────────────────────
def test_add_sums_tokens_and_keeps_first_ttft():
    a = UsageRecord(prompt_tokens=10, completion_tokens=5, total_tokens=15,
                    cost_usd=0.01, latency_sec=1.0, ttft_sec=0.3, n_calls=1)
    b = UsageRecord(prompt_tokens=20, completion_tokens=8, total_tokens=28,
                    cost_usd=0.02, latency_sec=2.0, ttft_sec=0.9, n_calls=1)
    c = a + b
    assert (c.prompt_tokens, c.completion_tokens, c.total_tokens) == (30, 13, 43)
    assert c.cost_usd == 0.03
    assert c.latency_sec == 3.0
    assert c.ttft_sec == 0.3   # first non-null wins
    assert c.n_calls == 2


def test_add_cost_none_only_when_both_none():
    none_a = UsageRecord(cost_usd=None, n_calls=1)
    priced = UsageRecord(cost_usd=0.05, n_calls=1)
    assert (none_a + none_a).cost_usd is None
    assert (none_a + priced).cost_usd == 0.05  # priced subtotal, not None
    assert (none_a + priced).as_metrics_dict()["cost_known_calls"] == 1
    assert (none_a + priced).as_metrics_dict()["n_calls"] == 2


def test_sum_builtin_works_with_zero_start():
    recs = [UsageRecord(total_tokens=5), UsageRecord(total_tokens=7)]
    assert sum(recs, 0).total_tokens == 12


# ── serialization ────────────────────────────────────────────────────────────
def test_metrics_dict_has_required_fields():
    rec = UsageRecord(prompt_tokens=12, completion_tokens=3, total_tokens=15,
                      cost_usd=0.001, latency_sec=2.0)
    m = rec.as_metrics_dict(answer_chars=740)
    for key in ("prompt_tokens", "completion_tokens", "total_tokens",
                "cost_usd", "latency_sec", "ttft_sec", "cache_read_tokens",
                "cache_write_tokens", "reasoning_tokens", "n_calls",
                "cost_known_calls"):
        assert key in m
    assert m["raw_answer_chars"] == 740
    assert m["final_answer_chars"] == 740  # equal until a plugin shortens


def test_token_usage_alias():
    rec = UsageRecord(prompt_tokens=12, completion_tokens=3, total_tokens=15)
    assert rec.as_token_usage_dict() == {
        "prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15,
    }


def test_usage_record_supports_legacy_dict_access():
    rec = UsageRecord(prompt_tokens=12, completion_tokens=3, total_tokens=15)
    assert rec["total_tokens"] == 15
    assert rec.get("prompt_tokens") == 12
    assert rec.get("missing", "fallback") == "fallback"


# ── coercion ─────────────────────────────────────────────────────────────────
def test_to_record_from_legacy_dict():
    rec = to_record({"prompt_tokens": 10, "completion_tokens": 5,
                     "total_tokens": 15}, "m", "p")
    assert isinstance(rec, UsageRecord)
    assert rec.total_tokens == 15 and rec.model == "m"


def test_to_record_passthrough_backfills_provenance():
    rec = to_record(UsageRecord(total_tokens=9), "m", "p")
    assert rec.model == "m" and rec.provider == "p" and rec.total_tokens == 9


def test_to_record_preserves_explicit_zero_n_calls():
    # An explicit n_calls=0 (a no-LLM-call row) must not silently become 1.
    assert to_record({"total_tokens": 0, "n_calls": 0}).n_calls == 0
    # Absent n_calls still defaults to 1.
    assert to_record({"total_tokens": 5}).n_calls == 1


# ── streaming TTFT ───────────────────────────────────────────────────────────
class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content, usage=None):
        self.choices = [_Choice(content)]
        if usage is not None:
            self.usage = usage


def test_stream_call_measures_ttft(monkeypatch):
    monkeypatch.setattr(llm_mod, "_safe_completion_cost", lambda r, m: None)
    chunks = [_Chunk("Hello "), _Chunk("world"),
              _Chunk(None, usage=_Usage(prompt=5, completion=2, total=7))]

    def fake_completion(**kwargs):
        assert kwargs.get("stream") is True
        return iter(chunks)

    text, rec = llm_mod._stream_call(fake_completion, "m", [{"role": "user", "content": "hi"}],
                                     None, "m", "openai")
    assert text == "Hello world"
    assert rec.ttft_sec is not None and rec.ttft_sec >= 0.0
    assert rec.total_tokens == 7  # usage read from terminal chunk
