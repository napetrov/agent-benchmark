"""Tests for output-shaper plugins (ADR 2026-06-11 Phase C).

Output shapers post-process the model answer, so ``raw_answer_chars`` and
``final_answer_chars`` diverge — the metric divergence the plugin-delta view
consumes. These tests exercise the shaper offline (no LLM), the AgentConfig
plumbing, the metrics block, and an end-to-end paired plugin delta.
"""

from __future__ import annotations

import pytest

from agent_benchmarks.eval.plugin_delta import compare_plugin_runs
from agent_benchmarks.metrics.usage import UsageRecord
from agent_benchmarks.plugins import (
    PluginWrappedTreatment,
    apply_output_shapers,
    create_plugin,
    create_plugins,
    plugin_set_metadata,
    take_output_shapers,
    validate_plugins_for_harness,
)
from agent_benchmarks.treatments.base import AgentConfig, Treatment


class _EchoTreatment(Treatment):
    name = "baseline"

    def prepare(self, question_text, library_name, library_id=None):
        return AgentConfig(system_prompt="You are helpful.")


# ── spec parsing ────────────────────────────────────────────────────────

def test_truncate_spec_defaults():
    p = create_plugin("plugin:truncate")
    assert p.id == "truncate"
    assert p.kind == "output_shaper"
    assert p.is_output_shaper
    assert p.config["max_chars"] == 800


def test_truncate_spec_custom_max_chars():
    p = create_plugin("truncate:120")
    assert p.config["max_chars"] == 120


@pytest.mark.parametrize("spec", ["truncate:0", "truncate:-5", "truncate:abc"])
def test_truncate_spec_rejects_bad_max_chars(spec):
    with pytest.raises(ValueError, match="max_chars"):
        create_plugin(spec)


def test_truncate_spec_rejects_extra_parts():
    with pytest.raises(ValueError, match="truncate"):
        create_plugin("plugin:truncate:100:200")


def test_unknown_plugin_lists_valid_specs():
    with pytest.raises(ValueError, match="truncate"):
        create_plugin("plugin:nonsense")


# ── shaping behaviour ───────────────────────────────────────────────────

def test_shape_truncates_and_adds_ellipsis():
    p = create_plugin("truncate:10")
    out = p.shape("x" * 50)
    assert len(out) == 10
    assert out.endswith("…")


def test_shape_leaves_short_answer_untouched():
    p = create_plugin("truncate:100")
    assert p.shape("short") == "short"


def test_prompt_middleware_shape_is_noop():
    p = create_plugin("plugin:caveman")
    assert not p.is_output_shaper
    assert p.shape("anything") == "anything"


def test_apply_output_shapers_chains_in_order():
    plugins = create_plugins(["truncate:40", "truncate:10"])
    assert apply_output_shapers(plugins, "y" * 100) == ("y" * 9) + "…"


# ── AgentConfig plumbing ────────────────────────────────────────────────

def test_output_shaper_does_not_touch_system_prompt():
    wrapped = PluginWrappedTreatment(_EchoTreatment(), create_plugins(["truncate:50"]))
    cfg = wrapped.prepare("q", "oneTBB")
    # Prompt is unchanged; the shaper is registered for post-model use.
    assert cfg.system_prompt == "You are helpful."
    shapers, clean = take_output_shapers(cfg)
    assert [s.id for s in shapers] == ["truncate"]
    # Runtime objects must not leak into serialisable metadata.
    assert "output_shapers" not in clean
    # Provenance still recorded.
    assert clean["plugins"][0]["kind"] == "output_shaper"


def test_take_output_shapers_none_for_prompt_plugin():
    wrapped = PluginWrappedTreatment(_EchoTreatment(), create_plugins(["plugin:caveman"]))
    cfg = wrapped.prepare("q", "oneTBB")
    shapers, clean = take_output_shapers(cfg)
    assert shapers == []
    assert clean is cfg.metadata


