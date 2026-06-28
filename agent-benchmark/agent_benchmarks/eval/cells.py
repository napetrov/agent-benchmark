"""Model × harness evaluation cells (ADR 2026-06-10, Phase B).

Implements the load-bearing rules from
``docs/decisions/2026-06-10-model-harness-dimension.md``:

  §2.1  **Stamp every result row** with its ``(model, harness)`` (and, per the
        plugin-aware extension, ``plugin_set``).
  §2.2  **Refuse to delta across cells.** An arm's delta is only meaningful
        *within* one ``(model, harness, plugin_set)`` cell; a cross-cell
        difference is variance *of the axis*, never a treatment effect. This
        module makes that rule executable via :func:`safe_delta`, so the
        invariant is enforced in code rather than left to reviewer discipline
        (the ADR calls this rule "load-bearing, not pedantry").

This is pure, offline logic — no LLM calls — so it is fully unit-testable in CI.
The harness taxonomy mirrors ADR §3.1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Harness taxonomy (ADR §3.1). `terminal-bench:<agent>` is a family; a concrete
# instance pins one Harbor agent (e.g. "terminal-bench:terminus").
HARNESS_SINGLE_SHOT = "single-shot"   # one completion; judge score
HARNESS_AGENT = "agent"               # bounded tool-calling loop; judge + tool_use_rate
HARNESS_TERMINAL_BENCH = "terminal-bench"  # Harbor drives a coding agent; pass-rate
HARNESS_ARMS_RUNNER = "arms-runner"  # local in-process arms runner
HARNESS_OPENCLAW_AGENT = "openclaw-agent"  # OpenClaw runtime adapter
_KNOWN_HARNESS_PREFIXES = (
    HARNESS_SINGLE_SHOT,
    HARNESS_AGENT,
    HARNESS_TERMINAL_BENCH,
    HARNESS_ARMS_RUNNER,
    HARNESS_OPENCLAW_AGENT,
)

# Canonical id of the empty plugin set (matches ArmRunner's default).
EMPTY_PLUGIN_SET = "none"


class CrossCellDeltaError(ValueError):
    """Raised when a delta is attempted across two different cells (ADR §2.2)."""


def is_known_harness(harness: str) -> bool:
    """True for a recognized harness id or a ``terminal-bench:<agent>`` instance."""
    if harness in (
        HARNESS_SINGLE_SHOT,
        HARNESS_AGENT,
        HARNESS_TERMINAL_BENCH,
        HARNESS_ARMS_RUNNER,
        HARNESS_OPENCLAW_AGENT,
    ):
        return True
    return harness.startswith(HARNESS_TERMINAL_BENCH + ":")


@dataclass(frozen=True)
class Cell:
    """A ``(model, harness, plugin_set)`` evaluation cell — the unit within which
    deltas are valid (ADR §2.2 + plugin-aware extension §2)."""

    model: str
    harness: str
    plugin_set: str = EMPTY_PLUGIN_SET

    @property
    def key(self) -> str:
        """Stable string key for grouping/keying result rows."""
        return f"{self.model}|{self.harness}|{self.plugin_set}"

    def __str__(self) -> str:  # human-readable
        return f"(model={self.model}, harness={self.harness}, plugins={self.plugin_set})"

    @classmethod
    def from_row(cls, row: dict) -> "Cell":
        """Build a Cell from a stamped result row / arm dict.

        Accepts the fields ArmRunner already emits: ``model``, ``harness``,
        ``plugin_set`` (defaults to the empty set when absent).
        """
        return cls(
            model=str(row.get("model", "")),
            harness=str(row.get("harness", "")),
            plugin_set=str(row.get("plugin_set", EMPTY_PLUGIN_SET)),
        )


def same_cell(a: dict | Cell, b: dict | Cell) -> bool:
    """True iff two rows/cells belong to the same ``(model, harness, plugin_set)``."""
    ca = a if isinstance(a, Cell) else Cell.from_row(a)
    cb = b if isinstance(b, Cell) else Cell.from_row(b)
    return ca == cb


def safe_delta(
    treated: dict | Cell,
    baseline: dict | Cell,
    treated_score: float | None,
    baseline_score: float | None,
    *,
    ndigits: int = 1,
) -> float | None:
    """Return ``treated_score - baseline_score`` only if both share a cell.

    Enforces ADR §2.2: a delta across different ``(model, harness, plugin_set)``
    cells is not a treatment effect and must not be computed. Raises
    :class:`CrossCellDeltaError` rather than silently returning a misleading
    number. Returns ``None`` if either score is missing.
    """
    if not same_cell(treated, baseline):
        ct = treated if isinstance(treated, Cell) else Cell.from_row(treated)
        cb = baseline if isinstance(baseline, Cell) else Cell.from_row(baseline)
        raise CrossCellDeltaError(
            f"refusing cross-cell delta: treated {ct} vs baseline {cb}; "
            "deltas are only valid within one (model, harness, plugin_set) cell "
            "(ADR 2026-06-10 §2.2)"
        )
    if treated_score is None or baseline_score is None:
        return None
    return round(float(treated_score) - float(baseline_score), ndigits)


def group_by_cell(rows: list[dict]) -> dict[str, list[dict]]:
    """Group stamped result rows by their cell key (ADR §3.3 result cube)."""
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(Cell.from_row(row).key, []).append(row)
    return out


@dataclass(frozen=True)
class MatrixCellDescriptor:
    """User-facing descriptor for one explicit benchmark matrix cell."""

    name: str
    model: str
    provider: str
    harness: str
    plugin_specs: tuple[str, ...] = ()


def load_matrix_cells(path: str | Path) -> list[MatrixCellDescriptor]:
    """Load ``matrix.cells`` descriptors from JSON.

    Accepted shapes are ``{"matrix": {"cells": [...]}}``, ``{"cells": [...]}``,
    or a top-level list of cells.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cells = _extract_cells(raw)
    out = [_parse_matrix_cell(item, idx) for idx, item in enumerate(cells)]
    names = [c.name for c in out]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"duplicate matrix cell names: {', '.join(duplicates)}")
    return out


