"""Shared data models for coding-task harness runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OperationRecord:
    """One observed harness operation.

    External coding agents expose different logs. This model is deliberately
    generic: adapters can record stable operations they control and may also
    ingest structured events emitted by wrappers or agents.
    """

    type: str
    name: str
    status: str = "ok"
    elapsed_sec: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "status": self.status,
            "elapsed_sec": round(self.elapsed_sec, 4),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class HarnessResult:
    """Raw outcome returned by a harness adapter for one task."""

    harness: str
    task: str
    command: list[str]
    returncode: int
    elapsed_sec: float
    reward: float | None
    passed: bool
    stdout_tail: str = ""
    stderr_tail: str = ""
    output_dir: str | None = None
    operations: list[OperationRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        operations = [op.as_dict() for op in self.operations]
        metrics = dict(self.metrics)
        metrics.setdefault("operation_count", len(operations))
        metrics.setdefault("operations_by_type", operations_by_type(operations))
        exploration = _exploration_metrics(self.operations, metrics)
        if exploration is not None:
            metrics.setdefault("exploration_metrics", exploration)
        return {
            "task": self.task,
            "harness": self.harness,
            "command": self.command,
            "returncode": self.returncode,
            "elapsed_sec": round(self.elapsed_sec, 4),
            "reward": self.reward,
            "passed": self.passed,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "output_dir": self.output_dir,
            "operations": operations,
            "metrics": metrics,
        }


@dataclass(frozen=True)
class TaskRunResult:
    """Public row emitted by ``tasks run``."""

    task: str
    harness: str
    model: str | None
    result: HarnessResult

    def as_dict(self) -> dict[str, Any]:
        row = self.result.as_dict()
        row["model"] = self.model
        return row


def operations_by_type(operations: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for op in operations:
        op_type = str(op.get("type") or "unknown")
        counts[op_type] = counts.get(op_type, 0) + 1
    return counts


def _exploration_metrics(
    operations: list[OperationRecord], metrics: dict[str, Any]
) -> dict[str, Any] | None:
    """Derive the optional ``exploration_metrics`` block (BACKLOG #60).

    Imported lazily to keep this lightweight model module free of a hard
    dependency on the exploration summarizer.
    """
    from .exploration import summarize_exploration

    main_tokens = metrics.get("total_tokens")
    return summarize_exploration(
        operations, main_tokens=int(main_tokens) if main_tokens else None
    )
