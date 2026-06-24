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


def test_rollups_keep_distinct_harnesses():
    # Two non-skill harnesses must NOT be merged into one bucket: each keeps its
    # own pass count. codex solves t1, claude-code fails it.
    data = {
        "schema_version": "task_runs.v1", "model": "m", "repeats": 1,
        "baseline_harness": "claude-code", "harnesses": ["claude-code", "codex"],
        "tasks": [{"name": "t1", "path": "p", "metadata": {"difficulty": "easy"},
                   "verifier": {}, "agent": {}, "environment": {}}],
        "results": [
            {"task": "t1", "harness": "claude-code", "passed": False, "reward": 0.0,
             "returncode": 0, "output_dir": None,
             "metrics": {"operation_count": 0, "operations_by_type": {}, "cost_usd": 0.01}},
            {"task": "t1", "harness": "codex", "passed": True, "reward": 1.0,
             "returncode": 0, "output_dir": None,
             "metrics": {"operation_count": 0, "operations_by_type": {}, "cost_usd": 0.02}},
        ],
        "summary": {"per_harness": {
            "claude-code": {"n": 1, "passed": 0, "pass_rate": 0.0, "avg_reward": 0.0,
                            "elapsed_sec": 1.0, "operation_count": 0, "operations_by_type": {},
                            "cost": {"total_cost_usd": 0.01, "cost_known_n": 1}},
            "codex": {"n": 1, "passed": 1, "pass_rate": 1.0, "avg_reward": 1.0,
                      "elapsed_sec": 1.0, "operation_count": 0, "operations_by_type": {},
                      "cost": {"total_cost_usd": 0.02, "cost_known_n": 1}},
        }, "comparisons": {}},
    }
    md = render_task_runs_report(data)
    # both harness ids appear as distinct columns; per-task row shows 0/1 and 1/1
    assert "`claude-code` pass" in md
    assert "`codex` pass" in md
    assert "| t1 | easy | 0/1 |" in md  # claude-code column = 0/1, not merged with codex


def test_per_task_cost_unknown_renders_dash():
    # A harness whose rows omit cost_usd (oracle/dry-run) must show — not $0.0000.
    data = {
        "schema_version": "task_runs.v1", "model": "m", "repeats": 1,
        "harnesses": ["docker-oracle"],
        "tasks": [{"name": "t1", "path": "p", "metadata": {"difficulty": "easy"},
                   "verifier": {}, "agent": {}, "environment": {}}],
        "results": [
            {"task": "t1", "harness": "docker-oracle", "passed": True, "reward": 1.0,
             "returncode": 0, "output_dir": None,
             "metrics": {"operation_count": 0, "operations_by_type": {}}},  # no cost_usd
        ],
        "summary": {"per_harness": {
            "docker-oracle": {"n": 1, "passed": 1, "pass_rate": 1.0, "avg_reward": 1.0,
                              "elapsed_sec": 1.0, "operation_count": 0, "operations_by_type": {},
                              "cost": {"total_cost_usd": None, "cost_known_n": 0}},
        }, "comparisons": {}},
    }
    md = render_task_runs_report(data)
    assert "| t1 | easy | 1/1 | — |" in md
    assert "$0.0000" not in md
