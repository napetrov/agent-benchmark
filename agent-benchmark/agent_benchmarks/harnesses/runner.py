"""Suite runner and summary logic for executable coding tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import TaskRunResult
from .registry import create_harness
from .tasks import TaskSpec


@dataclass
class TaskSuiteRunner:
    """Run a set of tasks through one or more harnesses."""

    tasks: list[TaskSpec]
    harnesses: list[str]
    model: str | None = None
    baseline_harness: str | None = None
    output_root: Path = Path("results/task-runs")
    command_template: str | None = None
    dry_run: bool = False

    def run(self) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        rows: list[dict[str, Any]] = []
        for task in self.tasks:
            for harness_id in self.harnesses:
                harness = create_harness(harness_id, command_template=self.command_template)
                output_dir = self.output_root / task.name / _safe_id(harness_id)
                result = harness.run(
                    task,
                    model=self.model,
                    output_dir=output_dir,
                    dry_run=self.dry_run,
                )
                rows.append(TaskRunResult(task.name, harness_id, self.model, result).as_dict())

        summary = summarize_task_results(rows, baseline_harness=self.baseline_harness)
        return {
            "schema_version": "task_runs.v1",
            "generated_at": generated_at,
            "model": self.model,
            "baseline_harness": self.baseline_harness,
            "harnesses": self.harnesses,
            "tasks": [task.as_dict() for task in self.tasks],
            "results": rows,
            "summary": summary,
        }


def summarize_task_results(
    rows: list[dict[str, Any]],
    *,
    baseline_harness: str | None = None,
) -> dict[str, Any]:
    per_harness: dict[str, dict[str, Any]] = {}
    for row in rows:
        harness = row["harness"]
        stats = per_harness.setdefault(
            harness,
            {
                "n": 0,
                "passed": 0,
                "reward_sum": 0.0,
                "reward_n": 0,
                "elapsed_sec": 0.0,
                "operation_count": 0,
                "operations_by_type": {},
            },
        )
        stats["n"] += 1
        stats["passed"] += 1 if row.get("passed") else 0
        reward = row.get("reward")
        if isinstance(reward, (int, float)):
            stats["reward_sum"] += float(reward)
            stats["reward_n"] += 1
        stats["elapsed_sec"] += float(row.get("elapsed_sec") or 0.0)
        metrics = row.get("metrics", {})
        stats["operation_count"] += int(metrics.get("operation_count") or 0)
        for op_type, count in metrics.get("operations_by_type", {}).items():
            stats["operations_by_type"][op_type] = stats["operations_by_type"].get(op_type, 0) + count

    for stats in per_harness.values():
        stats["pass_rate"] = round(stats["passed"] / stats["n"], 4) if stats["n"] else None
        stats["avg_reward"] = (
            round(stats["reward_sum"] / stats["reward_n"], 4) if stats["reward_n"] else None
        )
        stats["elapsed_sec"] = round(stats["elapsed_sec"], 4)
        del stats["reward_sum"]
        del stats["reward_n"]

    comparisons: dict[str, dict[str, Any]] = {}
    if baseline_harness and baseline_harness in per_harness:
        base = per_harness[baseline_harness]
        base_pass = base.get("pass_rate")
        for harness, stats in per_harness.items():
            if harness == baseline_harness:
                continue
            pass_rate = stats.get("pass_rate")
            comparisons[harness] = {
                "baseline_harness": baseline_harness,
                "pass_rate_delta": (
                    round(pass_rate - base_pass, 4)
                    if isinstance(pass_rate, float) and isinstance(base_pass, float)
                    else None
                ),
                "passed_delta": stats.get("passed", 0) - base.get("passed", 0),
                "operation_count_delta": stats.get("operation_count", 0) - base.get("operation_count", 0),
            }

    return {"per_harness": per_harness, "comparisons": comparisons}


def _safe_id(value: str) -> str:
    return value.replace("/", "_").replace(":", "_").replace(" ", "_")
