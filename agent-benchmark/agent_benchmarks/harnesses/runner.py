"""Suite runner and summary logic for executable coding tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import HarnessResult, OperationRecord, TaskRunResult
from .registry import create_harness
from .tasks import TaskSpec


@dataclass
class TaskSuiteRunner:
    """Run a set of tasks through one or more harnesses.

    ``repeats`` runs every ``(task, harness)`` cell N times so pass-rate and
    cost carry variance (each repeat is a separate ``results[]`` row with a
    ``repeat`` index). N=1 reproduces the original single-shot behavior.
    """

    tasks: list[TaskSpec]
    harnesses: list[str]
    model: str | None = None
    baseline_harness: str | None = None
    output_root: Path = Path("results/task-runs")
    command_template: str | None = None
    dry_run: bool = False
    repeats: int = 1

    def run(self) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        rows: list[dict[str, Any]] = []
        repeats = max(1, self.repeats)
        for task in self.tasks:
            for harness_id in self.harnesses:
                for rep in range(1, repeats + 1):
                    harness = create_harness(harness_id, command_template=self.command_template)
                    output_dir = self.output_root / task.name / _safe_id(harness_id)
                    if repeats > 1:
                        output_dir = output_dir / f"run{rep}"
                    # Isolate each cell: a harness crash (docker build/exec error,
                    # bad config) must not abort the whole sweep and discard every
                    # completed cell — record it as a failed row and continue.
                    try:
                        result = harness.run(
                            task,
                            model=self.model,
                            output_dir=output_dir,
                            dry_run=self.dry_run,
                        )
                    except Exception as exc:  # noqa: BLE001 — one bad cell ≠ dead sweep
                        result = _error_result(harness_id, task, output_dir, exc)
                    row = TaskRunResult(task.name, harness_id, self.model, result).as_dict()
                    if repeats > 1:
                        row["repeat"] = rep
                    rows.append(row)

        summary = summarize_task_results(rows, baseline_harness=self.baseline_harness)
        return {
            "schema_version": "task_runs.v1",
            "generated_at": generated_at,
            "model": self.model,
            "baseline_harness": self.baseline_harness,
            "harnesses": self.harnesses,
            "repeats": repeats,
            "tasks": [task.as_dict() for task in self.tasks],
            "results": rows,
            "summary": summary,
        }


_COST_KEYS = (
    "cost_usd", "prompt_tokens", "completion_tokens", "total_tokens",
    "cache_read_tokens", "cache_write_tokens",
)


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
                # telemetry accumulators (LLM-backed harnesses only)
                "_cost_sum": 0.0,
                "_cost_known": 0,
                "_tokens": {k: 0 for k in _COST_KEYS if k != "cost_usd"},
                "_by_task": {},   # task -> {"n", "passed"}
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
        # Cost/token telemetry (present when an LLM harness emitted a UsageRecord).
        cost = metrics.get("cost_usd")
        if isinstance(cost, (int, float)):
            stats["_cost_sum"] += float(cost)
            stats["_cost_known"] += 1
        for key in stats["_tokens"]:
            val = metrics.get(key)
            if isinstance(val, (int, float)):
                stats["_tokens"][key] += int(val)
        # Per-task breakdown (which tasks the harness solves).
        task = row.get("task")
        if task is not None:
            bucket = stats["_by_task"].setdefault(task, {"n": 0, "passed": 0})
            bucket["n"] += 1
            bucket["passed"] += 1 if row.get("passed") else 0

    for stats in per_harness.values():
        stats["pass_rate"] = round(stats["passed"] / stats["n"], 4) if stats["n"] else None
        stats["avg_reward"] = (
            round(stats["reward_sum"] / stats["reward_n"], 4) if stats["reward_n"] else None
        )
        stats["elapsed_sec"] = round(stats["elapsed_sec"], 4)
        del stats["reward_sum"]
        del stats["reward_n"]
        # Finalize telemetry: only surface cost when at least one call was priced.
        cost_known = stats.pop("_cost_known")
        cost_sum = stats.pop("_cost_sum")
        tokens = stats.pop("_tokens")
        stats["cost"] = {
            "total_cost_usd": round(cost_sum, 6) if cost_known else None,
            "cost_known_n": cost_known,
            **tokens,
        }
        by_task = stats.pop("_by_task")
        stats["per_task"] = {
            t: {"n": v["n"], "passed": v["passed"],
                "pass_rate": round(v["passed"] / v["n"], 4) if v["n"] else None}
            for t, v in sorted(by_task.items())
        }

    comparisons: dict[str, dict[str, Any]] = {}
    if baseline_harness and baseline_harness in per_harness:
        base = per_harness[baseline_harness]
        base_pass = base.get("pass_rate")
        for harness, stats in per_harness.items():
            if harness == baseline_harness:
                continue
            pass_rate = stats.get("pass_rate")
            base_cost = base["cost"].get("total_cost_usd")
            arm_cost = stats["cost"].get("total_cost_usd")
            comparisons[harness] = {
                "baseline_harness": baseline_harness,
                "pass_rate_delta": (
                    round(pass_rate - base_pass, 4)
                    if isinstance(pass_rate, float) and isinstance(base_pass, float)
                    else None
                ),
                "passed_delta": stats.get("passed", 0) - base.get("passed", 0),
                "operation_count_delta": stats.get("operation_count", 0) - base.get("operation_count", 0),
                "cost_delta_usd": (
                    round(arm_cost - base_cost, 6)
                    if isinstance(arm_cost, (int, float)) and isinstance(base_cost, (int, float))
                    else None
                ),
            }

    return {"per_harness": per_harness, "comparisons": comparisons}


def _error_result(harness_id: str, task: TaskSpec, output_dir: Path, exc: Exception) -> HarnessResult:
    """Build a failed result for a cell whose harness raised, so the sweep
    survives. ``reward`` is ``None`` (the cell did not produce a verdict —
    distinct from a verified 0), and ``metrics.error`` carries the cause."""
    return HarnessResult(
        harness=harness_id,
        task=task.name,
        command=[],
        returncode=1,
        elapsed_sec=0.0,
        reward=None,
        passed=False,
        stderr_tail=f"{type(exc).__name__}: {exc}",
        output_dir=str(output_dir),
        operations=[OperationRecord(type="harness", name=harness_id, status="error",
                                    metadata={"task": task.name})],
        metrics={"error": f"{type(exc).__name__}: {exc}"},
    )


def _safe_id(value: str) -> str:
    return value.replace("/", "_").replace(":", "_").replace(" ", "_")
