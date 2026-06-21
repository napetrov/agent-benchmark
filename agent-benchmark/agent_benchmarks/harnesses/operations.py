"""Operation telemetry extraction for external coding harnesses."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import OperationRecord

_MARKER = "AGENT_BENCHMARK_OP"
_KEYWORD_TYPES = ("tool", "subagent", "loop")


def load_operations(output_dir: Path | None, stdout: str, stderr: str) -> list[OperationRecord]:
    """Collect operation telemetry from structured files and output markers.

    Harness wrappers can emit JSONL records into ``operations.jsonl`` or print
    lines prefixed with ``AGENT_BENCHMARK_OP`` followed by a JSON object.
    """

    operations: list[OperationRecord] = []
    if output_dir:
        for name in ("operations.jsonl", "operation-log.jsonl"):
            operations.extend(_read_jsonl(output_dir / name))
    operations.extend(_parse_markers(stdout))
    operations.extend(_parse_markers(stderr))
    operations.extend(_parse_keyword_lines(stdout, "stdout"))
    operations.extend(_parse_keyword_lines(stderr, "stderr"))
    return operations


def _read_jsonl(path: Path) -> list[OperationRecord]:
    if not path.is_file():
        return []
    out: list[OperationRecord] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [
            OperationRecord(
                type="log_parse_error",
                name=path.name,
                status="error",
                metadata={"error": str(exc)},
            )
        ]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(_op_from_dict(json.loads(line)))
        except json.JSONDecodeError:
            out.append(OperationRecord(type="log_parse_error", name=path.name, status="error"))
    return out


def _parse_markers(text: str) -> list[OperationRecord]:
    out: list[OperationRecord] = []
    for line in text.splitlines():
        if _MARKER not in line:
            continue
        payload = line.split(_MARKER, 1)[1].strip()
        try:
            out.append(_op_from_dict(json.loads(payload)))
        except json.JSONDecodeError:
            out.append(OperationRecord(type="log_parse_error", name="marker", status="error"))
    return out


def _parse_keyword_lines(text: str, stream: str) -> list[OperationRecord]:
    out: list[OperationRecord] = []
    for line in text.splitlines():
        if _MARKER in line:
            continue
        lowered = line.lower()
        for op_type in _KEYWORD_TYPES:
            if re.search(rf"\b{op_type}s?\b", lowered):
                out.append(
                    OperationRecord(
                        type=op_type,
                        name="unstructured-log",
                        metadata={"stream": stream, "line": line[:300]},
                    )
                )
                break
    return out


def _op_from_dict(data: dict[str, Any]) -> OperationRecord:
    op_type = str(data.get("type") or data.get("kind") or "operation")
    name = str(data.get("name") or data.get("tool") or data.get("subagent") or op_type)
    status = str(data.get("status") or "ok")
    elapsed = float(data.get("elapsed_sec") or data.get("duration_sec") or 0.0)
    metadata = {
        k: v
        for k, v in data.items()
        if k not in {"type", "kind", "name", "tool", "subagent", "status", "elapsed_sec", "duration_sec"}
    }
    return OperationRecord(type=op_type, name=name, status=status, elapsed_sec=elapsed, metadata=metadata)
