"""Coding harness adapters for executable task evaluation."""

from .docker_solver import DockerSolverHarness
from .models import HarnessResult, OperationRecord, TaskRunResult
from .registry import create_harness, known_harnesses
from .runner import TaskSuiteRunner, summarize_task_results
from .tasks import TaskSpec, discover_tasks, load_task

__all__ = [
    "DockerSolverHarness",
    "HarnessResult",
    "OperationRecord",
    "TaskRunResult",
    "TaskSuiteRunner",
    "TaskSpec",
    "create_harness",
    "discover_tasks",
    "known_harnesses",
    "load_task",
    "summarize_task_results",
]
