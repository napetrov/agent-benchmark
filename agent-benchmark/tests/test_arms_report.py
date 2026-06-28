"""Tests for the arms-comparison Markdown report."""

from agent_benchmarks.report.arms_report import render_arms_report, _md_cell


def test_md_cell_escapes_pipes_and_newlines():
    assert _md_cell("a | b\nc") == r"a \| b c"
    assert _md_cell(None) == ""


def test_report_escapes_question_text_in_table():
    data = {
        "library_name": "oneTBB",
        "model": "m", "provider": "openai",
        "arms": ["baseline"],
        "baseline_arm": "baseline",
        "total_questions": 1,
        "answers": [],
        "evaluations": [
            {"question_text": "What | how\nnewline?",
             "scores": {"baseline": {"aggregate": 70}}}
        ],
        "summary": {"per_arm": {"baseline": {"avg_aggregate": 70.0, "n": 1}}},
    }
    md = render_arms_report(data)
    # The raw pipe inside the question must be escaped so the row stays valid.
    assert r"What \| how" in md
    assert "What | how\nnewline" not in md


def test_report_renders_cost_and_latency_section():
    data = {
        "library_name": "oneTBB", "model": "m", "provider": "openai",
        "arms": ["baseline", "skill"], "baseline_arm": "baseline",
        "total_questions": 1, "answers": [],
        "cost_summary": {
            "baseline": {"n": 2, "total_cost_usd": 0.0042, "cost_known_n": 1,
                         "prompt_tokens": 100, "completion_tokens": 40,
                         "total_tokens": 140, "mean_latency_sec": 1.5,
                         "mean_ttft_sec": None, "cache_hit_ratio": 0.5},
            "skill": {"n": 1, "total_cost_usd": None, "cost_known_n": 0,
                      "prompt_tokens": 200, "completion_tokens": 60,
                      "total_tokens": 260, "mean_latency_sec": 2.0,
                      "mean_ttft_sec": 0.3, "cache_hit_ratio": None},
        },
    }
    md = render_arms_report(data)
    assert "## Cost & latency" in md
    assert "$0.0042 (1/2)" in md  # partial-coverage flag: 1 of 2 rows priced
    assert "50.0%" in md          # cache-hit ratio rendered as percent
    assert "0.300" in md          # ttft for skill arm


def test_report_renders_agentic_section():
    data = {
        "library_name": "oneTBB", "model": "m", "provider": "openai",
        "arms": ["agent"], "baseline_arm": "baseline", "total_questions": 1,
        "answers": [
            {"arms": {"agent": {"agentic": True, "tool_call_count": 2, "iterations": 3}}}
        ],
    }
    md = render_arms_report(data)
    assert "Agentic tool use" in md
    assert "`agent`" in md
    assert "Tool-use rate" in md


def test_report_renders_skill_load_rate_from_summary():
    data = {
        "library_name": "oneTBB", "model": "m", "provider": "openai",
        "arms": ["skill_agent:onetbb-quickstart"],
        "baseline_arm": "baseline",
        "total_questions": 2,
        "answers": [],
        "agentic_usage_summary": {
            "skill_agent:onetbb-quickstart": {
                "n": 2,
                "avg_tool_calls": 0.5,
                "tool_use_rate": 0.5,
                "avg_iterations": 1.5,
                "skill_load_rate": 0.5,
            }
        },
    }
    md = render_arms_report(data)
    assert "Skill-load rate" in md
    assert "| `skill_agent:onetbb-quickstart` | 50% | 0.5 | 50% | 1.5 | 2 |" in md
