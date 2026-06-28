"""Render an N-arm treatment comparison as Markdown."""

from typing import Any, Dict, List


def _md_cell(text: str) -> str:
    """Make text safe for a single Markdown table cell."""
    return (text or "").replace("\n", " ").replace("|", r"\|")


def render_arms_report(data: Dict[str, Any]) -> str:
    """Render the artifact produced by ``ArmRunner.build_output`` as Markdown."""
    lines: List[str] = []
    lib = data.get("library_name", "?")
    arms = data.get("arms", [])
    baseline = data.get("baseline_arm", "baseline")

    lines.append(f"# Treatment-arm comparison — {lib}")
    lines.append("")
    lines.append(f"- Model: `{data.get('provider', '?')}/{data.get('model', '?')}`")
    lines.append(f"- Harness: `{data.get('harness', 'arms-runner')}`")
    if data.get("matrix_cell"):
        lines.append(f"- Matrix cell: `{data['matrix_cell']}`")
    lines.append(f"- Plugin set: `{data.get('plugin_set', 'none')}` (`{data.get('plugin_set_id', '?')}`)")
    lines.append(f"- Arms: {', '.join(f'`{a}`' for a in arms)}")
    lines.append(f"- Baseline arm: `{baseline}`")
    lines.append(f"- Questions: {data.get('total_questions', 0)}")
    lines.append("")

    summary = data.get("summary")
    if summary and summary.get("per_arm"):
        lines.append("## Summary (avg aggregate score, 0–100)")
        lines.append("")
        lines.append("| Arm | Avg | Δ vs baseline | n |")
        lines.append("| --- | ---: | ---: | ---: |")
        for arm in arms:
            stats = summary["per_arm"].get(arm, {})
            avg = stats.get("avg_aggregate")
            delta = stats.get("delta_vs_baseline")
            avg_s = "—" if avg is None else f"{avg:.1f}"
            if arm == baseline:
                delta_s = "(baseline)"
            elif delta is None:
                delta_s = "—"
            else:
                delta_s = f"{delta:+.1f}"
            lines.append(f"| `{arm}` | {avg_s} | {delta_s} | {stats.get('n', 0)} |")
        lines.append("")
    else:
        lines.append("_No evaluations available (answers were not judged)._")
        lines.append("")

    # Cost & latency: per-arm token/cost/latency rollup from the metrics blocks.
    cost_summary = data.get("cost_summary")
    if cost_summary:
        lines.append("## Cost & latency")
        lines.append("")
        lines.append("| Arm | Cost (USD) | Prompt tok | Completion tok | "
                     "Mean latency (s) | Mean TTFT (s) | Cache hit | n |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for arm in arms:
            cs = cost_summary.get(arm)
            if not cs:
                continue
            cost = cs.get("total_cost_usd")
            if cost is None:
                cost_s = "—"
            else:
                cost_s = f"${cost:.4f}"
                # Flag a partial total when some rows lacked litellm pricing.
                known = cs.get("cost_known_n")
                n = cs.get("total_llm_calls", cs.get("n"))
                if known is not None and n is not None and known < n:
                    cost_s += f" ({known}/{n})"
            ttft = cs.get("mean_ttft_sec")
            ttft_s = "—" if ttft is None else f"{ttft:.3f}"
            chr_ = cs.get("cache_hit_ratio")
            chr_s = "—" if chr_ is None else f"{chr_:.1%}"
            lat = cs.get("mean_latency_sec")
            lat_s = "—" if lat is None else f"{lat:.3f}"
            lines.append(
                f"| `{arm}` | {cost_s} | {cs.get('prompt_tokens', 0)} | "
                f"{cs.get('completion_tokens', 0)} | {lat_s} | {ttft_s} | "
                f"{chr_s} | {cs.get('n', 0)} |"
            )
        lines.append("")

    agentic_stats = data.get("agentic_usage_summary") or {}
    if not agentic_stats:
        # Backward-compatible fallback for older artifacts.
        answers = data.get("answers", [])
        fallback: Dict[str, Dict[str, Any]] = {}
        for rec in answers:
            for arm_name, arm in rec.get("arms", {}).items():
                if isinstance(arm, dict) and arm.get("agentic"):
                    s = fallback.setdefault(arm_name, {"calls": [], "iters": []})
                    s["calls"].append(arm.get("tool_call_count", 0))
                    s["iters"].append(arm.get("iterations", 0))
        for arm_name, s in fallback.items():
            n = len(s["calls"]) or 1
            agentic_stats[arm_name] = {
                "n": len(s["calls"]),
                "avg_tool_calls": sum(s["calls"]) / n,
                "tool_use_rate": sum(1 for c in s["calls"] if c > 0) / n,
                "avg_iterations": sum(s["iters"]) / n,
                "skill_load_rate": None,
            }
    if agentic_stats:
        lines.append("## Agentic tool use")
        lines.append("")
        lines.append("| Arm | Tool-use rate | Avg tool calls | Skill-load rate | Avg iterations | n |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        for arm_name, s in agentic_stats.items():
            skill_rate = s.get("skill_load_rate")
            skill_s = "—" if skill_rate is None else f"{skill_rate * 100:.0f}%"
            lines.append(
                f"| `{arm_name}` | {s.get('tool_use_rate', 0) * 100:.0f}% | "
                f"{s.get('avg_tool_calls', 0):.1f} | {skill_s} | "
                f"{s.get('avg_iterations', 0):.1f} | {s.get('n', 0)} |"
            )
        lines.append("")

    evaluations = data.get("evaluations")
    if evaluations:
        lines.append("## Per-question scores")
        lines.append("")
        header = "| Question | " + " | ".join(f"`{a}`" for a in arms) + " |"
        sep = "| --- | " + " | ".join("---:" for _ in arms) + " |"
        lines.append(header)
        lines.append(sep)
        for ev in evaluations:
            q = ev.get("question_text", "")
            q_short = (q[:60] + "…") if len(q) > 60 else q
            q_short = _md_cell(q_short)
            cells = []
            for arm in arms:
                s = ev.get("scores", {}).get(arm)
                if isinstance(s, dict) and isinstance(s.get("aggregate"), (int, float)):
                    cells.append(f"{s['aggregate']:.0f}")
                else:
                    cells.append("—")
            lines.append(f"| {q_short} | " + " | ".join(cells) + " |")
        lines.append("")

    return "\n".join(lines)
