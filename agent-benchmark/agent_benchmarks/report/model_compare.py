"""Multi-model comparison report generation.

Public API
----------
check_run_consistency(runs, group_name)
    Validate a list of (run_id, run_data) pairs before comparison.
    Raises SystemExit on hard errors; returns a list of warning strings.

extract_scores(run_data, force_treatment_arm=None)
    Extract per-question scores from an arms JSON artifact.

generate_combined_report(regular_runs, golden_runs, run_ids, out_path, treatment_arm=None)
    Write a Markdown comparison report to *out_path*.

generate_section_report(runs, run_ids, section_name, treatment_arm=None)
    Return a list of Markdown lines for one question-set section (regular or golden).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from scipy import stats as sp_stats

    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    from zoneinfo import ZoneInfo

    _TZ = ZoneInfo("America/Los_Angeles")
except ImportError:
    _TZ = None


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_run(path: str) -> dict[str, Any]:
    """Load a judged arms JSON file.  Raises SystemExit with a clear message on failure."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise SystemExit(f"Error: File not found: {path}") from exc
    except PermissionError as exc:
        raise SystemExit(f"Error: Permission denied reading {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Error: Invalid JSON in {path}: {exc}") from exc


def normalize_difficulty(difficulty: Any) -> str:
    """Normalize difficulty to string format.

    Handles both string format ("easy"/"medium"/"hard") and numeric format (1/2/3).
    Returns normalized string or "unknown" if unrecognized.
    """
    if isinstance(difficulty, str):
        # Already string format - return as-is (lowercased for consistency)
        return difficulty.lower()
    elif isinstance(difficulty, int):
        # Numeric format: 1=easy, 2=medium, 3=hard
        mapping = {1: "easy", 2: "medium", 3: "hard"}
        return mapping.get(difficulty, "unknown")
    else:
        return "unknown"


# ---------------------------------------------------------------------------
# Consistency validation
# ---------------------------------------------------------------------------


def check_run_consistency(
    runs: list[tuple[str, dict]],
    group_name: str,
) -> list[str]:
    """Check runs for consistency problems; return warning strings.

    Hard errors (different ``baseline_arm``) raise ``SystemExit`` immediately.
    Soft warnings (hash mismatch, identical models) are collected and returned.
    """
    if len(runs) < 2:
        return []

    warnings: list[str] = []

    # 1. baseline_arm must match across all runs in the group
    baseline_arms = {run_id: data.get("baseline_arm", "") for run_id, data in runs}
    unique_baselines = set(baseline_arms.values())
    if len(unique_baselines) > 1:
        detail = ", ".join(f"{rid}={arm}" for rid, arm in baseline_arms.items())
        raise SystemExit(
            f"Error [{group_name}]: runs have different baseline_arm values ({detail}). "
            "Comparing runs with different baselines produces meaningless deltas."
        )

    # 2. question_set_hash — warn if present in all runs but diverges
    hashes = {
        run_id: data["question_set_hash"]
        for run_id, data in runs
        if "question_set_hash" in data
    }
    if len(hashes) == len(runs) and len(set(hashes.values())) > 1:
        detail = ", ".join(f"{rid}={h[:8]}" for rid, h in hashes.items())
        warnings.append(
            f"Warning [{group_name}]: question_set_hash differs across runs ({detail}). "
            "Runs may be based on different question sets; common-question intersection "
            "will still be used but results may not be directly comparable."
        )

    # 3. identical model+provider across all runs likely means duplicate runs
    models = [(data.get("model", ""), data.get("provider", "")) for _, data in runs]
    if len(set(models)) == 1:
        m, p = models[0]
        warnings.append(
            f"Warning [{group_name}]: all runs share the same model '{m}' ({p}). "
            "Did you mean to compare different models?"
        )

    return warnings


# ---------------------------------------------------------------------------
# Score extraction
# ---------------------------------------------------------------------------


