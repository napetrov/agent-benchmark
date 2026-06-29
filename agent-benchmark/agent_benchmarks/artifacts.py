"""Versioned, schema-validated I/O for produced artifacts.

The benchmark produces long-lived JSON artifact kinds: ``questions``,
``answers``, ``eval`` (LLM-judge scores), ``arms`` (treatment-arm comparisons),
``task_runs`` (executable task results), and ``explore_runs`` (ExploreBench
localization results). This module stamps each with a ``schema_version`` and
validates it against the JSON Schema in ``agent_benchmarks/schemas/`` on save
and load, so fixtures and baselines stay forward-compatible and self-describing.
"""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

# kind -> current schema_version string (also the schema filename stem).
SCHEMA_VERSIONS: dict[str, str] = {
    "questions": "questions.v1",
    "answers": "answers.v1",
    "eval": "eval.v1",
    "arms": "arms.v1",
    "matrix_rollup": "matrix_rollup.v1",
    "plugin_delta": "plugin_delta.v1",
    "subject_scorecard": "subject_scorecard.v1",
    "task_runs": "task_runs.v1",
    "explore_runs": "explore_runs.v1",
}


class ArtifactValidationError(ValueError):
    """Raised when an artifact does not conform to its schema."""


def _schema_path(kind: str) -> Path:
    if kind not in SCHEMA_VERSIONS:
        raise KeyError(f"Unknown artifact kind: {kind!r}. Known: {sorted(SCHEMA_VERSIONS)}")
    return SCHEMA_DIR / f"{SCHEMA_VERSIONS[kind]}.json"


def validate_artifact(kind: str, data: dict) -> None:
    """Validate ``data`` against the schema for ``kind`` (raises on failure)."""
    from jsonschema import Draft202012Validator

    schema = json.loads(_schema_path(kind).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        details = "\n".join(
            f"  - {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors
        )
        raise ArtifactValidationError(f"{kind} artifact validation failed:\n{details}")


def stamp(kind: str, data: dict) -> dict:
    """Return ``data`` with its ``schema_version`` set for ``kind``."""
    if kind not in SCHEMA_VERSIONS:
        raise KeyError(f"Unknown artifact kind: {kind!r}")
    data["schema_version"] = SCHEMA_VERSIONS[kind]
    return data


def save_artifact(kind: str, data: dict, path: Path, *, validate: bool = True) -> None:
    """Stamp, (optionally) validate, and write an artifact to ``path``.

    Operates on a shallow copy so the caller's dict is not mutated.
    """
    payload = dict(data)
    stamp(kind, payload)
    if validate:
        validate_artifact(kind, payload)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_artifact(kind: str, path: Path, *, validate: bool = True) -> dict:
    """Read and (optionally) validate an artifact from ``path``."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if validate:
        validate_artifact(kind, data)
    return data
