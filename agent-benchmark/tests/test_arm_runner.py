"""Tests for the N-arm runner (answer generation + judging)."""

import agent_benchmarks.eval.arm_runner as arm_runner_mod
from agent_benchmarks.eval.arm_runner import ArmRunner
from agent_benchmarks.treatments import BaselineTreatment, SkillTreatment
from agent_benchmarks.skills import load_skill
from agent_benchmarks.plugins import create_plugins, plugin_set_metadata, wrap_treatments


def _patch_llm(monkeypatch, captured):
    def fake_call(prompt, model, provider="openai", api_key=None, system=None, **kw):
        captured.append({"prompt": prompt, "system": system})
        return f"answer (system={'yes' if system else 'no'})", {
            "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15
        }

    monkeypatch.setattr(arm_runner_mod, "llm_call_with_usage", fake_call)


QUESTIONS = [
    {"id": "q1", "question": "How do I parallelize a loop?", "category": "usage"},
    {"id": "q2", "question": "How do I sum an array in parallel?"},
]


def test_arm_runner_generates_per_arm(monkeypatch):
    captured = []
    _patch_llm(monkeypatch, captured)

    skill = load_skill("data/skills/onetbb-quickstart")
    runner = ArmRunner([BaselineTreatment(), SkillTreatment(skill)])
    records = runner.run("oneTBB", QUESTIONS, concurrency=1)

    assert len(records) == 2
    rec = records[0]
    assert set(rec["arms"].keys()) == {"baseline", "skill:onetbb-quickstart"}
    # baseline has no context, skill arm does
    assert rec["arms"]["baseline"]["context_chunks"] == []
    assert rec["arms"]["skill:onetbb-quickstart"]["context_chunks"]
    # 2 questions x 2 arms = 4 LLM calls
    assert len(captured) == 4


def test_arm_runner_requires_at_least_one_arm():
    import pytest
    with pytest.raises(ValueError):
        ArmRunner([])


class _FakeJudge:
    """Scores by answer length so arms get distinct, deterministic numbers."""

    def score_answer(self, library_name, question, answer, context="", ground_truth=None):
        agg = 80 if context.strip() and context != "(No documentation retrieved)" else 60
        return {"aggregate": agg, "correctness": agg}


def test_arm_runner_judge_computes_deltas(monkeypatch):
    captured = []
    _patch_llm(monkeypatch, captured)

    skill = load_skill("data/skills/onetbb-quickstart")
    runner = ArmRunner([BaselineTreatment(), SkillTreatment(skill)])
    records = runner.run("oneTBB", QUESTIONS, concurrency=1)

    evaluations = runner.judge(_FakeJudge(), "oneTBB", records, baseline_arm="baseline")
    assert len(evaluations) == 2
    ev = evaluations[0]
    assert ev["scores"]["baseline"]["aggregate"] == 60
    assert ev["scores"]["skill:onetbb-quickstart"]["aggregate"] == 80
    assert ev["deltas_vs_baseline"]["skill:onetbb-quickstart"] == 20.0

    output = runner.build_output("oneTBB", records, evaluations, baseline_arm="baseline")
    summary = output["summary"]["per_arm"]
    assert summary["baseline"]["avg_aggregate"] == 60.0
    assert summary["skill:onetbb-quickstart"]["delta_vs_baseline"] == 20.0


def test_build_output_without_evaluations(monkeypatch):
    captured = []
    _patch_llm(monkeypatch, captured)
    runner = ArmRunner([BaselineTreatment()])
    records = runner.run("oneTBB", QUESTIONS[:1], concurrency=1)
    output = runner.build_output("oneTBB", records)
    assert "summary" not in output
    assert output["arms"] == ["baseline"]


def test_arm_runner_emits_metrics_block_and_alias(monkeypatch):
    captured = []
    _patch_llm(monkeypatch, captured)
    runner = ArmRunner([BaselineTreatment()])
    records = runner.run("oneTBB", QUESTIONS[:1], concurrency=1)
    arm = records[0]["arms"]["baseline"]

    # Legacy alias preserved.
    assert arm["token_usage"] == {"prompt_tokens": 10, "completion_tokens": 5,
                                  "total_tokens": 15}
    # New metrics block present with required + optional fields.
    m = arm["metrics"]
    assert m["prompt_tokens"] == 10 and m["completion_tokens"] == 5
    assert m["total_tokens"] == 15
    assert m["cost_usd"] is None          # dict stub carries no pricing
    assert "latency_sec" in m and "ttft_sec" in m
    assert m["raw_answer_chars"] == m["final_answer_chars"]

    output = runner.build_output("oneTBB", records)
    cs = output["cost_summary"]["baseline"]
    assert cs["n"] == 1
    assert cs["total_tokens"] == 15
    assert cs["total_cost_usd"] is None
    assert cs["cost_known_n"] == 0   # dict stub has no pricing
    assert cs["mean_ttft_sec"] is None


def test_cost_summary_flags_partial_pricing_by_call():
    runner = ArmRunner([BaselineTreatment()])
    records = [{
        "arms": {
            "agent": {
                "metrics": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "cost_usd": 0.01,
                    "cost_known_calls": 1,
                    "n_calls": 2,
                    "latency_sec": 1.0,
                }
            }
        }
    }]

    cs = runner._cost_summary(records)["agent"]
    assert cs["total_cost_usd"] == 0.01
    assert cs["cost_known_n"] == 1
    assert cs["total_llm_calls"] == 2


def test_arm_runner_stamps_plugin_set_and_harness(monkeypatch):
    captured = []
    _patch_llm(monkeypatch, captured)
    plugins = create_plugins(["plugin:caveman"])
    plugin_set = plugin_set_metadata(plugins)
    treatments = wrap_treatments([BaselineTreatment()], plugins)

    runner = ArmRunner(
        treatments,
        harness="openclaw-agent",
        plugin_set=plugin_set,
    )
    records = runner.run("oneTBB", QUESTIONS[:1], concurrency=1)
    output = runner.build_output("oneTBB", records)

    assert "caveman style" in captured[0]["system"]
    assert records[0]["arms"]["baseline"]["plugin_set"] == "caveman:full"
    assert records[0]["arms"]["baseline"]["harness"] == "openclaw-agent"
    assert output["plugin_set"] == "caveman:full"
    assert output["harness"] == "openclaw-agent"