def extract_scores(
    run_data: dict,
    force_treatment_arm: str | None = None,
) -> list[dict]:
    """Extract question-level scores from an arms artifact.

    Parameters
    ----------
    run_data:
        Parsed arms JSON artifact (``arms.v1`` schema or legacy format).
    force_treatment_arm:
        When given, only scores for this arm are used as the treatment.
        Raises ``SystemExit`` if the arm is absent.
        When ``None``, the single non-baseline arm is auto-selected; raises
        ``SystemExit`` if there is more than one non-baseline arm (ambiguous).
    """
    scores = []

    # New format: scores live inside top-level "evaluations"
    if "evaluations" in run_data:
        baseline_arm = run_data.get("baseline_arm")
        if not isinstance(baseline_arm, str) or not baseline_arm:
            return []

        for evaluation in run_data["evaluations"]:
            qid = evaluation.get("question_id")
            if not qid:
                continue
            eval_scores = evaluation.get("scores", {})

            if not isinstance(eval_scores, dict) or not eval_scores:
                continue
            if baseline_arm not in eval_scores:
                continue

            baseline_data = eval_scores.get(baseline_arm, {})
            if not isinstance(baseline_data, dict):
                continue
            baseline_score = baseline_data.get("aggregate")

            non_baseline_arms = [
                arm for arm in eval_scores
                if arm != baseline_arm and isinstance(eval_scores[arm], dict)
            ]

            if force_treatment_arm is not None:
                if force_treatment_arm not in eval_scores:
                    raise SystemExit(
                        f"Error: --treatment-arm '{force_treatment_arm}' not found in "
                        f"question '{qid}'. Available arms: {list(eval_scores.keys())}"
                    )
                target_arm = force_treatment_arm
            else:
                if len(non_baseline_arms) > 1:
                    raise SystemExit(
                        f"Error: run has multiple non-baseline arms {non_baseline_arms} in "
                        f"question '{qid}'. Use --treatment-arm to select one explicitly."
                    )
                target_arm = non_baseline_arms[0] if non_baseline_arms else None

            if target_arm is not None and isinstance(eval_scores.get(target_arm), dict):
                treatment_score = eval_scores[target_arm].get("aggregate")
                treatment_arm = target_arm
            else:
                treatment_score = None
                treatment_arm = None

            if baseline_score is not None and treatment_score is not None:
                scores.append(
                    {
                        "question_id": qid,
                        "question_text": evaluation.get("question_text", ""),
                        "category": evaluation.get("category", ""),
                        "difficulty": normalize_difficulty(evaluation.get("difficulty", "unknown")),
                        "persona": evaluation.get("persona", ""),
                        "without_docs": baseline_score,
                        "with_docs": treatment_score,
                        "delta": treatment_score - baseline_score,
                        "treatment_arm": treatment_arm,
                    }
                )

    # Legacy format: scores live inside per-answer "arms"
    else:
        baseline_arm = run_data.get("baseline_arm")
        if not isinstance(baseline_arm, str) or not baseline_arm:
            return []

        for answer in run_data.get("answers", []):
            qid = answer.get("question_id")
            if not qid:
                continue
            arms = answer.get("arms", {})
            if not isinstance(arms, dict) or baseline_arm not in arms or len(arms) < 2:
                continue

            baseline_eval = arms.get(baseline_arm, {}).get("evaluation", {})
            non_baseline_arms = [a for a in arms if a != baseline_arm]

            if force_treatment_arm is not None:
                if force_treatment_arm not in arms:
                    raise SystemExit(
                        f"Error: --treatment-arm '{force_treatment_arm}' not found in "
                        f"question '{qid}'. Available arms: {list(arms.keys())}"
                    )
                treatment_arm = force_treatment_arm
            else:
                if len(non_baseline_arms) > 1:
                    raise SystemExit(
                        f"Error: run has multiple non-baseline arms {non_baseline_arms} in "
                        f"question '{qid}'. Use --treatment-arm to select one explicitly."
                    )
                treatment_arm = non_baseline_arms[0] if non_baseline_arms else None

            treatment_eval = (
                arms.get(treatment_arm, {}).get("evaluation", {}) if treatment_arm else {}
            )

            baseline_score = baseline_eval.get("aggregate_score")
            treatment_score = treatment_eval.get("aggregate_score")

            if baseline_score is not None and treatment_score is not None:
                scores.append(
                    {
                        "question_id": qid,
                        "question_text": answer.get("question_text", ""),
                        "category": answer.get("category", ""),
                        "difficulty": normalize_difficulty(answer.get("difficulty", "unknown")),
                        "persona": answer.get("persona", ""),
                        "without_docs": baseline_score,
                        "with_docs": treatment_score,
                        "delta": treatment_score - baseline_score,
                        "treatment_arm": treatment_arm,
                    }
                )

    return scores


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _avg(lst: list[float]) -> float:
    return round(sum(lst) / len(lst), 1) if lst else 0.0


