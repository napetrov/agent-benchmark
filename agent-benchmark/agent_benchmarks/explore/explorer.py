"""Explorers: produce a ``<final_answer>`` citation block for a task.

An *explorer* takes an exploration query over a repo/doc tree and returns a
compact citation block plus any operation telemetry it emitted. Two concrete
explorers ship here:

* :class:`StaticExplorer` — returns a canned answer. Used by tests, dry runs,
  and as an oracle baseline (feed it the reference locations to get a perfect
  score, or a deliberately broad/empty answer to model a weak explorer).
* :class:`CommandExplorer` — run an external CLI (a FastContext binary,
  ``claude -p``, etc.), capture its stdout as the final answer, and ingest any
  ``AGENT_BENCHMARK_OP`` / ``operations.jsonl`` telemetry it produced.

Both return an :class:`ExplorerResult`, so the ExploreBench runner and the
command-wrapper harness (BACKLOG #60 slices 5 + 6) consume one shape.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from agent_benchmarks.harnesses.models import OperationRecord
from agent_benchmarks.harnesses.operations import load_operations
from agent_benchmarks.metrics.exploration import CitationSet, parse_final_answer


@dataclass(frozen=True)
class ExplorerResult:
    """What an explorer returns for one task."""

    final_answer: str
    operations: tuple[OperationRecord, ...] = ()
    elapsed_sec: float = 0.0
    returncode: int = 0


class Explorer(Protocol):
    """Anything that can answer an exploration query with a citation block."""

    name: str

    def explore(self, query: str, *, repo_root: Path) -> ExplorerResult:
        ...


@dataclass
class StaticExplorer:
    """Return a fixed answer regardless of the query (tests / oracle / dry run)."""

    answer: str
    name: str = "static"
    operations: tuple[OperationRecord, ...] = ()

    def explore(self, query: str, *, repo_root: Path) -> ExplorerResult:
        return ExplorerResult(final_answer=self.answer, operations=self.operations)

    @classmethod
    def from_references(cls, references, name: str = "oracle") -> "StaticExplorer":
        """Build an oracle explorer that cites exactly the reference locations."""
        lines = []
        for ref in references:
            if ref.lines:
                lines.append(f"{ref.path}:{ref.lines[0]}-{ref.lines[1]}")
            else:
                lines.append(ref.path)
        answer = "<final_answer>\n" + "\n".join(lines) + "\n</final_answer>"
        return cls(answer=answer, name=name)


@dataclass
class CommandExplorer:
    """Run a CLI explorer and capture its citation block + telemetry.

    ``command_template`` is rendered with ``{query}``, ``{query_quoted}``,
    ``{repo_root}``, and ``{output_dir}`` placeholders, then split with
    ``shlex`` and executed inside ``repo_root``. The process stdout is the final
    answer; any ``AGENT_BENCHMARK_OP`` markers or ``operations.jsonl`` it writes
    under ``output_dir`` are ingested as operations.
    """

    command_template: str
    name: str = "command"
    timeout_sec: float = 600.0
    env: dict = field(default_factory=dict)
    output_root: Path | None = None

    def explore(self, query: str, *, repo_root: Path) -> ExplorerResult:
        output_dir = self.output_root
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
        context = {
            "query": query,
            "query_quoted": shlex.quote(query),
            "repo_root": str(repo_root),
            "output_dir": str(output_dir or ""),
        }
        command = shlex.split(_render(self.command_template, context))
        env = os.environ.copy()
        env.update(self.env)
        if output_dir is not None:
            env["AGENT_BENCHMARK_OUTPUT_DIR"] = str(output_dir)
            env["AGENT_BENCHMARK_OPERATIONS_FILE"] = str(output_dir / "operations.jsonl")
        start = time.time()
        proc = subprocess.run(
            command,
            cwd=str(repo_root),
            env=env,
            text=True,
            capture_output=True,
            timeout=self.timeout_sec,
            check=False,
        )
        elapsed = time.time() - start
        stdout = proc.stdout or ""
        operations = tuple(load_operations(output_dir, stdout, proc.stderr or ""))
        return ExplorerResult(
            final_answer=stdout,
            operations=operations,
            elapsed_sec=elapsed,
            returncode=proc.returncode,
        )


_PLACEHOLDERS = ("query", "query_quoted", "repo_root", "output_dir")


def _render(template: str, context: dict) -> str:
    escaped = template.replace("{", "{{").replace("}", "}}")
    for key in _PLACEHOLDERS:
        escaped = escaped.replace("{{" + key + "}}", "{" + key + "}")
    return escaped.format(**context)


def build_subagent_op(
    name: str,
    cset: CitationSet,
    *,
    elapsed_sec: float = 0.0,
    status: str = "ok",
) -> OperationRecord:
    """Build the ``subagent`` telemetry op for one exploration (ADR §3.3).

    This is the bridge between the exploration step and the operation-stream
    metrics layer: a terminal-bench wrapper that delegates context discovery to
    an explorer records this op (or its marker line via :func:`op_marker_line`),
    and ``summarize_exploration`` then folds it into ``exploration_metrics``.
    """
    return OperationRecord(
        type="subagent",
        name=name,
        status=status,
        elapsed_sec=elapsed_sec,
        metadata={
            "final_answer_valid": len(cset.malformed) == 0,
            "citation_count": len(cset.citations),
            "citation_paths": sorted({c.path for c in cset.citations}),
        },
    )


def subagent_op_from_answer(
    name: str, final_answer: str, *, elapsed_sec: float = 0.0, status: str = "ok"
) -> OperationRecord:
    """Parse a ``<final_answer>`` block and build its subagent op."""
    return build_subagent_op(
        name, parse_final_answer(final_answer), elapsed_sec=elapsed_sec, status=status
    )


def op_marker_line(op: OperationRecord) -> str:
    """Render an op as an ``AGENT_BENCHMARK_OP`` stdout marker line.

    A wrapper that cannot write ``operations.jsonl`` can ``print`` this line; the
    harness telemetry loader parses it back into an :class:`OperationRecord`.
    """
    payload = {
        "type": op.type,
        "name": op.name,
        "status": op.status,
        "elapsed_sec": round(op.elapsed_sec, 4),
        **op.metadata,
    }
    return "AGENT_BENCHMARK_OP " + json.dumps(payload)
