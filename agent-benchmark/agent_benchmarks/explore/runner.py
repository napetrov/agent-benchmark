"""ExploreBench suite runner (BACKLOG #60, ADR §3.4).

Runs each exploration task through one or more *arms* (explorers), parses the
``<final_answer>`` block each returns, scores it against the task's reference
locations with :func:`score_localization`, and emits an ``explore_runs.v1``
artifact with per-arm rollups and baseline deltas.

Each run also records a ``subagent`` operation (the ADR §3.3 telemetry shape) so
the result is consumable by the same exploration-metrics layer as the executable
task track.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent_benchmarks.metrics.exploration import parse_final_answer, score_localization

from .explorer import Explorer, ExplorerResult, build_subagent_op
from .tasks import ExploreTask

# An arm builds an explorer for a given task (so an oracle arm can cite that
# task's references, while a command arm ignores the task).
ArmFactory = Callable[[ExploreTask], Explorer]


@dataclass
class ExploreRunner:
    """Run exploration tasks through named explorer arms."""

    tasks: list[ExploreTask]
    arms: dict[str, ArmFactory]
    model: str | None = None
    baseline_arm: str | None = None
    output_root: Path = Path("results/explore-runs")
    _clock: Callable[[], float] = field(default=time.time, repr=False)

    def run(self) -> dict[str, Any]:
        generated_at = (
            datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        )
        rows: list[dict[str, Any]] = []
        for task in self.tasks:
            reference = task.reference_locations()
            for arm, factory in self.arms.items():
                explorer = factory(task)
                start = self._clock()
                result = explorer.explore(task.query, repo_root=task.repo_root)
                elapsed = result.elapsed_sec or (self._clock() - start)
                rows.append(self._row(task, arm, result, reference, elapsed))

        summary = summarize_explore_results(rows, baseline_arm=self.baseline_arm)
        return {
            "schema_version": "explore_runs.v1",
            "generated_at": generated_at,
            "model": self.model,
            "baseline_arm": self.baseline_arm,
            "arms": list(self.arms.keys()),
            "tasks": [t.as_dict() for t in self.tasks],
            "results": rows,
            "summary": summary,
        }

    def _row(
        self,
        task: ExploreTask,
        arm: str,
        result: ExplorerResult,
        reference,
        elapsed: float,
    ) -> dict[str, Any]:
        cset = parse_final_answer(result.final_answer)
        score = score_localization(cset, reference)
        subagent_op = build_subagent_op(
            arm,
            cset,
            elapsed_sec=elapsed,
            status="ok" if result.returncode == 0 else "error",
        )
        operations = [op.as_dict() for op in (*result.operations, subagent_op)]
        return {
            "task": task.id,
            "arm": arm,
            "model": self.model,
            "final_answer": result.final_answer,
            "citations": [
                {"path": c.path, "start": c.start, "end": c.end} for c in cset.citations
            ],
            "score": score.as_dict(),
            "elapsed_sec": round(elapsed, 4),
            "metrics": {
                "citation_count": len(cset.citations),
                "malformed_count": len(cset.malformed),
                "overlapping_citations": cset.overlapping,
                "returncode": result.returncode,
            },
            "operations": operations,
        }


def summarize_explore_results(
    rows: list[dict[str, Any]], *, baseline_arm: str | None = None
) -> dict[str, Any]:
    per_arm: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["arm"], []).append(row)

    for arm, arm_rows in grouped.items():
        per_arm[arm] = {
            "n": len(arm_rows),
            "avg_file_f1": _avg(arm_rows, "file_f1"),
            "avg_line_f1": _avg(arm_rows, "line_f1"),
            "avg_citation_validity_rate": _avg(arm_rows, "citation_validity_rate"),
            "avg_citation_compactness": _avg(arm_rows, "citation_compactness"),
        }

    comparisons: dict[str, dict[str, Any]] = {}
    if baseline_arm and baseline_arm in per_arm:
        base = per_arm[baseline_arm]
        for arm, stats in per_arm.items():
            if arm == baseline_arm:
                continue
            comparisons[arm] = {
                "baseline_arm": baseline_arm,
                "file_f1_delta": _delta(stats["avg_file_f1"], base["avg_file_f1"]),
                "line_f1_delta": _delta(stats["avg_line_f1"], base["avg_line_f1"]),
            }

    return {"per_arm": per_arm, "comparisons": comparisons}


def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [
        row["score"].get(key)
        for row in rows
        if row["score"].get(key) is not None
    ]
    return round(sum(values) / len(values), 4) if values else None


def _delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return round(a - b, 4)
