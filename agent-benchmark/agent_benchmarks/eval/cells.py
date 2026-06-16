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

from dataclasses import dataclass

# Harness taxonomy (ADR §3.1). `terminal-bench:<agent>` is a family; a concrete
# instance pins one Harbor agent (e.g. "terminal-bench:terminus").
HARNESS_SINGLE_SHOT = "single-shot"   # one completion; judge score
HARNESS_AGENT = "agent"               # bounded tool-calling loop; judge + tool_use_rate
HARNESS_TERMINAL_BENCH = "terminal-bench"  # Harbor drives a coding agent; pass-rate
_KNOWN_HARNESS_PREFIXES = (
    HARNESS_SINGLE_SHOT,
    HARNESS_AGENT,
    HARNESS_TERMINAL_BENCH,
)

# Canonical id of the empty plugin set (matches ArmRunner's default).
EMPTY_PLUGIN_SET = "none"


class CrossCellDeltaError(ValueError):
    """Raised when a delta is attempted across two different cells (ADR §2.2)."""


def is_known_harness(harness: str) -> bool:
    """True for a recognized harness id or a ``terminal-bench:<agent>`` instance."""
    if harness in (HARNESS_SINGLE_SHOT, HARNESS_AGENT):
        return True
    return harness == HARNESS_TERMINAL_BENCH or harness.startswith(
        HARNESS_TERMINAL_BENCH + ":"
    )


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
