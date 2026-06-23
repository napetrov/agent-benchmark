"""Tests for the standalone Docker solver harness and its telemetry rollup.

Docker itself is never invoked here: the pipeline steps are monkeypatched so the
tests cover JSON-telemetry parsing, the reward contract, repeats, and the
cost/per-task summary aggregation — the parts that turn raw runs into tracked,
saved data.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_benchmarks.artifacts import validate_artifact
from agent_benchmarks.harnesses import TaskSuiteRunner, load_task
from agent_benchmarks.harnesses.docker_solver import (
    DockerSolverHarness,
    _DEFAULT_BUILD_TIMEOUT,
    _DEFAULT_VERIFY_TIMEOUT,
    _last_json_object,
    _parse_claude_json,
    _task_build_timeout,
    _task_verify_timeout,
)
from agent_benchmarks.harnesses.registry import create_harness, known_harnesses
from agent_benchmarks.harnesses.runner import summarize_task_results

# A representative `claude -p --output-format json` result line.
_CLAUDE_JSON = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 4200,
        "ttft_ms": 1646,
        "num_turns": 5,
        "result": "done",
        "total_cost_usd": 0.0731,
        "usage": {
            "input_tokens": 6086,
            "output_tokens": 512,
            "cache_read_input_tokens": 1024,
            "cache_creation_input_tokens": 16389,
        },
    }
)


def _fixture_task(tmp_path: Path) -> Path:
    task = tmp_path / "intel-perf-toy"
    (task / "tests").mkdir(parents=True)
    (task / "environment").mkdir()
    (task / "solution").mkdir()
    (task / "instruction.md").write_text(
        "Optimize the loop. Recompile with `g++ -O3 bench.cpp -o /app/bench`.",
        encoding="utf-8",
    )
    (task / "task.toml").write_text(
        '[metadata]\ndifficulty = "medium"\ntags = ["c++", "perf"]\n'
        "[agent]\ntimeout_sec = 30\n",
        encoding="utf-8",
    )
    return task


# ── telemetry parsing ───────────────────────────────────────────────────────


def test_parse_claude_json_maps_full_telemetry():
    usage = _parse_claude_json(_CLAUDE_JSON, "t", "haiku", latency=9.9)
    assert usage is not None
    assert usage.prompt_tokens == 6086
    assert usage.completion_tokens == 512
    assert usage.total_tokens == 6598
    assert usage.cache_read_tokens == 1024
    assert usage.cache_write_tokens == 16389
    assert usage.cost_usd == 0.0731
    assert usage.cost_known_calls == 1
    assert usage.n_calls == 5
    # duration_ms wins over the wall-clock fallback; ttft is converted to seconds.
    assert usage.latency_sec == 4.2
    assert usage.ttft_sec == 1.646


def test_parse_claude_json_returns_none_on_garbage():
    assert _parse_claude_json("not json at all", "t", "m", 1.0) is None


def test_parse_claude_json_uses_wallclock_when_duration_absent():
    payload = json.dumps({"result": "ok", "usage": {"input_tokens": 1, "output_tokens": 2}})
    usage = _parse_claude_json(payload, "t", "m", latency=3.5)
    assert usage is not None
    assert usage.latency_sec == 3.5
    assert usage.cost_usd is None
    assert usage.cost_known_calls == 0


def test_last_json_object_picks_final_result_line():
    text = "log noise\n{\"a\": 1}\nINFO building\n" + _CLAUDE_JSON + "\n"
    obj = _last_json_object(text)
    assert obj["total_cost_usd"] == 0.0731


# ── task-driven timeouts ──────────────────────────────────────────────────────


def test_build_timeout_honors_task_metadata(tmp_path):
    task = load_task(_fixture_task(tmp_path))
    # fixture has no build_timeout_sec -> default fallback
    assert _task_build_timeout(task) == _DEFAULT_BUILD_TIMEOUT
    assert _task_verify_timeout(task) == _DEFAULT_VERIFY_TIMEOUT


def test_build_and_verify_timeouts_read_toml(tmp_path):
    task = tmp_path / "intel-perf-slow-build"
    (task / "tests").mkdir(parents=True)
    (task / "environment").mkdir()
    (task / "instruction.md").write_text("x", encoding="utf-8")
    (task / "task.toml").write_text(
        "[metadata]\ntags = []\n"
        "[environment]\nbuild_timeout_sec = 900\n"
        "[verifier]\ntimeout_sec = 120\n",
        encoding="utf-8",
    )
    spec = load_task(task)
    assert _task_build_timeout(spec) == 900.0
    assert _task_verify_timeout(spec) == 120.0


# ── registry wiring ───────────────────────────────────────────────────────────


def test_registry_builds_docker_harnesses():
    assert isinstance(create_harness("docker-oracle"), DockerSolverHarness)
    assert create_harness("docker-oracle").mode == "oracle"
    claude = create_harness("docker-claude")
    assert claude.mode == "claude" and claude.skill_path is None
    skill = create_harness("docker-claude-skill:data/skills/x/SKILL.md")
    assert skill.skill_path == "data/skills/x/SKILL.md"
    assert "docker-claude" in known_harnesses()


def test_docker_claude_skill_requires_a_path():
    import pytest

    with pytest.raises(ValueError):
        create_harness("docker-claude-skill:")


# ── run contract (Docker steps patched out) ──────────────────────────────────


def _patch_pipeline(monkeypatch, *, reward: float, usage_json: str | None):
    """Stub the Docker-touching steps so run() exercises only host logic."""
    import agent_benchmarks.harnesses.docker_solver as mod

    # run()'s cleanup calls _docker(["rm", ...]); stub it so these stay
    # Docker-free even on hosts without a `docker` binary.
    monkeypatch.setattr(mod, "_docker", lambda *a, **k: None)
    monkeypatch.setattr(DockerSolverHarness, "_build_image", lambda self, t, i, log: None)
    monkeypatch.setattr(DockerSolverHarness, "_start_container", lambda self, i, c, log: None)
    monkeypatch.setattr(DockerSolverHarness, "_solve_oracle", lambda self, t, c, log: None)

    def fake_verify(self, task, container, output_dir, log):
        (output_dir / "reward.txt").write_text(str(reward), encoding="utf-8")
        return reward

    monkeypatch.setattr(DockerSolverHarness, "_verify", fake_verify)

    if usage_json is not None:
        def fake_solve_claude(self, task, container, output_dir, model, timeout,
                              operations, log, extra_metrics):
            (output_dir / "solver.json").write_text(usage_json, encoding="utf-8")
            return _parse_claude_json(usage_json, task.name, model or "", 1.0)

        monkeypatch.setattr(DockerSolverHarness, "_solve_claude", fake_solve_claude)


def test_docker_claude_run_folds_cost_into_metrics(tmp_path, monkeypatch):
    task = load_task(_fixture_task(tmp_path))
    _patch_pipeline(monkeypatch, reward=1.0, usage_json=_CLAUDE_JSON)
    harness = create_harness("docker-claude")
    result = harness.run(task, model="haiku", output_dir=tmp_path / "out")

    assert result.passed is True
    assert result.reward == 1.0
    assert result.metrics["cost_usd"] == 0.0731
    assert result.metrics["total_tokens"] == 6598
    assert result.metrics["mode"] == "claude"


def test_docker_oracle_run_has_no_llm_cost(tmp_path, monkeypatch):
    task = load_task(_fixture_task(tmp_path))
    _patch_pipeline(monkeypatch, reward=0.0, usage_json=None)
    result = create_harness("docker-oracle").run(task, output_dir=tmp_path / "out")
    assert result.passed is False
    assert "cost_usd" not in result.metrics  # oracle = no LLM telemetry


def test_dry_run_skips_docker(tmp_path):
    task = load_task(_fixture_task(tmp_path))
    result = create_harness("docker-claude").run(task, output_dir=tmp_path / "out", dry_run=True)
    assert result.metrics["dry_run"] is True
    assert result.passed is False


# ── summary rollup: cost, per-task, repeats ───────────────────────────────────


def test_summary_rolls_up_cost_and_per_task():
    rows = [
        {"task": "a", "harness": "skill", "passed": True, "elapsed_sec": 1.0, "reward": 1.0,
         "metrics": {"operation_count": 1, "operations_by_type": {"harness": 1},
                     "cost_usd": 0.05, "total_tokens": 100, "prompt_tokens": 80,
                     "completion_tokens": 20}},
        {"task": "a", "harness": "skill", "passed": False, "elapsed_sec": 1.0, "reward": 0.0,
         "metrics": {"operation_count": 1, "operations_by_type": {"harness": 1},
                     "cost_usd": 0.03, "total_tokens": 60, "prompt_tokens": 50,
                     "completion_tokens": 10}},
        {"task": "b", "harness": "skill", "passed": True, "elapsed_sec": 1.0, "reward": 1.0,
         "metrics": {"operation_count": 1, "operations_by_type": {"harness": 1},
                     "cost_usd": 0.02, "total_tokens": 40}},
    ]
    summary = summarize_task_results(rows, baseline_harness=None)
    stats = summary["per_harness"]["skill"]
    assert stats["cost"]["total_cost_usd"] == 0.1
    assert stats["cost"]["cost_known_n"] == 3
    assert stats["cost"]["total_tokens"] == 200
    # task "a" ran twice (1 pass), task "b" once (1 pass)
    assert stats["per_task"]["a"] == {"n": 2, "passed": 1, "pass_rate": 0.5}
    assert stats["per_task"]["b"] == {"n": 1, "passed": 1, "pass_rate": 1.0}


def test_summary_cost_delta_vs_baseline():
    rows = [
        {"task": "a", "harness": "noskill", "passed": False, "elapsed_sec": 1.0, "reward": 0.0,
         "metrics": {"operation_count": 0, "operations_by_type": {}, "cost_usd": 0.04}},
        {"task": "a", "harness": "skill", "passed": True, "elapsed_sec": 1.0, "reward": 1.0,
         "metrics": {"operation_count": 0, "operations_by_type": {}, "cost_usd": 0.10}},
    ]
    summary = summarize_task_results(rows, baseline_harness="noskill")
    cmp = summary["comparisons"]["skill"]
    assert cmp["pass_rate_delta"] == 1.0
    assert cmp["cost_delta_usd"] == 0.06


def test_summary_cost_null_when_no_pricing():
    rows = [
        {"task": "a", "harness": "h", "passed": True, "elapsed_sec": 1.0, "reward": 1.0,
         "metrics": {"operation_count": 0, "operations_by_type": {}}},
    ]
    stats = summarize_task_results(rows)["per_harness"]["h"]
    assert stats["cost"]["total_cost_usd"] is None
    assert stats["cost"]["cost_known_n"] == 0


def test_repeats_produce_multiple_rows_and_validate(tmp_path, monkeypatch):
    task = load_task(_fixture_task(tmp_path))
    _patch_pipeline(monkeypatch, reward=1.0, usage_json=_CLAUDE_JSON)
    suite = TaskSuiteRunner(
        tasks=[task],
        harnesses=["docker-claude"],
        model="haiku",
        output_root=tmp_path / "runs",
        repeats=3,
    )
    output = suite.run()
    validate_artifact("task_runs", output)
    assert output["repeats"] == 3
    assert len(output["results"]) == 3
    assert {r["repeat"] for r in output["results"]} == {1, 2, 3}
    stats = output["summary"]["per_harness"]["docker-claude"]
    assert stats["n"] == 3
    assert stats["cost"]["cost_known_n"] == 3


def test_one_failing_cell_does_not_abort_the_sweep(tmp_path, monkeypatch):
    """A harness crash on one task records a failed row and the sweep continues
    — the artifact still holds every other cell instead of being discarded."""
    good = _fixture_task(tmp_path)
    bad = tmp_path / "intel-perf-bad"
    (bad / "tests").mkdir(parents=True)
    (bad / "environment").mkdir()
    (bad / "instruction.md").write_text("x", encoding="utf-8")
    (bad / "task.toml").write_text('[metadata]\ntags = []\n', encoding="utf-8")

    from agent_benchmarks.harnesses.command import CommandHarness

    real_run = DockerSolverHarness.run

    def flaky_run(self, task, *, model=None, output_dir=None, timeout_sec=None, dry_run=False):
        if task.name == "intel-perf-bad":
            raise RuntimeError("docker build failed (exit 1); see run.log")
        # The good task: stub the Docker pipeline and run the real method.
        _patch_pipeline(monkeypatch, reward=1.0, usage_json=_CLAUDE_JSON)
        return real_run(self, task, model=model, output_dir=output_dir, dry_run=dry_run)

    monkeypatch.setattr(DockerSolverHarness, "run", flaky_run)
    suite = TaskSuiteRunner(
        tasks=[load_task(bad), load_task(good)],
        harnesses=["docker-claude"],
        model="haiku",
        output_root=tmp_path / "runs",
    )
    output = suite.run()

    validate_artifact("task_runs", output)
    assert len(output["results"]) == 2  # both cells present, sweep survived
    rows = {r["task"]: r for r in output["results"]}
    assert rows["intel-perf-bad"]["passed"] is False
    assert rows["intel-perf-bad"]["reward"] is None  # no verdict, not a verified 0
    assert "docker build failed" in rows["intel-perf-bad"]["metrics"]["error"]
    assert rows["intel-perf-toy"]["passed"] is True
    assert CommandHarness  # keep import for the patched module path


def test_recompile_failure_recorded_in_metrics(tmp_path, monkeypatch):
    """A failed in-container recompile is surfaced in metrics so the cell can be
    told apart from a genuine model miss (it is a tooling failure)."""
    task = load_task(_fixture_task(tmp_path))  # instruction has a `g++ ... -o /app/bench`
    import agent_benchmarks.harnesses.docker_solver as mod

    monkeypatch.setattr(mod, "_docker", lambda *a, **k: None)
    monkeypatch.setattr(DockerSolverHarness, "_build_image", lambda self, t, i, log: None)
    monkeypatch.setattr(DockerSolverHarness, "_start_container", lambda self, i, c, log: None)
    monkeypatch.setattr(DockerSolverHarness, "_verify", lambda self, t, c, o, log: 0.0)

    # Snapshot copy-out and the claude subprocess are stubbed; recompile "fails".
    monkeypatch.setattr(DockerSolverHarness, "_recompile",
                        lambda self, t, c, log: ["g++ -O3 bench.cpp -o /app/bench"])

    def fake_solve(self, task, container, output_dir, model, timeout, operations, log, extra_metrics):
        failed = self._recompile(task, container, log)
        if failed:
            extra_metrics["recompile_failed"] = failed
        return _parse_claude_json(_CLAUDE_JSON, task.name, model or "", 1.0)

    monkeypatch.setattr(DockerSolverHarness, "_solve_claude", fake_solve)
    result = create_harness("docker-claude").run(task, model="haiku", output_dir=tmp_path / "out")
    assert result.metrics["recompile_failed"] == ["g++ -O3 bench.cpp -o /app/bench"]
    assert result.passed is False