def _fmt_delta(d: float | None) -> str:
    if d is None:
        return "N/A"
    if isinstance(d, float):
        d = round(d, 1)
    return f"+{d}" if d > 0 else str(d)


def significance_test(
    with_scores: list[float], without_scores: list[float]
) -> dict | None:
    """Paired t-test, Wilcoxon, and Cohen's d_z (sample SD).  Requires scipy."""
    if len(with_scores) < 5 or not HAS_SCIPY:
        return None

    deltas = [w - wo for w, wo in zip(with_scores, without_scores, strict=True)]
    d_mean = sum(deltas) / len(deltas)
    if len(deltas) < 2:
        return None
    d_std = (sum((x - d_mean) ** 2 for x in deltas) / (len(deltas) - 1)) ** 0.5

    result: dict[str, Any] = {
        "n": len(with_scores),
        "delta_mean": round(d_mean, 2),
        "delta_std": round(d_std, 2),
    }

    t_stat, p_ttest = sp_stats.ttest_rel(with_scores, without_scores)
    result["t_stat"] = round(t_stat, 3)
    result["p_ttest"] = round(p_ttest, 4)

    try:
        _, p_wilcox = sp_stats.wilcoxon(deltas)
        result["p_wilcoxon"] = round(p_wilcox, 4)
    except Exception:
        result["p_wilcoxon"] = None

    result["cohens_d"] = round(d_mean / d_std, 3) if d_std > 0 else 0.0
    result["significant"] = bool(
        p_ttest < 0.05
        and (result["p_wilcoxon"] is None or result["p_wilcoxon"] < 0.05)
    )

    abs_d = abs(result["cohens_d"])
    if abs_d < 0.2:
        result["effect"] = "negligible"
    elif abs_d < 0.5:
        result["effect"] = "small"
    elif abs_d < 0.8:
        result["effect"] = "medium"
    else:
        result["effect"] = "large"

    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_combined_report(
    regular_runs: list[tuple[str, dict]],
    golden_runs: list[tuple[str, dict]],
    run_ids: list[str],
    out_path: str,
    treatment_arm: str | None = None,
) -> None:
    """Write a Markdown comparison report to *out_path*."""
    lines: list[str] = []

    lines += [
        "#  Model Comparison Report",
        f"_Generated: {datetime.now(tz=_TZ).strftime('%Y-%m-%d %H:%M %Z') if _TZ else datetime.now().strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
    ]

    if regular_runs and golden_runs:
        lines += [
            "## Overview",
            "",
            "This report compares models across two question sets:",
            "- **Regular Questions**: standard questions covering getting started, compatibility, performance, and troubleshooting",
            "- **Golden Questions**: scenario-based questions derived from real issues",
            "",
            "---",
            "",
            "# Regular Questions Analysis",
            "",
        ]
        lines += generate_section_report(regular_runs, run_ids, "Regular", treatment_arm)
        lines += [
            "",
            "---",
            "",
            "# Golden Questions Analysis",
            "",
        ]
        lines += generate_section_report(golden_runs, run_ids, "Golden", treatment_arm)

    elif regular_runs:
        lines += generate_section_report(regular_runs, run_ids, "Regular", treatment_arm)

    elif golden_runs:
        lines += generate_section_report(golden_runs, run_ids, "Golden", treatment_arm)

    output = "\n".join(lines)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(output, encoding="utf-8")
    print(f"✅ Report written to {out_path}")


