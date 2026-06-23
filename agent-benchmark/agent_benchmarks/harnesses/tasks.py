"""Terminal-bench task discovery and metadata loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_ROOT = REPO_ROOT / "terminal-bench-tasks"


@dataclass(frozen=True)
class TaskSpec:
    """Resolved terminal-bench task descriptor."""

    name: str
    path: Path
    instruction: str
    metadata: dict[str, Any] = field(default_factory=dict)
    verifier: dict[str, Any] = field(default_factory=dict)
    agent: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)

    @property
    def timeout_sec(self) -> float | None:
        value = self.agent.get("timeout_sec")
        return float(value) if value is not None else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "metadata": self.metadata,
            "verifier": self.verifier,
            "agent": self.agent,
            "environment": self.environment,
        }


def discover_tasks(root: Path | None = None) -> list[TaskSpec]:
    """Load every task directory under ``terminal-bench-tasks``."""

    root = Path(root or TASKS_ROOT)
    if not root.is_dir():
        return []
    return [load_task(path) for path in sorted(root.iterdir()) if (path / "task.toml").is_file()]


def load_task(path_or_name: str | Path, root: Path | None = None) -> TaskSpec:
    """Load one task by directory path or task name."""

    root = Path(root or TASKS_ROOT)
    path = Path(path_or_name)
    if not path.exists():
        path = root / str(path_or_name)
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"Task directory not found: {path_or_name}")

    toml_path = path / "task.toml"
    instruction_path = path / "instruction.md"
    if not toml_path.is_file():
        raise FileNotFoundError(f"Task has no task.toml: {path}")
    if not instruction_path.is_file():
        raise FileNotFoundError(f"Task has no instruction.md: {path}")

    data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
    metadata = _table(data.get("metadata"))
    verifier = _table(data.get("verifier"))
    agent = _table(data.get("agent"))
    environment = _table(data.get("environment"))
    return TaskSpec(
        name=path.name,
        path=path,
        instruction=instruction_path.read_text(encoding="utf-8"),
        metadata=metadata,
        verifier=verifier,
        agent=agent,
        environment=environment,
    )


def _table(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