# ── metrics block ───────────────────────────────────────────────────────

def test_metrics_records_distinct_raw_and_final_chars():
    rec = UsageRecord(model="m", provider="openai")
    m = rec.as_metrics_dict(answer_chars=500, final_chars=120)
    assert m["raw_answer_chars"] == 500
    assert m["final_answer_chars"] == 120


def test_metrics_final_defaults_to_raw():
    rec = UsageRecord(model="m", provider="openai")
    m = rec.as_metrics_dict(answer_chars=500)
    assert m["raw_answer_chars"] == m["final_answer_chars"] == 500


# ── harness compatibility ───────────────────────────────────────────────

def test_output_shaper_allowed_on_local_harnesses():
    plugins = create_plugins(["truncate:100"])
    for harness in ("arms-runner", "single-shot", "agent", "openclaw-agent"):
        validate_plugins_for_harness(plugins, harness)  # no raise


def test_output_shaper_rejected_on_terminal_bench():
    plugins = create_plugins(["truncate:100"])
    with pytest.raises(ValueError, match="output_shaper"):
        validate_plugins_for_harness(plugins, "terminal-bench:terminus")


# ── plugin-set identity ─────────────────────────────────────────────────

def test_plugin_set_label_and_id_track_truncate_config():
    a = plugin_set_metadata(create_plugins(["truncate:800"]))
    b = plugin_set_metadata(create_plugins(["truncate:200"]))
    assert a["plugin_set"] == "truncate:800"
    assert b["plugin_set"] == "truncate:200"
    assert a["plugin_set_id"] != b["plugin_set_id"]


# ── end-to-end paired delta (the machinery this slice makes live) ────────

def _arms_artifact_with_final(plugin_set: str, final_chars_by_q: dict[str, int]) -> dict:
    """Minimal arms.v1 artifact whose single arm carries raw/final char metrics."""
    plugin_id = "empty" if plugin_set == "none" else "trunc"
    answers = []
    for qid, final in final_chars_by_q.items():
        answers.append({
            "question_id": qid,
            "arms": {
                "baseline": {
                    "metrics": {"raw_answer_chars": 300, "final_answer_chars": final},
                },
            },
        })
    return {
        "schema_version": "arms.v1",
        "library_name": "oneTBB",
        "model": "m",
        "provider": "openai",
        "harness": "agent",
        "judge_model": "judge-m",
        "judge_provider": "openai",
        "plugin_set": plugin_set,
        "plugin_set_id": f"sha256:{plugin_id}",
        "plugins": [] if plugin_set == "none" else [{"id": "truncate"}],
        "arms": ["baseline"],
        "baseline_arm": "baseline",
        "total_questions": len(answers),
        "answers": answers,
        "evaluations": [
            {"question_id": qid, "scores": {"baseline": {"aggregate": 80}}}
            for qid in final_chars_by_q
        ],
        "cost_summary": {
            "baseline": {
                "total_cost_usd": 0.01,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "mean_latency_sec": 1.0,
                "mean_ttft_sec": None,
            },
        },
    }


def test_plugin_delta_reports_length_reduction_without_token_savings():
    # Control: no shaper, final == raw (300). Plugin: truncated to 100.
    control = _arms_artifact_with_final("none", {"q1": 300, "q2": 300})
    plugin = _arms_artifact_with_final("truncate:100", {"q1": 100, "q2": 100})

    out = compare_plugin_runs(control, plugin)

    text = out["answer_text_deltas"]["baseline"]
    # Raw model output size is unchanged (the shaper cut delivered text only).
    assert text["raw_answer_chars"]["delta"] == 0.0
    # Final delivered length dropped by 200 chars.
    assert text["final_answer_chars"]["delta"] == -200.0
    # Completion tokens (billed) unchanged — the point of an output shaper.
    assert out["cost_deltas"]["baseline"]["completion_tokens"]["delta"] == 0
