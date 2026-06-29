"""Markdown rendering for subject scorecards."""

from __future__ import annotations


def render_subject_scorecard(scorecard: dict) -> str:
    """Render a compact human-readable subject scorecard."""
    subject = scorecard.get("subject", {})
    suite = scorecard.get("suite", {})
    lines = [
        f"# Subject scorecard: {subject.get('id', 'unknown')}",
        "",
        f"- Kind: `{subject.get('kind')}`",
        f"- Ref: `{subject.get('ref')}`",
        f"- Baseline: `{scorecard.get('baseline')}`",
        f"- Products: {', '.join(suite.get('products', [])) or 'n/a'}",
        f"- Questions: {', '.join(suite.get('questions', [])) or 'n/a'}",
        "",
        "## Awareness runs",
    ]
    runs = scorecard.get("awareness", {}).get("runs", [])
    if runs:
        for run in runs:
            lines.append(
                f"- `{run.get('product')}` / `{run.get('questions')}` -> `{run.get('matrix_rollup')}`"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Cells"])
    cells = scorecard.get("cells", [])
    if cells:
        lines.append("| Product | Cell | Harness | Plugins | Artifact |")
        lines.append("| --- | --- | --- | --- | --- |")
        for cell in cells:
            lines.append(
                "| "
                f"{cell.get('product', '')} | "
                f"{cell.get('matrix_cell', '')} | "
                f"{cell.get('harness', '')} | "
                f"{cell.get('plugin_set', 'none')} | "
                f"`{cell.get('artifact', '')}` |"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Plugin deltas"])
    deltas = scorecard.get("plugin_deltas", [])
    if deltas:
        for row in deltas:
            lines.append(
                f"- `{row.get('baseline_cell')}` -> `{row.get('plugin_cell')}`: `{row.get('artifact')}`"
            )
    else:
        lines.append("- none")

    warnings = scorecard.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)

    return "\n".join(lines) + "\n"
