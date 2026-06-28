"""Render plugin-delta artifacts as Markdown."""

from __future__ import annotations

from typing import Any, Dict, List


def render_plugin_delta_report(data: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"# Plugin delta — {data.get('library_name', '?')}")
    lines.append("")
    lines.append(f"- Model: `{data.get('provider', '?')}/{data.get('model', '?')}`")
    lines.append(f"- Harness: `{data.get('harness', '?')}`")
    if data.get("judge_model") or data.get("judge_provider"):
        lines.append(f"- Judge: `{data.get('judge_provider', '?')}/{data.get('judge_model', '?')}`")
    lines.append(
        f"- Baseline plugins: `{data.get('baseline_plugin_set', 'none')}` "
        f"(`{data.get('baseline_plugin_set_id', '?')}`)"
    )
    lines.append(
        f"- Plugin set: `{data.get('plugin_set', 'none')}` "
        f"(`{data.get('plugin_set_id', '?')}`)"
    )
    lines.append(f"- Questions: {data.get('total_questions', 0)}")
    lines.append("")

    for warning in data.get("warnings", []):
        lines.append(f"> Warning: {warning}")
    if data.get("warnings"):
        lines.append("")

    score_deltas = data.get("score_deltas") or {}
    if score_deltas:
        lines.append("## Judge score deltas")
        lines.append("")
        lines.append("| Arm | Baseline avg | Plugin avg | Plugin delta | n |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for arm in data.get("arms", []):
            row = score_deltas.get(arm) or {}
            lines.append(
                f"| `{arm}` | {_fmt(row.get('baseline_avg_aggregate'))} | "
                f"{_fmt(row.get('plugin_avg_aggregate'))} | "
                f"{_fmt_signed(row.get('aggregate_delta'))} | {row.get('n', 0)} |"
            )
        lines.append("")

    cost_deltas = data.get("cost_deltas") or {}
    if cost_deltas:
        lines.append("## Cost and token deltas")
        lines.append("")
        lines.append("| Arm | Cost Δ | Prompt tok Δ | Completion tok Δ | Total tok Δ | Latency Δ |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for arm in data.get("arms", []):
            row = cost_deltas.get(arm) or {}
            lines.append(
                f"| `{arm}` | {_fmt_money_delta(_delta(row, 'total_cost_usd'))} | "
                f"{_fmt_signed(_delta(row, 'prompt_tokens'), digits=0)} | "
                f"{_fmt_signed(_delta(row, 'completion_tokens'), digits=0)} | "
                f"{_fmt_signed(_delta(row, 'total_tokens'), digits=0)} | "
                f"{_fmt_signed(_delta(row, 'mean_latency_sec'))} |"
            )
        lines.append("")

    text_deltas = data.get("answer_text_deltas") or {}
    if text_deltas:
        lines.append("## Answer length deltas")
        lines.append("")
        lines.append("| Arm | Raw chars Δ | Final chars Δ |")
        lines.append("| --- | ---: | ---: |")
        for arm in data.get("arms", []):
            row = text_deltas.get(arm) or {}
            lines.append(
                f"| `{arm}` | {_fmt_signed(_delta(row, 'raw_answer_chars'), digits=0)} | "
                f"{_fmt_signed(_delta(row, 'final_answer_chars'), digits=0)} |"
            )
        lines.append("")

    return "\n".join(lines)


def _delta(row: dict, field: str):
    value = row.get(field)
    return value.get("delta") if isinstance(value, dict) else None


def _fmt(value: Any, *, digits: int = 1) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value:.{digits}f}"


def _fmt_signed(value: Any, *, digits: int = 1) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{value:+.{digits}f}"


def _fmt_money_delta(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"${value:+.4f}"
