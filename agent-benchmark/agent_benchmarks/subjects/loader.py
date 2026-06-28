"""Load Phase D subject descriptors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import SUBJECT_KINDS, SubjectArtifact, SubjectDescriptor, SubjectMember, SubjectSuite

try:  # pragma: no cover - exercised via whichever parser the interpreter has
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


def load_subject(path: str | Path) -> SubjectDescriptor:
    """Load and validate a JSON/TOML subject descriptor."""
    path = Path(path)
    raw = _load_mapping(path)
    subject_raw = _mapping(raw.get("subject"), "subject")
    suite_raw = _mapping(raw.get("suite"), "suite")
    matrix_raw = raw.get("matrix", {})

    subject = _parse_subject(subject_raw)
    suite = _parse_suite(suite_raw)
    baseline = str(raw.get("baseline") or "baseline").strip()
    if not baseline:
        raise ValueError("baseline must not be empty")

    cells = _extract_matrix_cells(matrix_raw)
    matrix_cells_explicit = bool(cells)
    if not cells:
        cells = ({
            "id": "arms-runner",
            "model": str(raw.get("model") or "gpt-4o-mini"),
            "provider": str(raw.get("provider") or "openai"),
            "harness": str(raw.get("harness") or "arms-runner"),
            "plugins": [],
        },)

    return SubjectDescriptor(
        path=path,
        subject=subject,
        suite=suite,
        baseline=baseline,
        matrix_cells=tuple(cells),
        matrix_cells_explicit=matrix_cells_explicit,
    )


def awareness_arm_specs(descriptor: SubjectDescriptor) -> list[str]:
    """Return arm specs for awareness/Q&A runs."""
    specs = [descriptor.baseline]
    specs.extend(_subject_specs(descriptor.subject, agentic=False))
    return _dedupe(specs)


def work_arm_specs(descriptor: SubjectDescriptor) -> list[str]:
    """Return arm specs for executable/task runs."""
    specs = [descriptor.baseline]
    specs.extend(_subject_specs(descriptor.subject, agentic=True))
    return _dedupe(specs)


def matrix_config(descriptor: SubjectDescriptor) -> dict[str, Any]:
    """Return a matrix.cells config suitable for arms matrix-run."""
    return {"matrix": {"cells": list(descriptor.matrix_cells)}}


def _load_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
    elif suffix == ".toml":
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"subject descriptor must be .json or .toml, got {path}")
    return _mapping(raw, "descriptor")


def _mapping(raw: Any, name: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{name} must be an object")
    return raw


def _parse_subject(raw: dict[str, Any]) -> SubjectArtifact:
    subject_id = str(raw.get("id") or "").strip()
    kind = str(raw.get("kind") or "").strip()
    ref = raw.get("ref")
    if not subject_id:
        raise ValueError("subject.id is required")
    if kind not in SUBJECT_KINDS:
        raise ValueError(f"subject.kind must be one of {sorted(SUBJECT_KINDS)}, got {kind!r}")

    members_raw = raw.get("members", [])
    members: list[SubjectMember] = []
    if members_raw:
        if kind != "bundle":
            raise ValueError("subject.members is only valid for kind='bundle'")
        if not isinstance(members_raw, list):
            raise ValueError("subject.members must be a list")
        for idx, item in enumerate(members_raw):
            item_raw = _mapping(item, f"subject.members[{idx}]")
            member_kind = str(item_raw.get("kind") or "").strip()
            member_ref = str(item_raw.get("ref") or "").strip()
            if member_kind not in SUBJECT_KINDS - {"bundle"}:
                raise ValueError(f"subject.members[{idx}].kind is invalid: {member_kind!r}")
            if not member_ref:
                raise ValueError(f"subject.members[{idx}].ref is required")
            members.append(SubjectMember(kind=member_kind, ref=member_ref))

    ref_s = None if ref is None else str(ref).strip()
    if kind != "bundle" and not ref_s:
        raise ValueError(f"subject.ref is required for kind={kind!r}")
    if kind == "bundle" and not members:
        raise ValueError("bundle subjects require subject.members")
    return SubjectArtifact(id=subject_id, kind=kind, ref=ref_s, members=tuple(members))


def _parse_suite(raw: dict[str, Any]) -> SubjectSuite:
    products = _string_list(raw.get("products"), "suite.products")
    questions = _string_list(raw.get("questions"), "suite.questions")
    tasks = _string_list(raw.get("tasks", []), "suite.tasks")
    if not products:
        raise ValueError("suite.products must contain at least one product")
    if not questions:
        raise ValueError("suite.questions must contain at least one questions file")
    return SubjectSuite(products=tuple(products), questions=tuple(questions), tasks=tuple(tasks))


def _extract_matrix_cells(raw: Any) -> tuple[dict[str, Any], ...]:
    if not raw:
        return ()
    raw = _mapping(raw, "matrix")
    cells = raw.get("cells", [])
    if not isinstance(cells, list):
        raise ValueError("matrix.cells must be a list")
    out: list[dict[str, Any]] = []
    for idx, cell in enumerate(cells):
        cell_raw = _mapping(cell, f"matrix.cells[{idx}]")
        out.append(dict(cell_raw))
    return tuple(out)


def _string_list(raw: Any, name: str) -> list[str]:
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        values = raw
    else:
        raise ValueError(f"{name} must be a string or string list")
    return [item.strip() for item in values if item.strip()]


def _subject_specs(subject: SubjectArtifact, *, agentic: bool) -> list[str]:
    if subject.kind == "bundle":
        parts = []
        for member in subject.members:
            parts.extend(_member_specs(member.kind, member.ref, agentic=agentic))
        if len(parts) > 1 and parts[0].startswith("mcp:"):
            first_non_mcp = next((idx for idx, part in enumerate(parts) if not part.startswith("mcp:")), None)
            if first_non_mcp is not None:
                parts.insert(0, parts.pop(first_non_mcp))
        return ["+".join(parts)]
    return _member_specs(subject.kind, subject.ref or "", agentic=agentic)


def _member_specs(kind: str, ref: str, *, agentic: bool) -> list[str]:
    if kind == "skill":
        return [f"skill-agent:{ref}" if agentic else f"skill:{ref}"]
    if kind == "profile":
        return [f"profile:{ref}"]
    if kind == "mcp":
        normalized = ref.removeprefix("mcp:")
        return [f"agent:mcp:{normalized}" if agentic else f"mcp:{normalized}"]
    if kind == "doc-source":
        return [f"agent:{ref}" if agentic else f"docs:{ref}"]
    raise ValueError(f"unsupported subject kind {kind!r}")


def _dedupe(values: list[str]) -> list[str]:
    out = []
    for value in values:
        if value not in out:
            out.append(value)
    return out
