"""ExploreBench: the standalone exploration-quality track (BACKLOG #60).

Scores whether an agent can *locate* the right files and line ranges for a task
(file:line citations vs. reference locations), independent of whether it can use
them to answer or solve. See ``docs/decisions/2026-06-23-exploration-quality-
fastcontext.md``.
"""

from .explorer import CommandExplorer, Explorer, ExplorerResult, StaticExplorer
from .runner import ExploreRunner, summarize_explore_results
from .tasks import (
    ExploreReference,
    ExploreTask,
    discover_explore_tasks,
    load_explore_task,
)

__all__ = [
    "CommandExplorer",
    "Explorer",
    "ExplorerResult",
    "ExploreReference",
    "ExploreRunner",
    "ExploreTask",
    "StaticExplorer",
    "discover_explore_tasks",
    "load_explore_task",
    "summarize_explore_results",
]
