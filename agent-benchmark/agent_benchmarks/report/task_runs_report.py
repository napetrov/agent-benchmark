"""Render an executable-task run (``task_runs.v1``) as Markdown.

Mirrors :mod:`agent_benchmarks.report.arms_report` for the Q&A track: takes the
artifact produced by :class:`~agent_benchmarks.harnesses.runner.TaskSuiteRunner`
and renders a headline, a difficulty rollup, the per-harness comparison, a
per-task pass/cost table, and a per-cell answer detail.

The per-cell detail contrasts the verifier verdict with the model's own
self-report (``solver.json.result`` in each cell's ``output_dir``); cells where
the model claimed success yet the verifier scored 0 are the most informative.
Reading ``solver.json`` is best-effort — the report still renders if the cell
directories are gone (the self-report column is just blank).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _is_skill(harness: str) -> bool:
    return "skill" in harness


def _arm(harness: str) -> str:
    return "SKILL" if _is_skill(harness) else "BASE"


def _md_cell(text: str) -> str:
    """Make text safe for a single Markdown table cell."""
    return (text or "").replace("\n", " ").replace("|", r"\|")


def _fmt_cost(v: float | None) -> str:
    return f"${v:.4f}" if isinstance(v, (int, float)) else "—"


def _self_report(output_dir: str | None) -> tuple[str, int | None]:
    """Best-effort (one-line model self-report, num_turns) from solver.json."""
    if not output_dir:
        return "", None
    solver = Path(output_dir) / "solver.json"
    if not solver.is_file():
        return "", None
    try:
        obj = json.loads(solver.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return "", None
    text = (obj.get("result") or "").strip().replace("\n", " ")
    return text[:160], obj.get("num_turns")


def render_task_runs_report(data: dict[str, Any]) -> str:
    """Render a ``task_runs.v1`` artifact as Markdown."""
    lines: list[str] = []
    ph = data.get("summary", {}).get("per_harness", {})
    harnesses = list(ph.keys())
    diff_of = {
        t["name"]: t.get("metadata", {}).get("difficulty", "?")
        for t in data.get("tasks", [])
    }
    rows = data.get("results", [])
    baseline = data.get("baseline_harness")

    lines.append("# Executable task-run report")
    lines.append("")
    lines.append(f"- Model: `{data.get('model', '?')}`")
    lines.append(f"- Repeats: {data.get('repeats', 1)}")
    lines.append(f"- Harnesses: {', '.join(f'`{h}`' for h in harnesses)}")
    lines.append(f"- Baseline: `{baseline}`" if baseline else "- Baseline: —")
    lines.append(f"- Generated: `{data.get('generated_at', '?')}`")
    lines.append("")

    # ── headline ──
    lines.append("## Headline")
    lines.append("")
    lines.append("| Harness | Pass rate | Cost (USD) | Wall (min) | "
                 "Completion tok | Cache read tok | Cost-known |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for h in harnesses:
        s = ph[h]
        c = s.get("cost", {})
        rate = s.get("pass_rate")
        rate_s = "—" if rate is None else f"{rate*100:.2f}% ({s['passed']}/{s['n']})"
        lines.append(
            f"| `{h}` | {rate_s} | {_fmt_cost(c.get('total_cost_usd'))} | "
            f"{s.get('elapsed_sec', 0)/60:.1f} | {c.get('completion_tokens', '—')} | "
            f"{c.get('cache_read_tokens', '—')} | {c.get('cost_known_n', '—')}/{s['n']} |"
        )
    lines.append("")

    # ── difficulty rollup ──
    tasks = sorted({r["task"] for r in rows})
    cell: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"passed": 0, "n": 0, "cost": 0.0, "detail": []}
    )
    for r in rows:
        key = (r["task"], _arm(r["harness"]))
        c = cell[key]
        c["n"] += 1
        c["passed"] += 1 if r.get("passed") else 0
        cost = r.get("metrics", {}).get("cost_usd")
        if isinstance(cost, (int, float)):
            c["cost"] += cost
        claim, turns = _self_report(r.get("output_dir"))
        c["detail"].append({
            "repeat": r.get("repeat", 1), "reward": r.get("reward"),
            "passed": bool(r.get("passed")), "rc": r.get("returncode"),
            "cost": cost, "turns": turns, "claim": claim,
        })

    arms_present = sorted({_arm(h) for h in harnesses})
    lines.append("## Difficulty rollup")
    lines.append("")
    lines.append("| Difficulty | Tasks | " + " | ".join(f"{a} pass" for a in arms_present) + " |")
    lines.append("|-----------|------:|" + "|".join("------:" for _ in arms_present) + "|")
    by_diff: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: {a: [0, 0] for a in arms_present}
    )
    for t in tasks:
        dlv = diff_of.get(t, "?")
        for a in arms_present:
            by_diff[dlv][a][0] += cell[(t, a)]["passed"]
            by_diff[dlv][a][1] += cell[(t, a)]["n"]
    for dlv in sorted(by_diff):
        n_tasks = sum(1 for t in tasks if diff_of.get(t) == dlv)
        cols = []
        for a in arms_present:
            p, n = by_diff[dlv][a]
            cols.append(f"{p}/{n}" if n else "—")
        lines.append(f"| {dlv} | {n_tasks} | " + " | ".join(cols) + " |")
    lines.append("")

    # ── comparison (straight from artifact) ──
    cmp = data.get("summary", {}).get("comparisons", {})
    if cmp:
        lines.append("## Comparison vs baseline")
        lines.append("")
        lines.append("| Harness | Pass-rate Δ | Passed Δ | Op-count Δ | Cost Δ (USD) |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for h, cr in cmp.items():
            prd = cr.get("pass_rate_delta")
            prd_s = f"{prd*100:+.2f} pp" if isinstance(prd, (int, float)) else "—"
            cd = cr.get("cost_delta_usd")
            cd_s = f"{cd:+.4f}" if isinstance(cd, (int, float)) else "—"
            lines.append(f"| `{h}` | {prd_s} | {cr.get('passed_delta', 0):+} | "
                         f"{cr.get('operation_count_delta', 0):+} | {cd_s} |")
        lines.append("")

    # ── per-task pass + cost ──
    lines.append("## Per-task pass + cost")
    lines.append("")
    head = "| Task | Diff | " + " | ".join(
        f"{a} pass | {a} $" for a in arms_present
    ) + " |"
    lines.append(head)
    lines.append("| --- | :---: |" + "|".join(" :---: | ---: " for _ in arms_present) + "|")
    for t in tasks:
        cols = []
        for a in arms_present:
            c = cell[(t, a)]
            cols.append(f"{c['passed']}/{c['n']} | {_fmt_cost(c['cost'])}")
        lines.append(f"| {t} | {diff_of.get(t, '?')} | " + " | ".join(cols) + " |")
    lines.append("")

    # ── per-cell answer detail ──
    lines.append("## Per-cell answer detail")
    lines.append("")
    lines.append("Each repeat: verifier reward, pass/fail, turns, cost, and the model's "
                 "own one-line self-report. ⚠️ marks cells where the model claimed "
                 "success (\"done\") yet the verifier scored 0 — usually correct code "
                 "that missed the performance bar the verifier enforces.")
    lines.append("")
    for t in tasks:
        lines.append(f"### {t} ({diff_of.get(t, '?')})")
        lines.append("")
        lines.append("| Arm | Rep | Reward | Pass | Turns | Cost | Model self-report |")
        lines.append("| --- | :---: | :---: | :---: | :---: | ---: | --- |")
        for a in arms_present:
            for det in sorted(cell[(t, a)]["detail"], key=lambda x: x["repeat"]):
                rw = det["reward"]
                rw_s = f"{rw:g}" if isinstance(rw, (int, float)) else "null"
                claimed = det["claim"] and "done" in det["claim"].lower()
                pass_s = "✅" if det["passed"] else ("❌ ⚠️" if claimed else "❌")
                turns = det["turns"] if det["turns"] is not None else "—"
                claim = det["claim"] or ("(timeout rc124)" if det["rc"] == 124 else "(no result)")
                lines.append(f"| {a} | {det['repeat']} | {rw_s} | {pass_s} | {turns} | "
                             f"{_fmt_cost(det['cost'])} | {_md_cell(claim)} |")
        lines.append("")

    return "\n".join(lines)
