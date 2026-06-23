"""CLI coverage for executable task runs."""

from __future__ import annotations

from pathlib import Path

from agent_benchmarks.cli import build_parser


def _fixture_task(tmp_path: Path) -> Path:
    task = tmp_path / "toy-task"
    task.mkdir()
    (task / "instruction.md").write_text("Do it.", encoding="utf-8")
    (task / "task.toml").write_text("[metadata]\ntags = [\"toy\"]\n", encoding="utf-8")
    return task


def test_tasks_run_dry_run_writes_schema_artifact(tmp_path):
    _fixture_task(tmp_path)
    out = tmp_path / "runs.json"
    parser = build_parser()
    args = parser.parse_args([
        "tasks",
        "run",
        "--tasks",
        "toy-task",
        "--tasks-root",
        str(tmp_path),
        "--harnesses",
        "codex",
        "--baseline-harness",
        "claude-code",
        "--model",
        "m",
        "--out-json",
        str(out),
        "--dry-run",
    ])
    args.func(args)
    text = out.read_text(encoding="utf-8")
    assert '"schema_version": "task_runs.v1"' in text
    assert '"codex"' in text
    assert '"claude-code"' in text
