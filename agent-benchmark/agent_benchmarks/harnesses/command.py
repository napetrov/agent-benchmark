"""Command-backed coding harness adapters."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import HarnessResult, OperationRecord
from .operations import load_operations
from .tasks import TaskSpec


_REWARD_RE = re.compile(r"(?:reward|score|pass[_ -]?rate)\D+([01](?:\.\d+)?)", re.IGNORECASE)
_PLACEHOLDERS = (
    "harness",
    "task",
    "task_path",
    "instruction",
    "model",
    "output_dir",
    "prompt",
    "prompt_quoted",
)


@dataclass(frozen=True)
class CommandHarness:
    """Run a coding task through an external CLI command."""

    harness_id: str
    command_template: str
    kind: str = "command"
    default_timeout_sec: float | None = None
    env: dict[str, str] = field(default_factory=dict)

    def run(
        self,
        task: TaskSpec,
        *,
        model: str | None = None,
        output_dir: Path | None = None,
        timeout_sec: float | None = None,
        dry_run: bool = False,
    ) -> HarnessResult:
        output_dir = Path(output_dir) if output_dir else None
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)

        command = self.build_command(task, model=model, output_dir=output_dir)
        env = os.environ.copy()
        env.update(self.env)
        if output_dir:
            env["AGENT_BENCHMARK_OUTPUT_DIR"] = str(output_dir)
            env["AGENT_BENCHMARK_OPERATIONS_FILE"] = str(output_dir / "operations.jsonl")

        operations = [
            OperationRecord(
                type="harness",
                name=self.harness_id,
                metadata={"kind": self.kind, "task": task.name, "model": model},
            )
        ]
        start = time.time()
        if dry_run:
            elapsed = time.time() - start
            return HarnessResult(
                harness=self.harness_id,
                task=task.name,
                command=command,
                returncode=0,
                elapsed_sec=elapsed,
                reward=None,
                passed=False,
                output_dir=str(output_dir) if output_dir else None,
                operations=operations,
                metrics={"dry_run": True},
            )

        timeout = timeout_sec or task.timeout_sec or self.default_timeout_sec
        proc = subprocess.run(
            command,
            cwd=str(task.path.parent.parent),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        elapsed = time.time() - start
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        operations.extend(load_operations(output_dir, stdout, stderr))
        reward = _find_reward(output_dir, stdout, stderr)
        passed = reward is not None and reward >= 1.0
        if reward is None:
            passed = proc.returncode == 0

        metrics = {
            "dry_run": False,
            "timeout_sec": timeout,
            "stdout_bytes": len(stdout.encode("utf-8")),
            "stderr_bytes": len(stderr.encode("utf-8")),
        }
        return HarnessResult(
            harness=self.harness_id,
            task=task.name,
            command=command,
            returncode=proc.returncode,
            elapsed_sec=elapsed,
            reward=reward,
            passed=passed,
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
            output_dir=str(output_dir) if output_dir else None,
            operations=operations,
            metrics=metrics,
        )

    def build_command(
        self,
        task: TaskSpec,
        *,
        model: str | None,
        output_dir: Path | None,
    ) -> list[str]:
        context: dict[str, Any] = {
            "harness": self.harness_id,
            "task": task.name,
            "task_path": str(task.path),
            "instruction": task.instruction,
            "model": model or "",
            "output_dir": str(output_dir or ""),
        }
        prompt = _task_prompt(task)
        context["prompt"] = prompt
        context["prompt_quoted"] = shlex.quote(prompt)
        rendered = _render_template(self.command_template, context)
        return shlex.split(rendered)


def _render_template(template: str, context: dict[str, Any]) -> str:
    escaped = template.replace("{", "{{").replace("}", "}}")
    for key in _PLACEHOLDERS:
        escaped = escaped.replace("{{" + key + "}}", "{" + key + "}")
    return escaped.format(**context)


def _task_prompt(task: TaskSpec) -> str:
    return (
        "Solve this coding task. Work only inside the task environment. "
        "When finished, leave the files ready for the verifier.\n\n"
        f"# Task: {task.name}\n\n{task.instruction}"
    )


def _find_reward(output_dir: Path | None, stdout: str, stderr: str) -> float | None:
    if output_dir:
        candidates = sorted(output_dir.rglob("reward.txt")) + sorted(output_dir.rglob("reward.json"))
        for path in candidates:
            parsed = _parse_reward_text(path.read_text(encoding="utf-8", errors="replace"))
            if parsed is not None:
                return parsed
    return _parse_reward_text(stdout) if _parse_reward_text(stdout) is not None else _parse_reward_text(stderr)


def _parse_reward_text(text: str) -> float | None:
    stripped = text.strip()
    if stripped in {"0", "0.0", "1", "1.0"}:
        return float(stripped)
    match = _REWARD_RE.search(text)
    if match:
        return float(match.group(1))
    return None


def _tail(text: str, limit: int = 4000) -> str:
    return text[-limit:] if len(text) > limit else text
