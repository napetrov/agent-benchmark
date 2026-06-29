"""Render matrix-rollup artifacts as Markdown."""

from __future__ import annotations

from typing import Any


def _md_cell(text: Any) -> str:
    return str(text or "").replace("\n", " ").replace("|", r"\|")


def render_matrix_rollup_report(data: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Matrix rollup — {data.get('library_name', '?')}")
    lines.append("")
    lines.append(f"- Cells: {data.get('total_cells', len(data.get('cells', [])))}")
    lines.append(f"- Plugin deltas: {len(data.get('plugin_deltas', []))}")
    lines.append("")

    warnings = data.get("warnings") or []
    for warning in warnings:
        lines.append(f"> Warning: {warning}")
    if warnings:
        lines.append("")

    lines.append("## Cells")
    lines.append("")
    lines.append("| Cell | Model | Harness | Plugins | Artifact |")
    lines.append("| --- | --- | --- | --- | --- |")
    for cell in data.get("cells", []):
        model = f"{cell.get('provider', '?')}/{cell.get('model', '?')}"
        lines.append(
            f"| {_md_cell(cell.get('matrix_cell', '?'))} | "
            f"{_md_cell(model)} | "
            f"{_md_cell(cell.get('harness', '?'))} | "
            f"{_md_cell(cell.get('plugin_set', 'none'))} | "
            f"{_md_cell(cell.get('artifact', '?'))} |"
        )
    lines.append("")

    deltas = data.get("plugin_deltas") or []
    if deltas:
        lines.append("## Plugin Deltas")
        lines.append("")
        lines.append("| Pair | Plugin set | Artifact |")
        lines.append("| --- | --- | --- |")
        for row in deltas:
            lines.append(
                f"| {_md_cell(row.get('baseline_cell', '?'))} -> {_md_cell(row.get('plugin_cell', '?'))} | "
                f"{_md_cell(row.get('plugin_set', '?'))} | {_md_cell(row.get('artifact', '?'))} |"
            )
        lines.append("")

    return "\n".join(lines)
