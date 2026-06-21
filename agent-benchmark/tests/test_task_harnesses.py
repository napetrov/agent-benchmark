"""Tests for executable coding-task harness support."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_benchmarks.artifacts import validate_artifact
from agent_benchmarks.harnesses import TaskSuiteRunner, load_task
from agent_benchmarks.harnesses.command import CommandHarness
from agent_benchmarks.harnesses.operations import load_operations
from agent_benchmarks.harnesses.registry import create_harness, known_harnesses
from agent_benchmarks.harnesses.runner import summarize_task_results


def _fixture_task(tmp_path: Path) -> Path:
    task = tmp_path / "toy-task"
    (task / "tests").mkdir(parents=True)
    (task / "environment").mkdir()
    (task / "solution").mkdir()
    (task / "instruction.md").write_text("Write solution.py and pass tests.", encoding="utf-8")
    (task / "task.toml").write_text(
        """
[metadata]
difficulty = "easy"
tags = ["toy", "python"]

[agent]
timeout_sec = 12

[verifier]
timeout_sec = 3

[environment]
docker_image = "toy:latest"
allow_internet = false
""",
        encoding="utf-8",
    )
    return task


def test_task_loader_reads_terminal_bench_metadata(tmp_path):
    task = load_task(_fixture_task(tmp_path))
    assert task.name == "toy-task"
    assert task.timeout_sec == 12
    assert task.metadata["tags"] == ["toy", "python"]
    assert "Write solution.py" in task.instruction


def test_known_harness_aliases_render_harbor_commands(tmp_path):
    task = load_task(_fixture_task(tmp_path))
    harness = create_harness("codex")
    cmd = harness.build_command(task, model="gpt-5", output_dir=tmp_path / "out")
    assert cmd[:2] == ["harbor", "run"]
    assert "codex" in cmd
    assert "gpt-5" in cmd
    assert "codex" in known_harnesses()


def test_command_harness_id_includes_template_to_avoid_collisions():
    first = create_harness("command:echo {task}")
    second = create_harness("command:cat {task_path}")
    assert first.harness_id == "command:echo {task}"
    assert second.harness_id == "command:cat {task_path}"


def test_command_template_allows_code_braces_in_template_and_prompt(tmp_path):
    task_path = _fixture_task(tmp_path)
    (task_path / "instruction.md").write_text(
        'Write {"ok": true} into config.py and keep f"{value}" intact.',
        encoding="utf-8",
    )
    task = load_task(task_path)

    literal = CommandHarness("fake", "echo {'literal':1} {task}")
    assert literal.build_command(task, model=None, output_dir=tmp_path / "out") == [
        "echo",
        "{literal:1}",
        "toy-task",
    ]

    prompt = CommandHarness("fake", "echo {prompt_quoted}")
    rendered_prompt = " ".join(prompt.build_command(task, model=None, output_dir=tmp_path / "out"))
    assert '{"ok": true}' in rendered_prompt
    assert 'f"{value}"' in rendered_prompt


def test_command_harness_collects_reward_and_operations(tmp_path, monkeypatch):
    task = load_task(_fixture_task(tmp_path))
    out_dir = tmp_path / "out"

    def fake_run(command, cwd, env, text, capture_output, timeout, check):
        Path(env["AGENT_BENCHMARK_OPERATIONS_FILE"]).write_text(
            json.dumps({"type": "tool", "name": "edit", "elapsed_sec": 0.25}) + "\n",
            encoding="utf-8",
        )
        reward_dir = Path(env["AGENT_BENCHMARK_OUTPUT_DIR"]) / "logs" / "verifier"
        reward_dir.mkdir(parents=True)
        (reward_dir / "reward.txt").write_text("1.0", encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='AGENT_BENCHMARK_OP {"type":"loop","name":"turn","elapsed_sec":0.1}\n',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    harness = CommandHarness("fake", "fake-agent --task {task_path} --model {model}")
    result = harness.run(task, model="m", output_dir=out_dir)

    assert result.passed is True
    assert result.reward == 1.0
    assert result.metrics["stdout_bytes"] > 0
    by_type = result.as_dict()["metrics"]["operations_by_type"]
    assert by_type["harness"] == 1
    assert by_type["tool"] == 1
    assert by_type["loop"] == 1


def test_operation_loader_accepts_markers_and_unstructured_lines(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "operations.jsonl").write_text(
        json.dumps({"type": "subagent", "name": "reviewer"}) + "\n",
        encoding="utf-8",
    )
    ops = load_operations(
        out,
        'AGENT_BENCHMARK_OP {"type":"tool","name":"search"}\nloop 1 done',
        "",
    )
    assert [op.type for op in ops] == ["subagent", "tool", "loop"]


def test_operation_loader_reports_unreadable_jsonl(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    log = out / "operations.jsonl"
    log.write_text("{}", encoding="utf-8")

    def fail_read_text(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(Path, "read_text", fail_read_text)
    ops = load_operations(out, "", "")
    assert ops[0].type == "log_parse_error"
    assert ops[0].status == "error"
    assert "boom" in ops[0].metadata["error"]


def test_task_suite_summary_compares_to_baseline(tmp_path, monkeypatch):
    task = load_task(_fixture_task(tmp_path))

    def fake_run(self, task, *, model=None, output_dir=None, timeout_sec=None, dry_run=False):
        from agent_benchmarks.harnesses.models import HarnessResult, OperationRecord

        passed = self.harness_id == "candidate"
        return HarnessResult(
            harness=self.harness_id,
            task=task.name,
            command=["fake"],
            returncode=0 if passed else 1,
            elapsed_sec=1.0,
            reward=1.0 if passed else 0.0,
            passed=passed,
            operations=[OperationRecord("harness", self.harness_id)],
        )

    monkeypatch.setattr(CommandHarness, "run", fake_run)
    suite = TaskSuiteRunner(
        tasks=[task],
        harnesses=["baseline", "candidate"],
        baseline_harness="baseline",
        command_template="fake {task_path}",
        output_root=tmp_path / "runs",
    )
    output = suite.run()

    validate_artifact("task_runs", output)
    assert output["summary"]["per_harness"]["baseline"]["pass_rate"] == 0.0
    assert output["summary"]["per_harness"]["candidate"]["pass_rate"] == 1.0
    assert output["summary"]["comparisons"]["candidate"]["pass_rate_delta"] == 1.0


def test_summarize_task_results_counts_operations():
    rows = [
        {"harness": "h1", "passed": True, "elapsed_sec": 1, "metrics": {"operation_count": 2,
         "operations_by_type": {"tool": 1, "loop": 1}}},
        {"harness": "h1", "passed": False, "elapsed_sec": 2, "metrics": {"operation_count": 1,
         "operations_by_type": {"tool": 1}}},
    ]
    summary = summarize_task_results(rows)
    assert summary["per_harness"]["h1"]["pass_rate"] == 0.5
    assert summary["per_harness"]["h1"]["operations_by_type"] == {"tool": 2, "loop": 1}
