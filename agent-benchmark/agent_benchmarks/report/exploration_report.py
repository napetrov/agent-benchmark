"""Render exploration-quality panels from run artifacts (BACKLOG #60, ADR §3.6).

Two inputs are supported:

* an ``explore_runs.v1`` artifact — renders the citation-quality leaderboard
  (file/line F1, validity, compactness) and baseline deltas.
* a ``task_runs.v1`` artifact whose result rows carry an ``exploration_metrics``
  block — renders the trajectory/token panel (pre-edit cost, repeated reads,
  broad-search-after-subagent, main vs full-system tokens).

Pure string rendering; the caller loads the JSON and writes the Markdown.
"""

from __future__ import annotations

from typing import Any


def render_explore_report(artifact: dict[str, Any]) -> str:
    """Markdown leaderboard for an ``explore_runs.v1`` artifact."""
    lines = ["# Exploration quality (ExploreBench)", ""]
    summary = artifact.get("summary", {})
    per_arm = summary.get("per_arm", {})
    if not per_arm:
        return "\n".join(lines + ["_No exploration results._", ""])

    lines += [
        "| arm | n | file F1 | line F1 | validity | compactness |",
        "|---|---|---|---|---|---|",
    ]
    for arm, stats in sorted(
        per_arm.items(), key=lambda kv: _sort_key(kv[1].get("avg_file_f1"))
    ):
        lines.append(
            f"| {arm} | {stats.get('n', 0)} "
            f"| {_fmt(stats.get('avg_file_f1'))} "
            f"| {_fmt(stats.get('avg_line_f1'))} "
            f"| {_fmt(stats.get('avg_citation_validity_rate'))} "
            f"| {_fmt(stats.get('avg_citation_compactness'))} |"
        )

    comparisons = summary.get("comparisons", {})
    if comparisons:
        lines += ["", "## Deltas vs baseline", ""]
        lines += ["| arm | baseline | file F1 Δ | line F1 Δ |", "|---|---|---|---|"]
        for arm, cmp_row in comparisons.items():
            lines.append(
                f"| {arm} | {cmp_row.get('baseline_arm')} "
                f"| {_fmt_delta(cmp_row.get('file_f1_delta'))} "
                f"| {_fmt_delta(cmp_row.get('line_f1_delta'))} |"
            )
    lines.append("")
    return "\n".join(lines)


def render_exploration_metrics(artifact: dict[str, Any]) -> str:
    """Markdown trajectory/token panel from a ``task_runs.v1`` artifact.

    Surfaces only rows that carry an ``exploration_metrics`` block; runs with no
    exploration telemetry are omitted (mirroring how the block itself is only
    emitted when there is signal).
    """
    rows = [
        row
        for row in artifact.get("results", [])
        if isinstance(row.get("metrics", {}).get("exploration_metrics"), dict)
    ]
    lines = ["# Exploration trajectory & token cost", ""]
    if not rows:
        return "\n".join(lines + ["_No exploration telemetry in this run._", ""])

    lines += [
        "| task | harness | pre-edit calls | repeated-read | "
        "broad/after-subagent | main tok | full tok |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        em = row["metrics"]["exploration_metrics"]
        lines.append(
            f"| {row.get('task')} | {row.get('harness')} "
            f"| {_int(em.get('pre_edit_tool_calls'))} "
            f"| {_fmt(em.get('repeated_read_ratio'))} "
            f"| {_int(em.get('broad_search_count'))}/"
            f"{_int(em.get('broad_search_after_subagent_count'))} "
            f"| {_int(em.get('main_agent_tokens'))} "
            f"| {_int(em.get('full_system_tokens'))} |"
        )
    lines.append("")
    return "\n".join(lines)


def _sort_key(value: Any) -> float:
    # Highest file-F1 first; None sinks to the bottom.
    return -value if isinstance(value, (int, float)) else 1.0


def _fmt(value: Any) -> str:
    return f"{value:.3f}" if isinstance(value, (int, float)) else "n/a"


def _fmt_delta(value: Any) -> str:
    return f"{value:+.3f}" if isinstance(value, (int, float)) else "n/a"


def _int(value: Any) -> str:
    return str(value) if isinstance(value, int) else "n/a"
