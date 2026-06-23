"""Standalone Docker harness — solve a terminal-bench task and verify it.

This is the Python port of ``scripts/run_task.sh``: it runs an executable task
end to end against local Docker with **no Harbor dependency**, and — unlike the
bash script — captures full LLM telemetry (cost, tokens, cache, latency,
turns) into the ``task_runs.v1`` artifact so task experiments are tracked the
same way the Q&A ``arms run`` path already is.

Two solver modes:

``oracle``
    Apply the task's own ``solution/solve.sh`` (no LLM). Validates that the task
    image + verifier work end to end. Free; no telemetry.
``claude``
    Run ``claude -p --output-format json`` to solve from ``instruction.md``.
    The JSON result carries ``total_cost_usd`` / ``usage`` / ``duration_ms`` /
    ``ttft_ms`` / ``num_turns``, which we parse into a :class:`UsageRecord` and
    fold into ``HarnessResult.metrics``. An optional skill directory is copied
    next to the work tree (the with-skill treatment arm).

The agent runs on the HOST (the ``claude`` CLI is a host tool); we snapshot
``/app`` out of the container, let the agent edit it, copy it back, and
recompile inside the container so the binary matches the image's (older) glibc.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agent_benchmarks.metrics.usage import UsageRecord

from .models import HarnessResult, OperationRecord
from .tasks import TaskSpec

# Recompile commands embedded in instruction.md, e.g. `g++ -O3 ... -o /app/bench`.
# C tasks (missing-restrict) use gcc, C++ tasks use g++.
_RECOMPILE_RE = re.compile(r"(g\+\+|gcc) [^`\n]*-o /app/[^ `\n]*")
_PROXY_VARS = ("http_proxy", "https_proxy", "no_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
_DEFAULT_SOLVE_TIMEOUT = 600.0
_DEFAULT_BUILD_TIMEOUT = 600.0
_DEFAULT_VERIFY_TIMEOUT = 180.0


@dataclass(frozen=True)
class DockerSolverHarness:
    """Build → solve → verify a task with local Docker; emit reward + telemetry.

    ``mode`` is ``oracle`` or ``claude``. ``skill_path`` (claude mode only)
    points at a skill directory or its ``SKILL.md``; when set, the whole skill
    tree is exposed to the agent as the with-skill treatment arm.
    """

    harness_id: str
    mode: str = "claude"
    skill_path: Optional[str] = None
    model_default: Optional[str] = None
    kind: str = "docker"
    env: dict[str, str] = field(default_factory=dict)

    def run(
        self,
        task: TaskSpec,
        *,
        model: Optional[str] = None,
        output_dir: Optional[Path] = None,
        timeout_sec: Optional[float] = None,
        dry_run: bool = False,
    ) -> HarnessResult:
        output_dir = Path(output_dir) if output_dir else None
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
        model = model or self.model_default

        operations = [
            OperationRecord(
                type="harness",
                name=self.harness_id,
                metadata={"kind": self.kind, "task": task.name, "model": model, "mode": self.mode},
            )
        ]

        if dry_run:
            return HarnessResult(
                harness=self.harness_id,
                task=task.name,
                command=self._describe_command(task, model),
                returncode=0,
                elapsed_sec=0.0,
                reward=None,
                passed=False,
                output_dir=str(output_dir) if output_dir else None,
                operations=operations,
                metrics={"dry_run": True, "mode": self.mode},
            )

        if output_dir is None:
            raise ValueError("DockerSolverHarness requires an output_dir")

        log_path = output_dir / "run.log"
        log = log_path.open("w", encoding="utf-8")
        usage: Optional[UsageRecord] = None
        image = f"agent-bench/{task.name}:latest"
        container = f"abrun-{task.name}-{os.getpid()}"
        solve_timeout = timeout_sec or task.timeout_sec or _DEFAULT_SOLVE_TIMEOUT
        start = time.time()
        returncode = 0
        try:
            self._build_image(task, image, log)
            self._start_container(image, container, log)
            try:
                if self.mode == "oracle":
                    self._solve_oracle(task, container, log)
                elif self.mode == "claude":
                    usage = self._solve_claude(
                        task, container, output_dir, model, solve_timeout, operations, log
                    )
                else:
                    raise ValueError(f"unknown mode {self.mode!r}")
                reward = self._verify(task, container, output_dir, log)
            finally:
                _docker(["rm", "-f", container], log, check=False)
        except subprocess.TimeoutExpired as exc:
            log.write(f"\nTIMEOUT: {exc}\n")
            returncode = 124
            reward = 0.0
        finally:
            log.close()

        elapsed = time.time() - start
        passed = reward is not None and reward >= 1.0
        metrics: dict[str, Any] = {"dry_run": False, "mode": self.mode}
        if usage is not None:
            metrics.update(usage.as_metrics_dict())
        return HarnessResult(
            harness=self.harness_id,
            task=task.name,
            command=self._describe_command(task, model),
            returncode=returncode,
            elapsed_sec=elapsed,
            reward=reward,
            passed=passed,
            stdout_tail=_tail(log_path.read_text(encoding="utf-8", errors="replace")),
            output_dir=str(output_dir),
            operations=operations,
            metrics=metrics,
        )

    # ── pipeline steps ──────────────────────────────────────────────────────

    def _build_image(self, task: TaskSpec, image: str, log) -> None:
        """Build the task image; pass host proxy through (corporate networks)."""
        env_dir = task.path / "environment"
        build_args: list[str] = ["--network", "host"]
        for var in _PROXY_VARS:
            val = os.environ.get(var)
            if val:
                build_args += ["--build-arg", f"{var}={val}"]
        # Honor the task's own build_timeout_sec (some images need >10 min);
        # _DEFAULT_BUILD_TIMEOUT is only the fallback when the task omits it.
        timeout = _task_build_timeout(task)
        _docker(
            ["build", "-q", *build_args, "-t", image,
             "-f", str(env_dir / "Dockerfile"), str(env_dir)],
            log, timeout=timeout,
        )

    def _start_container(self, image: str, container: str, log) -> None:
        _docker(["rm", "-f", container], log, check=False)
        _docker(
            ["run", "-d", "--name", container, "--network", "none",
             "--cpus", "4", "--memory", "2g", image, "sleep", "1800"],
            log,
        )

    def _solve_oracle(self, task: TaskSpec, container: str, log) -> None:
        """Apply solution/solve.sh as root (some images set a non-root USER)."""
        _docker(["cp", str(task.path / "solution" / "solve.sh"), f"{container}:/solve.sh"], log)
        _docker(
            ["exec", "-u", "root", container, "bash", "-lc", "chmod +x /solve.sh && /solve.sh"],
            log, check=False,
        )

    def _solve_claude(
        self, task: TaskSpec, container: str, output_dir: Path,
        model: Optional[str], timeout: float, operations: list[OperationRecord], log,
    ) -> Optional[UsageRecord]:
        """Snapshot /app, solve on the host, copy back, recompile in-container.

        Returns a :class:`UsageRecord` parsed from ``claude --output-format json``
        (cost/tokens/cache/latency/turns), or ``None`` if the JSON was missing.
        """
        work = output_dir / "work"
        if work.exists():
            _rmtree(work)
        work.mkdir(parents=True)
        _docker(["cp", f"{container}:/app/.", str(work)], log)

        skill_note = ""
        skill_dir = self._resolve_skill_dir()
        if skill_dir is not None:
            dest = work / ".skill"
            _copytree(skill_dir, dest)
            entry = self._skill_entry(skill_dir)
            skill_note = (
                f"A performance skill is available at ./.skill/ "
                f"(start with ./.skill/{entry}). Read the files it references "
                "before fixing.\n\n"
            )

        prompt = (
            f"{skill_note}"
            "Solve this coding task. Edit files in the current directory only. "
            "When done, leave the optimized source and any required outputs in place.\n\n"
            f"{task.instruction}"
        )
        prompt_file = output_dir / "prompt.txt"
        prompt_file.write_text(prompt, encoding="utf-8")

        cmd = ["claude", "-p", prompt, "--output-format", "json",
               "--dangerously-skip-permissions",
               "--allowedTools", "Read", "Edit", "Write", "Bash"]
        if model:
            cmd += ["--model", model]
        t0 = time.time()
        proc = subprocess.run(
            cmd, cwd=str(work), text=True, capture_output=True,
            timeout=timeout, check=False, env={**os.environ, **self.env},
        )
        latency = time.time() - t0
        log.write(proc.stdout or "")
        log.write(proc.stderr or "")
        usage = _parse_claude_json(proc.stdout, task.name, model or "", latency)
        (output_dir / "solver.json").write_text(proc.stdout or "", encoding="utf-8")
        if usage is not None:
            operations.append(
                OperationRecord(type="loop", name="claude-turns", elapsed_sec=usage.latency_sec,
                                metadata={"n_calls": usage.n_calls})
            )

        # Don't ship the skill files into /app for the verifier.
        if (work / ".skill").exists():
            _rmtree(work / ".skill")
        _docker(["cp", f"{str(work)}/.", f"{container}:/app/"], log)
        self._recompile(task, container, log)
        return usage

    def _recompile(self, task: TaskSpec, container: str, log) -> None:
        """Recompile inside the container so the binary matches the image glibc.

        The agent edits source on the host (newer glibc); a host-built binary may
        fail in the older task image, so re-run the compile command(s) documented
        in instruction.md in-container. Matches both ``g++`` and ``gcc``.
        """
        for match in _RECOMPILE_RE.finditer(task.instruction):
            cc = match.group(0).strip()
            log.write(f"\n[recompile] {cc}\n")
            _docker(["exec", "-u", "root", container, "bash", "-lc", cc], log, check=False)

    def _verify(self, task: TaskSpec, container: str, output_dir: Path, log) -> Optional[float]:
        """Run tests/ in-container; pull /logs/verifier/reward.txt back out."""
        _docker(["cp", str(task.path / "tests"), f"{container}:/tests"], log)
        proc = _docker(
            ["exec", "-u", "root", container, "bash", "-lc",
             "mkdir -p /logs/verifier && chmod +x /tests/test.sh && /tests/test.sh"],
            log, check=False, timeout=_task_verify_timeout(task),
        )
        reward_file = output_dir / "reward.txt"
        pulled = _docker(
            ["cp", f"{container}:/logs/verifier/reward.txt", str(reward_file)],
            log, check=False,
        )
        if pulled.returncode == 0 and reward_file.is_file():
            return _parse_reward(reward_file.read_text(encoding="utf-8", errors="replace"))
        # No reward file written: fall back to verifier exit code.
        return 1.0 if proc.returncode == 0 else 0.0

    # ── helpers ─────────────────────────────────────────────────────────────

    def _resolve_skill_dir(self) -> Optional[Path]:
        if not self.skill_path:
            return None
        p = Path(self.skill_path)
        return p.parent if p.is_file() else p

    def _skill_entry(self, skill_dir: Path) -> str:
        if self.skill_path and Path(self.skill_path).is_file():
            return Path(self.skill_path).name
        return "SKILL.md"

    def _describe_command(self, task: TaskSpec, model: Optional[str]) -> list[str]:
        parts = ["docker-solver", self.mode, task.name]
        if model:
            parts += ["--model", model]
        if self.skill_path:
            parts += ["--skill", self.skill_path]
        return parts


def _task_build_timeout(task: TaskSpec) -> float:
    """Image build timeout: the task's ``environment.build_timeout_sec`` if set,
    else :data:`_DEFAULT_BUILD_TIMEOUT`."""
    val = task.environment.get("build_timeout_sec")
    try:
        return float(val) if val is not None else _DEFAULT_BUILD_TIMEOUT
    except (TypeError, ValueError):
        return _DEFAULT_BUILD_TIMEOUT


def _task_verify_timeout(task: TaskSpec) -> float:
    """Verifier timeout: the task's ``verifier.timeout_sec`` if set, else
    :data:`_DEFAULT_VERIFY_TIMEOUT`."""
    val = task.verifier.get("timeout_sec")
    try:
        return float(val) if val is not None else _DEFAULT_VERIFY_TIMEOUT
    except (TypeError, ValueError):
        return _DEFAULT_VERIFY_TIMEOUT


def _docker(args: list[str], log, *, check: bool = True,
            timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    """Run a ``docker`` subcommand, tee-ing output to the run log."""
    proc = subprocess.run(
        ["docker", *args], text=True, capture_output=True, timeout=timeout, check=False,
    )
    log.write(f"$ docker {' '.join(shlex.quote(a) for a in args)}\n")
    if proc.stdout:
        log.write(proc.stdout)
    if proc.stderr:
        log.write(proc.stderr)
    if check and proc.returncode != 0:
        raise RuntimeError(f"docker {args[0]} failed (exit {proc.returncode}); see run.log")
    return proc


def _parse_claude_json(stdout: str, task: str, model: str, latency: float) -> Optional[UsageRecord]:
    """Parse ``claude -p --output-format json`` into a :class:`UsageRecord`.

    The CLI prints a single result object with ``total_cost_usd``, a nested
    ``usage`` block (input/output/cache tokens), ``duration_ms``, ``ttft_ms``,
    and ``num_turns``. Returns ``None`` when no parseable object is found (the
    elapsed wall-clock ``latency`` is used as a fallback for ``latency_sec``).
    """
    obj = _last_json_object(stdout)
    if obj is None:
        return None
    u = obj.get("usage") or {}
    input_tokens = int(u.get("input_tokens", 0) or 0)
    output_tokens = int(u.get("output_tokens", 0) or 0)
    cache_read = int(u.get("cache_read_input_tokens", 0) or 0)
    cache_write = int(u.get("cache_creation_input_tokens", 0) or 0)
    duration_ms = obj.get("duration_ms")
    ttft_ms = obj.get("ttft_ms")
    cost = obj.get("total_cost_usd")
    return UsageRecord(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        cost_usd=float(cost) if cost is not None else None,
        latency_sec=(duration_ms / 1000.0) if duration_ms is not None else latency,
        ttft_sec=(ttft_ms / 1000.0) if ttft_ms is not None else None,
        model=model,
        provider="claude-code",
        n_calls=int(obj.get("num_turns", 1) or 1),
        cost_known_calls=1 if cost is not None else 0,
    )


def _last_json_object(text: str) -> Optional[dict]:
    """Return the last top-level JSON object printed on stdout, if any."""
    if not text:
        return None
    # The result object is normally the final non-empty line.
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    # Fall back to the last {...} span anywhere in the output.
    match = None
    for match in re.finditer(r"\{.*\}", text, re.DOTALL):
        pass
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _parse_reward(text: str) -> Optional[float]:
    stripped = (text or "").strip()
    if stripped in {"0", "0.0", "1", "1.0"}:
        return float(stripped)
    try:
        return float(stripped)
    except ValueError:
        return None


def _copytree(src: Path, dest: Path) -> None:
    import shutil

    shutil.copytree(src, dest)


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def _tail(text: str, limit: int = 4000) -> str:
    return text[-limit:] if len(text) > limit else text
