"""ExploreBench task discovery (BACKLOG #60, ADR §3.4).

An exploration task poses a localization question over a repository/doc tree and
declares the reference locations a good explorer should cite. Tasks are small
YAML files::

    id: onetbb_flow_graph_locate_buffering
    product: oneTBB
    query: "Find the docs and example code for a bounded flow-graph pipeline."
    repo_root: .            # optional; defaults to the agent-benchmark repo
    references:
      - path: docs/flow_graph.md
        lines: [120, 180]
      - path: examples/pipeline.cpp     # whole-file reference (no lines)

Reference ``lines`` are inclusive ``[start, end]`` (or a single ``[n]``); a
missing/empty ``lines`` is a whole-file reference that scores at file
granularity only. This module is pure metadata loading — it neither runs an
explorer nor reads the referenced files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agent_benchmarks.metrics.exploration import ReferenceLocations, normalize_path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPLORE_TASKS_ROOT = REPO_ROOT / "data" / "explore_tasks"


@dataclass(frozen=True)
class ExploreReference:
    """One ground-truth location: a path and an optional inclusive line range."""

    path: str
    lines: tuple[int, int] | None = None

    def as_dict(self) -> dict:
        return {"path": self.path, "lines": list(self.lines) if self.lines else None}


@dataclass(frozen=True)
class ExploreTask:
    """A resolved exploration task."""

    id: str
    product: str
    query: str
    references: tuple[ExploreReference, ...]
    path: Path
    repo_root: Path = REPO_ROOT
    metadata: dict = field(default_factory=dict)

    def reference_locations(self) -> ReferenceLocations:
        """Build the scorer's :class:`ReferenceLocations` from the references."""
        files: dict[str, tuple[tuple[int, int], ...]] = {}
        for ref in self.references:
            key = normalize_path(ref.path)
            ranges = files.get(key, ())
            if ref.lines is not None:
                ranges = ranges + (ref.lines,)
            files[key] = ranges
        return ReferenceLocations(files=files)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "product": self.product,
            "query": self.query,
            "references": [r.as_dict() for r in self.references],
        }


def _parse_lines(value) -> tuple[int, int] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"'lines' must be [start, end] or [n], got {value!r}")
    nums = [int(v) for v in value]
    start = nums[0]
    end = nums[1] if len(nums) > 1 else nums[0]
    return (min(start, end), max(start, end))


def _task_from_data(data: dict, path: Path) -> ExploreTask:
    missing = [k for k in ("id", "query", "references") if k not in data]
    if missing:
        raise ValueError(f"Explore task {path} missing required field(s): {missing}")
    references = tuple(
        ExploreReference(path=str(ref["path"]), lines=_parse_lines(ref.get("lines")))
        for ref in data["references"]
    )
    if not references:
        raise ValueError(f"Explore task {path} has no references")
    repo_root = data.get("repo_root")
    resolved_root = (path.parent / repo_root).resolve() if repo_root else REPO_ROOT
    known = {"id", "product", "query", "references", "repo_root"}
    return ExploreTask(
        id=str(data["id"]),
        product=str(data.get("product", "unknown")),
        query=str(data["query"]),
        references=references,
        path=path,
        repo_root=resolved_root,
        metadata={k: v for k, v in data.items() if k not in known},
    )


def load_explore_task(ref: str, root: Path | None = None) -> ExploreTask:
    """Load one task by id (or path) from the explore-tasks root."""
    root = Path(root or EXPLORE_TASKS_ROOT)
    candidate = Path(ref)
    if candidate.is_file():
        path = candidate
    else:
        matches = [p for p in _task_files(root) if p.stem == ref]
        if not matches:
            raise FileNotFoundError(f"Explore task not found: {ref!r} under {root}")
        path = matches[0]
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _task_from_data(data, path)


def discover_explore_tasks(root: Path | None = None) -> list[ExploreTask]:
    """Load every exploration task under the explore-tasks root, sorted by id."""
    root = Path(root or EXPLORE_TASKS_ROOT)
    tasks = []
    for path in _task_files(root):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tasks.append(_task_from_data(data, path))
    return sorted(tasks, key=lambda t: t.id)


def _task_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.yaml") if p.is_file())
