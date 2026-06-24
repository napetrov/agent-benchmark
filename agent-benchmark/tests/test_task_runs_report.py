"""Tests for the executable task-run Markdown report renderer."""

from agent_benchmarks.report.task_runs_report import _md_cell, render_task_runs_report


def _artifact():
    return {
        "schema_version": "task_runs.v1",
        "model": "haiku",
        "repeats": 1,
        "baseline_harness": "docker-claude",
        "harnesses": ["docker-claude", "docker-claude-skill:s/SKILL.md"],
        "tasks": [
            {"name": "false-sharing", "path": "p", "metadata": {"difficulty": "medium"},
             "verifier": {}, "agent": {}, "environment": {}},
            {"name": "simd-sort", "path": "p", "metadata": {"difficulty": "hard"},
             "verifier": {}, "agent": {}, "environment": {}},
        ],
        "results": [
            {"task": "false-sharing", "harness": "docker-claude", "passed": False,
             "reward": 0.0, "returncode": 0, "output_dir": None,
             "metrics": {"operation_count": 1, "operations_by_type": {}, "cost_usd": 0.06}},
            {"task": "false-sharing", "harness": "docker-claude-skill:s/SKILL.md", "passed": True,
             "reward": 1.0, "returncode": 0, "output_dir": None,
             "metrics": {"operation_count": 1, "operations_by_type": {}, "cost_usd": 0.08}},
            {"task": "simd-sort", "harness": "docker-claude", "passed": True,
             "reward": 1.0, "returncode": 0, "output_dir": None,
             "metrics": {"operation_count": 1, "operations_by_type": {}, "cost_usd": 0.24}},
            {"task": "simd-sort", "harness": "docker-claude-skill:s/SKILL.md", "passed": False,
             "reward": 0.0, "returncode": 0, "output_dir": None,
             "metrics": {"operation_count": 1, "operations_by_type": {}, "cost_usd": 0.57}},
        ],
        "summary": {
            "per_harness": {
                "docker-claude": {"n": 2, "passed": 1, "pass_rate": 0.5, "avg_reward": 0.5,
                                  "elapsed_sec": 60.0, "operation_count": 2,
                                  "operations_by_type": {},
                                  "cost": {"total_cost_usd": 0.30, "cost_known_n": 2,
                                           "completion_tokens": 100, "cache_read_tokens": 9}},
                "docker-claude-skill:s/SKILL.md": {"n": 2, "passed": 1, "pass_rate": 0.5,
                                  "avg_reward": 0.5, "elapsed_sec": 90.0, "operation_count": 2,
                                  "operations_by_type": {},
                                  "cost": {"total_cost_usd": 0.65, "cost_known_n": 2,
                                           "completion_tokens": 150, "cache_read_tokens": 13}},
            },
            "comparisons": {
                "docker-claude-skill:s/SKILL.md": {
                    "baseline_harness": "docker-claude", "pass_rate_delta": 0.0,
                    "passed_delta": 0, "operation_count_delta": 0, "cost_delta_usd": 0.35},
            },
        },
    }


def test_md_cell_escapes_pipes_and_newlines():
    assert _md_cell("a | b\nc") == r"a \| b c"
    assert _md_cell(None) == ""


def test_report_has_all_sections():
    md = render_task_runs_report(_artifact())
    for section in ("# Executable task-run report", "## Headline", "## Difficulty rollup",
                    "## Comparison vs baseline", "## Per-task pass + cost",
                    "## Per-cell answer detail"):
        assert section in md


def test_report_difficulty_rollup_splits_medium_and_hard():
    md = render_task_runs_report(_artifact())
    # medium has 1 task, hard has 1 task
    assert "| medium | 1 |" in md
    assert "| hard | 1 |" in md


def test_report_renders_without_cell_dirs():
    # output_dir is None for every row -> self-report column blank, no crash.
    md = render_task_runs_report(_artifact())
    assert "(no result)" in md
