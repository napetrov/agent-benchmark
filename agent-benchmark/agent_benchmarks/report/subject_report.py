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

    work = scorecard.get("work", {})
    lines.extend(["", "## Work runs"])
    lines.append(f"- Status: `{work.get('status', 'not_run')}`")
    tasks = work.get("tasks", [])
    lines.append(f"- Tasks: {', '.join(f'`{task}`' for task in tasks) if tasks else 'none'}")
    harnesses = work.get("harnesses", [])
    lines.append(f"- Harnesses: {', '.join(f'`{h}`' for h in harnesses) if harnesses else 'none'}")
    if work.get("task_runs"):
        lines.append(f"- Artifact: `{work.get('task_runs')}`")
    if work.get("task_report"):
        lines.append(f"- Report: `{work.get('task_report')}`")
    per_harness = work.get("summary", {}).get("per_harness", {})
    if per_harness:
        lines.append("")
        lines.append("| Harness | Pass rate | Passed | Runs |")
        lines.append("| --- | ---: | ---: | ---: |")
        for harness, stats in per_harness.items():
            rate = stats.get("pass_rate")
            rate_s = "n/a" if rate is None else f"{rate:.2%}"
            lines.append(
                f"| `{harness}` | {rate_s} | {stats.get('passed', 0)} | {stats.get('n', 0)} |"
            )

    warnings = scorecard.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)

    return "\n".join(lines) + "\n"
