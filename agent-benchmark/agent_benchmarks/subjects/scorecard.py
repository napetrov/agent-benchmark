"""Build versioned per-subject scorecards."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .loader import awareness_arm_specs, work_arm_specs
from .models import SubjectDescriptor


def build_subject_scorecard(
    descriptor: SubjectDescriptor,
    *,
    awareness_runs: list[dict[str, Any]],
    out_dir: Path,
    work_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a subject_scorecard.v1 artifact from matrix rollup runs."""
    warnings: list[str] = []
    if descriptor.suite.tasks:
        if work_run is None:
            warnings.append(
                "task suites are declared but not executed; pass --work-harnesses "
                "or --skip-work to make the work status explicit"
            )
        else:
            warnings.extend(work_run.get("warnings", []))

    cells = []
    plugin_deltas = []
    for run in awareness_runs:
        rollup = run["rollup"]
        for cell in rollup.get("cells", []):
            cells.append({
                "product": run["product"],
                "questions": run["questions"],
                "matrix_cell": cell.get("matrix_cell"),
                "artifact": cell.get("artifact"),
                "model": cell.get("model"),
                "provider": cell.get("provider"),
                "harness": cell.get("harness"),
                "plugin_set": cell.get("plugin_set"),
                "summary": cell.get("summary", {}),
                "cost_summary": cell.get("cost_summary", {}),
            })
        for row in rollup.get("plugin_deltas", []):
            item = dict(row)
            item["product"] = run["product"]
            item["questions"] = run["questions"]
            plugin_deltas.append(item)
        warnings.extend(rollup.get("warnings", []))

    return {
        "schema_version": "subject_scorecard.v1",
        "generated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        "subject": {
            "id": descriptor.subject.id,
            "kind": descriptor.subject.kind,
            "ref": descriptor.subject.ref,
            "ref_digest": _digest_ref(descriptor.subject.ref, base=Path.cwd()),
            "members": [
                {
                    "kind": member.kind,
                    "ref": member.ref,
                    "ref_digest": _digest_ref(member.ref, base=Path.cwd()),
                }
                for member in descriptor.subject.members
            ],
        },
        "descriptor": str(descriptor.path),
        "suite": {
            "products": list(descriptor.suite.products),
            "questions": list(descriptor.suite.questions),
            "question_set_hash": _digest_values(descriptor.suite.questions),
            "tasks": list(descriptor.suite.tasks),
        },
        "baseline": descriptor.baseline,
        "baseline_digest": _digest_arm_spec(descriptor.baseline, base=Path.cwd()),
        "awareness": {
            "arm_specs": awareness_arm_specs(descriptor),
            "runs": [
                {
                    "product": run["product"],
                    "questions": run["questions"],
                    "matrix_rollup": run["matrix_rollup"],
                }
                for run in awareness_runs
            ],
        },
        "work": {
            "status": work_run.get("status", "not_run") if work_run else "not_run",
            "arm_specs": work_arm_specs(descriptor),
            "tasks": list(descriptor.suite.tasks),
            "harnesses": work_run.get("harnesses", []) if work_run else [],
            "task_runs": work_run.get("task_runs") if work_run else None,
            "task_report": work_run.get("task_report") if work_run else None,
            "summary": work_run.get("summary", {}) if work_run else {},
        },
        "cells": cells,
        "plugin_deltas": plugin_deltas,
        "run_manifest": {
            "out_dir": str(out_dir),
            "matrix_cells": len(descriptor.matrix_cells),
            "awareness_runs": len(awareness_runs),
        },
        "warnings": sorted(set(warnings)),
    }


def _digest_values(values: tuple[str, ...]) -> str:
    h = hashlib.sha256()
    for value in values:
        h.update(value.encode("utf-8"))
        h.update(b"\0")
        path = Path(value)
        if path.is_file():
            h.update(path.read_bytes())
    return "sha256:" + h.hexdigest()


def _digest_ref(ref: str | None, *, base: Path) -> str | None:
    if not ref:
        return None
    path = Path(ref.removeprefix("local:"))
    if not path.is_absolute():
        path = base / path
    h = hashlib.sha256()
    if path.is_file():
        h.update(path.read_bytes())
    elif path.is_dir():
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            h.update(str(child.relative_to(path)).encode("utf-8"))
            h.update(b"\0")
            h.update(child.read_bytes())
            h.update(b"\0")
    else:
        h.update(ref.encode("utf-8"))
    return "sha256:" + h.hexdigest()


def _digest_arm_spec(spec: str, *, base: Path) -> str:
    from agent_benchmarks.treatments.factory import _parse_combined_spec

    h = hashlib.sha256()
    h.update(spec.encode("utf-8"))
    h.update(b"\0")
    for part in _parse_combined_spec(spec):
        content_ref = _content_ref_for_arm_part(part.strip())
        if content_ref is None:
            continue
        h.update(part.strip().encode("utf-8"))
        h.update(b"\0")
        digest = _digest_ref(content_ref, base=base)
        h.update((digest or "").encode("utf-8"))
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def _content_ref_for_arm_part(part: str) -> str | None:
    for prefix in ("docs:", "agent:"):
        if part.startswith(prefix):
            ref = part.removeprefix(prefix)
            return ref if ref.startswith("local:") else None
    for prefix in ("profile:", "skill:", "skill-agent:"):
        if part.startswith(prefix):
            return part.removeprefix(prefix)
    return None