def generate_section_report(
    runs: list[tuple[str, dict]],
    run_ids: list[str],
    section_name: str,
    treatment_arm: str | None = None,
) -> list[str]:
    """Return Markdown lines for one question-set section."""

    # Extract and intersect to common questions only
    all_run_scores_raw: dict[str, list[dict]] = {}
    for run_id, run_data in runs:
        all_run_scores_raw[run_id] = extract_scores(
            run_data, force_treatment_arm=treatment_arm
        )

    question_sets = [
        set(s["question_id"] for s in scores)
        for scores in all_run_scores_raw.values()
    ]
    common_questions = set.intersection(*question_sets) if question_sets else set()

    # All metrics below use the common-question subset exclusively
    all_run_scores: dict[str, list[dict]] = {
        run_id: [
            s for s in all_run_scores_raw.get(run_id, [])
            if s["question_id"] in common_questions
        ]
        for run_id in run_ids
    }

    lines: list[str] = []

    # --- Models Compared ---
    lines += [
        "## Models Compared",
        "| Run ID | Answer model | Judge model |",
        "|---|---|---|",
    ]
    for run_id, run_data in runs:
        model = run_data.get("model", "unknown")
        provider = run_data.get("provider", "unknown")
        judge_model = run_data.get("judge_model", "same")
        judge_provider = run_data.get("judge_provider", provider)
        lines.append(
            f"| **{run_id}** | {model} ({provider}) | {judge_model} ({judge_provider}) |"
        )

    lines += [
        "",
        f"Common questions evaluated: **{len(common_questions)}**",
        "_All summary, significance, ranking, and head-to-head metrics use only this common question set._",
        "",
    ]

    # --- Overall Summary ---
    lines += [
        "## Overall Summary",
        "| Run | N | Context arm | Baseline | Delta | Improved | Degraded |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    summary_stats: dict[str, dict] = {}
    for run_id in run_ids:
        scores = all_run_scores[run_id]
        with_avg = _avg([s["with_docs"] for s in scores])
        without_avg = _avg([s["without_docs"] for s in scores])
        delta_avg = round(with_avg - without_avg, 1)
        improved = sum(1 for s in scores if s["delta"] > 0)
        degraded = sum(1 for s in scores if s["delta"] < 0)
        summary_stats[run_id] = {
            "n": len(scores),
            "with_avg": with_avg,
            "without_avg": without_avg,
            "delta_avg": delta_avg,
            "improved": improved,
            "degraded": degraded,
        }
        lines.append(
            f"| **{run_id}** | {len(scores)} | {with_avg} | {without_avg} | "
            f"**{_fmt_delta(delta_avg)}** | {improved} | {degraded} |"
        )

    lines += [""]

    # --- Statistical Significance ---
    if HAS_SCIPY:
        lines += [
            "## Statistical Significance of Delta (α = 0.05)",
            "_p-values are unadjusted; treat many pairwise comparisons as exploratory. "
            "Significant = t-test < 0.05 and Wilcoxon < 0.05 (or unavailable)._",
            "",
            "| Run | Delta | p (t-test) | p (Wilcoxon) | Cohen's d_z | Effect | Significant? |",
            "|---|---:|---:|---:|---:|---|---|",
        ]
        for run_id in run_ids:
            scores = all_run_scores[run_id]
            sig = significance_test(
                [s["with_docs"] for s in scores],
                [s["without_docs"] for s in scores],
            )
            if sig:
                sig_mark = "✅ Yes" if sig["significant"] else "❌ No"
                p_wilcox = sig["p_wilcoxon"] if sig["p_wilcoxon"] is not None else "N/A"
                lines.append(
                    f"| **{run_id}** | {_fmt_delta(sig['delta_mean'])} | {sig['p_ttest']} | "
                    f"{p_wilcox} | {_fmt_delta(sig['cohens_d'])} | {sig['effect']} | {sig_mark} |"
                )
        lines += [""]

    # --- By Difficulty ---
    difficulty_groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for run_id in run_ids:
        for s in all_run_scores[run_id]:  # already common questions only
            difficulty_groups[s["difficulty"]][run_id].append(s)

    if difficulty_groups:
        header = "| Difficulty | N | " + " | ".join(
            f"{rid} context | {rid} Δ" for rid in run_ids
        ) + " |"
        separator = "|---|---:|" + "|".join([" :---: | :---: "] * len(run_ids)) + "|"
        lines += [
            "## By Difficulty (common questions only)",
            header,
            separator,
        ]
        for diff in ["easy", "beginner", "intermediate", "medium", "advanced", "hard"]:
            if diff not in difficulty_groups:
                continue
            run_data = difficulty_groups[diff]
            n = len(next(iter(run_data.values())))
            row = f"| {diff} | {n} |"
            for run_id in run_ids:
                sc = run_data.get(run_id, [])
                if sc:
                    wa = _avg([s["with_docs"] for s in sc])
                    wo = _avg([s["without_docs"] for s in sc])
                    row += f" {wa} | {_fmt_delta(round(wa - wo, 1))} |"
                else:
                    row += " — | — |"
            lines.append(row)
        lines += [""]

    # --- Head-to-Head ---
    lines += [
        "## Head-to-Head (context arm, common questions)",
        "| Winner | Count | % |",
        "|---|---:|---:|",
    ]
    winner_counts: dict[str, int] = defaultdict(int)
    for qid in common_questions:
        question_scores = {}
        for run_id in run_ids:
            for s in all_run_scores[run_id]:
                if s["question_id"] == qid:
                    question_scores[run_id] = s["with_docs"]
                    break
        if question_scores:
            max_score = max(question_scores.values())
            winners = [rid for rid, score in question_scores.items() if score == max_score]
            if len(winners) == 1:
                winner_counts[winners[0]] += 1
            else:
                winner_counts["tie"] += 1

    total = len(common_questions)
    for run_id in run_ids:
        count = winner_counts.get(run_id, 0)
        pct = round(100 * count / total) if total > 0 else 0
        lines.append(f"| **{run_id}** | {count} | {pct}% |")
    tie_count = winner_counts.get("tie", 0)
    lines.append(f"| tie | {tie_count} | {round(100 * tie_count / total) if total > 0 else 0}% |")
    lines += [""]

    # --- Context-Arm Benefit ---
    lines += [
        "## Context-Arm Benefit — Delta Comparison",
        "_Which model benefits more from the non-baseline treatment arm?_",
        "",
        "| Run | Avg Delta | Questions context helped | Questions context hurt |",
        "|---|---:|---:|---:|",
    ]
    for run_id in run_ids:
        st = summary_stats[run_id]
        n = st["n"]
        helped_pct = round(100 * st["improved"] / n) if n > 0 else 0
        hurt_pct = round(100 * st["degraded"] / n) if n > 0 else 0
        lines.append(
            f"| **{run_id}** | **{_fmt_delta(st['delta_avg'])}** | "
            f"{st['improved']} ({helped_pct}%) | {st['degraded']} ({hurt_pct}%) |"
        )
    lines += [""]

    # --- Model Ranking ---
    lines += [
        "## Model Ranking",
        "",
        "### By absolute quality (context arm)",
        "| Rank | Run | Context-arm avg |",
        "|---:|---|---:|",
    ]
    for rank, (run_id, st) in enumerate(
        sorted(summary_stats.items(), key=lambda x: x[1]["with_avg"], reverse=True), 1
    ):
        lines.append(f"| {rank} | **{run_id}** | {st['with_avg']} |")

    lines += [
        "",
        "### By treatment utilisation (Delta)",
        "| Rank | Run | Delta |",
        "|---:|---|---:|",
    ]
    for rank, (run_id, st) in enumerate(
        sorted(summary_stats.items(), key=lambda x: x[1]["delta_avg"], reverse=True), 1
    ):
        lines.append(f"| {rank} | **{run_id}** | {_fmt_delta(st['delta_avg'])} |")

    lines += [""]
    return lines
