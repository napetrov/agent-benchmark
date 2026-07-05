"""eval subcommand group: score, ragas, panel-score."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_benchmarks.defaults import DEFAULT_CONCURRENCY, DEFAULT_JUDGE_MODEL, DEFAULT_JUDGE_PROVIDER
from agent_benchmarks.utils import normalize_model_ref


def _warn_judge_independence(
    answer_provider: str,
    answer_model: str,
    judge_provider: str,
    judge_model: str,
    context: str = "run",
) -> bool:
    """Emit a non-fatal warning when answer and judge use the same model/provider."""
    same = normalize_model_ref(answer_provider, answer_model) == normalize_model_ref(judge_provider, judge_model)
    if same:
        print(
            "⚠ Evaluator independence warning "
            f"({context}): answer model equals judge model "
            f"[{answer_provider}/{answer_model}] — potential self-referential bias.",
            file=sys.stderr,
        )
    return same


def _run_ragas_eval(answers, output_path, args) -> None:
    """Run RAGAS meta-evaluation and save results alongside answers."""
    try:
        from agent_benchmarks.eval.ragas_eval import RagasEvaluator
    except ImportError as e:
        print(f"\n⚠️  RAGAS not available ({e}). Skipping meta-evaluation.")
        return

    ragas_model = getattr(args, "ragas_model", DEFAULT_JUDGE_MODEL)
    ragas_provider = getattr(args, "ragas_provider", DEFAULT_JUDGE_PROVIDER)

    print(f"\n🔍 Running RAGAS meta-evaluation ({ragas_provider}/{ragas_model})...")
    try:
        evaluator = RagasEvaluator(
            llm_model=ragas_model,
            provider=ragas_provider,
        )
        result = evaluator.evaluate(answers, include_without_docs=True)

        # Save ragas results alongside answers
        import json
        ragas_path = output_path.with_name(output_path.stem + "_ragas.json")
        ragas_path.parent.mkdir(parents=True, exist_ok=True)
        ragas_path.write_text(json.dumps(result.to_dict(), indent=2))

        print(result.format_summary())
        print(f"✅ Saved RAGAS results to {ragas_path}")

    except Exception as exc:
        print(f"\n⚠️  RAGAS evaluation failed: {exc}")


def cmd_eval_panel_score(args: argparse.Namespace) -> None:
    """Score answers using a multi-judge panel (parallel, role-diverse judges)."""
    from agent_benchmarks.eval.panel import JudgePanel, JudgeConfig, DEFAULT_PANEL, JUDGE_ROLES

    # --judge-configs takes priority over --model/--provider/--roles
    # Format: "technical_expert:gpt-4o:openai,developer_advocate:claude-sonnet-4:anthropic,doc_reviewer:gemini-2.0-flash:google"
    if getattr(args, "judge_configs", None):
        judges = []
        for entry in args.judge_configs.split(","):
            parts = entry.strip().split(":")
            if len(parts) != 3:
                print(
                    f"Error: --judge-configs entry '{entry}' must be 'role:model:provider'.",
                    file=sys.stderr,
                )
                sys.exit(1)
            role, model, provider = parts
            if role not in JUDGE_ROLES:
                print(f"Error: unknown role '{role}'. Valid: {list(JUDGE_ROLES)}", file=sys.stderr)
                sys.exit(1)
            judges.append(JudgeConfig(role=role.strip(), model=model.strip(), provider=provider.strip()))
        roles = [j.role for j in judges]
    else:
        roles = [r.strip() for r in args.roles.split(",")] if args.roles else DEFAULT_PANEL
        unknown = [r for r in roles if r not in JUDGE_ROLES]
        if unknown:
            print(f"Error: unknown roles: {unknown}. Valid: {list(JUDGE_ROLES)}", file=sys.stderr)
            sys.exit(1)
        judges = [JudgeConfig(role=r, model=args.model, provider=args.provider) for r in roles]

    panel = JudgePanel(judges=judges, concurrency=args.concurrency)

    try:
        answers_data = json.loads(Path(args.answers).read_text())
    except FileNotFoundError:
        print(f"Error: answers file not found: {args.answers}", file=sys.stderr)
        sys.exit(1)
    answers = answers_data.get("answers", answers_data) if isinstance(answers_data, dict) else answers_data
    if not isinstance(answers, list):
        print(f"Error: expected a list of answers in {args.answers}", file=sys.stderr)
        sys.exit(1)

    answer_model = answers_data.get("model", "unknown") if isinstance(answers_data, dict) else "unknown"
    answer_provider = answers_data.get("provider", "unknown") if isinstance(answers_data, dict) else "unknown"
    if answer_model != "unknown" and answer_provider != "unknown":
        for cfg in judges:
            _warn_judge_independence(
                answer_provider=answer_provider,
                answer_model=answer_model,
                judge_provider=cfg.provider,
                judge_model=cfg.model,
                context="panel-score",
            )

    n_effective = min(len(answers), args.limit) if args.limit else len(answers)
    print(f"Panel evaluation: {n_effective} answers × {len(judges)} judges → {n_effective * len(judges)} LLM calls")
    print(f"Roles: {', '.join(roles)}\nModel: {args.provider}/{args.model}\n")

    output_path = Path(args.output) if args.output else Path(f"eval/{args.product}_panel.json")
    results = panel.evaluate_answers(answers, library_name=args.product,
                                     output_path=output_path,
                                     limit=getattr(args, "limit", None))

    # Summary
    valid = [r for r in results if r.get("with_docs") and r["with_docs"].get("aggregate") is not None]
    if valid:
        mean_score = sum(r["with_docs"]["aggregate"] for r in valid) / len(valid)
        mean_agree = sum(r["with_docs"].get("agreement_score", 1) for r in valid) / len(valid)
        flagged = sum(1 for r in valid if r["with_docs"].get("disagreement_flag", False))
        print(f"\n{'─'*50}")
        print(f"Panel score (context arm): {mean_score:.1f}/100")
        print(f"Mean agreement score:     {mean_agree:.3f}  (1.0 = perfect)")
        print(f"Disagreement flags:       {flagged}/{len(valid)} questions")

    print(f"\n✅ Saved to {output_path}")


def cmd_eval_score(args: argparse.Namespace) -> None:
    """Evaluate answers using LLM-as-judge."""
    from agent_benchmarks.eval import Judge

    # Load answers
    try:
        answers_data = json.loads(Path(args.answers).read_text())
    except FileNotFoundError:
        print(f"Error: answers file not found: {args.answers}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in {args.answers}: {exc}", file=sys.stderr)
        sys.exit(1)

    answers = answers_data.get("answers", answers_data) if isinstance(answers_data, dict) else answers_data
    if not isinstance(answers, list):
        print(f"Error: expected a list of answers in {args.answers}", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded {len(answers)} answers from {args.answers}")

    answer_model = answers_data.get("model", "unknown") if isinstance(answers_data, dict) else "unknown"
    answer_provider = answers_data.get("provider", "unknown") if isinstance(answers_data, dict) else "unknown"
    same_model_warning = False
    if answer_model != "unknown" and answer_provider != "unknown":
        same_model_warning = _warn_judge_independence(
            answer_provider=answer_provider,
            answer_model=answer_model,
            judge_provider=args.judge_provider,
            judge_model=args.judge_model,
            context="eval-score",
        )

    print(f"Evaluating with judge: {args.judge_provider}/{args.judge_model}")

    # Evaluate
    judge = Judge(
        model=args.judge_model,
        provider=args.judge_provider,
        run_metadata={
            "question_model": answers_data.get("question_model", "unknown") if isinstance(answers_data, dict) else "unknown",
            "question_provider": answers_data.get("question_provider", "unknown") if isinstance(answers_data, dict) else "unknown",
            "answer_model": answer_model,
            "answer_provider": answer_provider,
            "judge_model": args.judge_model,
            "judge_provider": args.judge_provider,
            "evaluator_independence_warning": same_model_warning,
        },
    )

    if args.output:
        output_path = Path(args.output)
    elif getattr(args, "run_id", None):
        output_path = Path(f"results/{args.product.lower()}_{args.run_id}/eval/{args.product}.json")
    else:
        output_path = Path(f"eval/{args.product}.json")

    evaluations = judge.evaluate_answers(args.product, answers, output_path=output_path, concurrency=args.concurrency)

    judge.save_evaluations(evaluations, output_path)
    print(f"\n✅ Saved evaluations to {output_path}")


def cmd_eval_ragas(args: argparse.Namespace) -> None:
    """Run standalone RAGAS meta-evaluation on an answers JSON."""
    answers_data = json.loads(Path(args.answers).read_text())
    answers = answers_data.get("answers", answers_data)
    print(f"Loaded {len(answers)} answers from {args.answers}")

    class _Args:
        ragas_model = args.ragas_model
        ragas_provider = args.ragas_provider

    output_path = Path(args.answers)
    _run_ragas_eval(answers, output_path, _Args())


def cmd_eval_grounding(args: argparse.Namespace) -> None:
    """Compute reference-free grounding/citation metrics (no LLM calls)."""
    import json
    from pathlib import Path

    from agent_benchmarks.eval.grounding import evaluate_grounding

    data = json.loads(Path(args.answers).read_text())
    answers = data.get("answers", data) if isinstance(data, dict) else data
    result = evaluate_grounding(answers, threshold=args.threshold)

    summary = result["summary"]
    gs = summary["grounding_score"]
    print(f"Grounding over {summary['n_evaluated']} context-arm answers:")
    if gs["mean"] is not None:
        print(f"  grounding_score : {gs['mean']:.3f}  (95% CI {gs['lo']:.3f}–{gs['hi']:.3f})")
    print(f"  citation_rate   : {summary['citation_rate']:.3f}  (threshold {summary['threshold']})")

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))
        print(f"\n✅ Grounding report saved to {out}")


def register(sub, positive_int) -> None:
    """Add the `eval` subcommand group."""
    # Eval subcommand group
    eval_p = sub.add_parser("eval", help="Evaluate answers")
    eval_sub = eval_p.add_subparsers(dest="eval_cmd", required=True)

    # eval score
    score_p = eval_sub.add_parser("score", help="Score answers using LLM-as-judge")
    score_p.add_argument("--product", required=True, help="Product name (e.g., oneTBB)")
    score_p.add_argument("--answers", required=True, help="Path to answers JSON file")
    score_p.add_argument("--run-id", default=None, dest="run_id",
                         help="Run tag (e.g. gpt4o). Sets output to results/{product}_{run_id}/eval/{product}.json")
    score_p.add_argument("--output", default=None, help="Output file (default: eval/{product}.json)")
    score_p.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL, help="LLM model for judging")
    score_p.add_argument("--judge-provider", default=DEFAULT_JUDGE_PROVIDER, choices=["openai", "anthropic", "azure", "bedrock", "google"])
    score_p.add_argument("--concurrency", type=positive_int, default=DEFAULT_CONCURRENCY, help="Parallel judge calls (default: 5)")
    score_p.set_defaults(func=cmd_eval_score)

    # eval ragas
    ragas_p = eval_sub.add_parser("ragas", help="Run RAGAS meta-evaluation on answers")
    ragas_p.add_argument("--answers", required=True, help="Path to answers JSON file")
    ragas_p.add_argument("--ragas-model", default=DEFAULT_JUDGE_MODEL,
                         help="LLM for RAGAS judge (default: gpt-4o-mini)")
    ragas_p.add_argument("--ragas-provider", default=DEFAULT_JUDGE_PROVIDER, choices=["openai", "anthropic"],
                         help="Provider for RAGAS judge LLM (default: openai)")
    ragas_p.set_defaults(func=cmd_eval_ragas)

    # eval grounding (reference-free, no LLM)
    grounding_p = eval_sub.add_parser(
        "grounding", help="Reference-free grounding/citation metrics with confidence intervals"
    )
    grounding_p.add_argument("--answers", required=True, help="Path to answers JSON file")
    grounding_p.add_argument("--output", default=None, help="Output JSON report path")
    grounding_p.add_argument("--threshold", type=float, default=0.5,
                             help="Grounding score above which an answer counts as grounded (default: 0.5)")
    grounding_p.set_defaults(func=cmd_eval_grounding)

    # eval panel-score
    panel_p = eval_sub.add_parser("panel-score", help="Score answers using a multi-judge panel")
    panel_p.add_argument("--answers", required=True, help="Path to answers JSON file")
    panel_p.add_argument("--product", required=True, help="Product name (e.g., oneTBB)")
    panel_p.add_argument("--output", default=None, help="Output file (default: eval/{product}_panel.json)")
    panel_p.add_argument("--model", default=DEFAULT_JUDGE_MODEL, help="Default LLM model for all judges")
    panel_p.add_argument("--provider", default=DEFAULT_JUDGE_PROVIDER, choices=["openai", "anthropic", "amazon-bedrock", "google-vertex", "openrouter", "openai-codex"])
    panel_p.add_argument("--roles", default=None,
                         help="Comma-separated judge roles (default: technical_expert,developer_advocate,doc_reviewer)")
    panel_p.add_argument(
        "--judge-configs", default=None, dest="judge_configs",
        help=(
            "Per-role model config (overrides --model/--provider/--roles). "
            "Format: 'role:model:provider,...' "
            "e.g. 'technical_expert:gpt-4o:openai,"
            "developer_advocate:claude-sonnet-4:anthropic,"
            "doc_reviewer:gemini-2.0-flash:google'"
        ),
    )
    panel_p.add_argument("--concurrency", type=positive_int, default=6,
                         help="Parallel judge API calls (default: 6)")
    panel_p.add_argument("--limit", type=positive_int, default=None,
                         help="Evaluate only first N answers (useful for testing)")
    panel_p.set_defaults(func=cmd_eval_panel_score)