def select_matrix_cell(cells: list[MatrixCellDescriptor], name: str) -> MatrixCellDescriptor:
    """Return one named descriptor or raise a helpful error."""
    for cell in cells:
        if cell.name == name:
            return cell
    available = ", ".join(c.name for c in cells) or "(none)"
    raise ValueError(f"matrix cell '{name}' not found; available cells: {available}")


def _extract_cells(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        matrix = raw.get("matrix")
        if isinstance(matrix, dict) and "cells" in matrix:
            cells = matrix["cells"]
        else:
            cells = raw.get("cells")
        if isinstance(cells, list):
            return cells
    raise ValueError("matrix config must contain a cells list")


def _parse_matrix_cell(raw: Any, idx: int) -> MatrixCellDescriptor:
    if not isinstance(raw, dict):
        raise ValueError(f"matrix cell #{idx + 1} must be an object")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError(f"matrix cell #{idx + 1} is missing name")
    model = str(raw.get("model") or "").strip()
    provider = str(raw.get("provider") or "").strip()
    harness = str(raw.get("harness") or "").strip()
    missing = [
        field for field, value in (
            ("model", model),
            ("provider", provider),
            ("harness", harness),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"matrix cell '{name}' is missing {', '.join(missing)}")
    if not is_known_harness(harness):
        raise ValueError(f"matrix cell '{name}' has unknown harness '{harness}'")

    plugins = raw.get("plugins", [])
    if isinstance(plugins, str):
        plugin_specs = tuple(s.strip() for s in plugins.split(",") if s.strip())
    elif isinstance(plugins, list) and all(isinstance(p, str) for p in plugins):
        plugin_specs = tuple(p.strip() for p in plugins if p.strip())
    else:
        raise ValueError(f"matrix cell '{name}' plugins must be a string list")

    return MatrixCellDescriptor(
        name=name,
        model=model,
        provider=provider,
        harness=harness,
        plugin_specs=plugin_specs,
    )
