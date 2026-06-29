"""subjects subcommand group: Phase D scorecards."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_subjects_list(args: argparse.Namespace) -> None:
    """List subject descriptors below a root directory."""
    root = Path(args.subjects_root)
    if not root.exists():
        print(f"No subjects root: {root}")
        return
    paths = sorted([*root.glob("*.toml"), *root.glob("*.json")])
    for path in paths:
        try:
            from agent_benchmarks.subjects import load_subject

            descriptor = load_subject(path)
            print(f"{descriptor.id}\t{descriptor.subject.kind}\t{path}")
        except Exception as exc:
            print(f"{path}\tERROR\t{exc}")


def cmd_subjects_show(args: argparse.Namespace) -> None:
    """Print the normalized subject plan."""
    from agent_benchmarks.subjects.loader import awareness_arm_specs, load_subject, matrix_config, work_arm_specs

    try:
        descriptor = load_subject(args.subject)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error loading subject: {exc}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps({
        "id": descriptor.id,
        "subject": {
            "kind": descriptor.subject.kind,
            "ref": descriptor.subject.ref,
            "members": [member.__dict__ for member in descriptor.subject.members],
        },
        "suite": {
            "products": list(descriptor.suite.products),
            "questions": list(descriptor.suite.questions),
            "tasks": list(descriptor.suite.tasks),
        },
        "baseline": descriptor.baseline,
        "awareness_arm_specs": awareness_arm_specs(descriptor),
        "work_arm_specs": work_arm_specs(descriptor),
        "matrix": matrix_config(descriptor),
    }, indent=2))


def cmd_subjects_run(args: argparse.Namespace) -> None:
    """Run awareness matrix cells for one subject and write a scorecard."""
    from agent_benchmarks.artifacts import load_artifact, save_artifact
    from agent_benchmarks.commands.arms import cmd_arms_matrix_run, _safe_name
    from agent_benchmarks.report.subject_report import render_subject_scorecard
    from agent_benchmarks.subjects import build_subject_scorecard, load_subject
    from agent_benchmarks.subjects.loader import awareness_arm_specs

    try:
        descriptor = load_subject(args.subject)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error loading subject: {exc}", file=sys.stderr)
        sys.exit(1)
    _validate_subject_work_args(descriptor, args)

    out_dir = Path(args.out_dir) if args.out_dir else Path("results/subjects") / _safe_subject_id(descriptor.id)
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = out_dir / "matrix.cells.json"
    matrix_path.write_text(json.dumps(_matrix_config_for_run(descriptor, args), indent=2), encoding="utf-8")
    baseline_arm = _baseline_arm_name(descriptor.baseline, args)
    _validate_unique_awareness_arm_names(awareness_arm_specs(descriptor), args)

    awareness_runs: list[dict] = []
    questions = _questions_for_products(descriptor.suite.products, descriptor.suite.questions)
    _validate_unique_product_output_dirs(descriptor.suite.products)
    for product, questions_path in zip(descriptor.suite.products, questions, strict=True):
        run_dir = out_dir / _safe_name(product)
        rollup_json = run_dir / "matrix-rollup.json"
        rollup_md = run_dir / "matrix-rollup.md"
        run_args = argparse.Namespace(
            product=product,
            questions=questions_path,
            arms=",".join(awareness_arm_specs(descriptor)),
            matrix_cells=str(matrix_path),
            matrix_cell=None,
            out_dir=str(run_dir),
            out_json=str(rollup_json),
            out_md=str(rollup_md),
            plugin_deltas=not args.no_plugin_deltas,
            model=args.model,
            provider=args.provider,
            harness=args.harness,
            plugins="",
            context7_id=args.context7_id,
            baseline_arm=baseline_arm,
            judge=args.judge,
            judge_model=args.judge_model,
            judge_provider=args.judge_provider,
            top_k=args.top_k,
            rerank_threshold=args.rerank_threshold,
            max_iterations=args.max_iterations,
            concurrency=args.concurrency,
        )
        cmd_arms_matrix_run(run_args)
        awareness_runs.append({
            "product": product,
            "questions": questions_path,
            "matrix_rollup": str(rollup_json),
            "rollup": load_artifact("matrix_rollup", rollup_json),
        })

    work_run = _run_subject_work(descriptor, args, out_dir=out_dir)
    scorecard = build_subject_scorecard(
        descriptor,
        awareness_runs=awareness_runs,
        work_run=work_run,
        out_dir=out_dir,
    )
    out_json = Path(args.out_json) if args.out_json else out_dir / "subject-scorecard.json"
    out_md = Path(args.out_md) if args.out_md else out_json.with_suffix(".md")
    save_artifact("subject_scorecard", scorecard, out_json)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_subject_scorecard(scorecard), encoding="utf-8")
    print(f"OK Saved subject scorecard: {out_json}")
    print(f"OK Saved subject report:    {out_md}")


def register(sub, positive_int) -> None:
    """Add the `subjects` subcommand group."""
    subjects_p = sub.add_parser(
        "subjects",
        help="Run Phase D evaluation subjects and scorecards",
    )
    subjects_sub = subjects_p.add_subparsers(dest="subjects_cmd", required=True)

    list_p = subjects_sub.add_parser("list", help="List subject descriptors")
    list_p.add_argument("--subjects-root", default="subjects", dest="subjects_root")
    list_p.set_defaults(func=cmd_subjects_list)

    show_p = subjects_sub.add_parser("show", help="Show normalized subject descriptor")
    show_p.add_argument("subject", help="Subject descriptor path (.toml or .json)")
    show_p.set_defaults(func=cmd_subjects_show)

    run_p = subjects_sub.add_parser("run", help="Run subject awareness matrix and write scorecard")
    run_p.add_argument("subject", help="Subject descriptor path (.toml or .json)")
    run_p.add_argument("--out-dir", default=None, dest="out_dir")
    run_p.add_argument("--out-json", default=None, dest="out_json")
    run_p.add_argument("--out-md", default=None, dest="out_md")
    run_p.add_argument("--model", default="gpt-4o-mini", help=argparse.SUPPRESS)
    run_p.add_argument("--provider", default="openai",
                       choices=["openai", "anthropic", "amazon-bedrock", "google-vertex", "openrouter", "openai-codex"])
    run_p.add_argument("--harness", default="arms-runner", help=argparse.SUPPRESS)
    run_p.add_argument("--context7-id", default=None, dest="context7_id")
    run_p.add_argument("--judge", action="store_true")
    run_p.add_argument("--judge-model", default="gpt-4o-mini", dest="judge_model")
    run_p.add_argument("--judge-provider", default="openai", dest="judge_provider",
                       choices=["openai", "anthropic", "amazon-bedrock", "google-vertex", "openrouter", "openai-codex"])
    run_p.add_argument("--top-k", type=positive_int, default=5, dest="top_k")
    run_p.add_argument("--rerank-threshold", type=float, default=0.3, dest="rerank_threshold")
    run_p.add_argument("--max-iterations", type=positive_int, default=6, dest="max_iterations")
    run_p.add_argument("--concurrency", type=positive_int, default=5)
    run_p.add_argument("--no-plugin-deltas", action="store_true", dest="no_plugin_deltas")
    run_p.add_argument(
        "--work-harnesses",
        default="",
        dest="work_harnesses",
        help=(
            "Comma-separated executable-task harnesses for suite.tasks "
            "(for example: codex,docker-claude-skill:data/skills/x)."
        ),
    )
    run_p.add_argument("--work-baseline-harness", default=None, dest="work_baseline_harness")
    run_p.add_argument("--work-model", default=None, dest="work_model")
    run_p.add_argument("--work-output-dir", default=None, dest="work_output_dir")
    run_p.add_argument("--work-command-template", default=None, dest="work_command_template")
    run_p.add_argument("--work-repeats", type=positive_int, default=1, dest="work_repeats")
    run_p.add_argument(
        "--work-dry-run",
        action="store_true",
        dest="work_dry_run",
        help="Build the task_runs artifact without invoking executable-task agents.",
    )
    run_p.add_argument(
        "--skip-work",
        action="store_true",
        dest="skip_work",
        help="Skip suite.tasks even when the subject descriptor declares them.",
    )
    run_p.set_defaults(func=cmd_subjects_run)


def _questions_for_products(products: tuple[str, ...], questions: tuple[str, ...]) -> list[str]:
    if len(questions) == len(products):
        return list(questions)
    if len(questions) == 1:
        return [questions[0] for _ in products]
    raise ValueError(
        "suite.questions must contain either one shared file or one file per suite.product"
    )


def _validate_unique_product_output_dirs(products: tuple[str, ...]) -> None:
    from agent_benchmarks.commands.arms import _safe_name

    safe_names = [_safe_name(product) for product in products]
    dot_names = [product for product, safe in zip(products, safe_names, strict=True) if safe in {".", ".."}]
    if dot_names:
        raise ValueError(
            "suite.products must not resolve to '.' or '..' output directories: "
            + ", ".join(dot_names)
        )
    collisions = sorted({name for name in safe_names if safe_names.count(name) > 1})
    if collisions:
        details = ", ".join(
            f"{name}: {', '.join(product for product in products if _safe_name(product) == name)}"
            for name in collisions
        )
        raise ValueError(f"suite.products collide after output directory sanitization: {details}")


def _validate_unique_awareness_arm_names(arm_specs: list[str], args: argparse.Namespace) -> None:
    from agent_benchmarks.treatments import create_treatments

    try:
        create_treatments(
            arm_specs,
            top_k=args.top_k,
            rerank_threshold=args.rerank_threshold,
        )
    except ValueError as exc:
        if "Duplicate arm name" not in str(exc):
            raise
        raise ValueError(
            "subject awareness arms resolve to duplicate runtime names; "
            "use a baseline with a distinct treatment kind or split this comparison"
        ) from exc


def _safe_subject_id(subject_id: str) -> str:
    from agent_benchmarks.commands.arms import _safe_name

    safe = _safe_name(subject_id)
    if safe in {".", ".."}:
        raise ValueError("subject.id must not resolve to '.' or '..' output directory")
    return safe


def _matrix_config_for_run(descriptor, args: argparse.Namespace) -> dict:
    """Build matrix config, honoring CLI model/provider when descriptor omitted cells."""
    from agent_benchmarks.subjects.loader import matrix_config

    if descriptor.matrix_cells_explicit:
        return matrix_config(descriptor)
    return {
        "matrix": {
            "cells": [{
                "id": "arms-runner",
                "model": args.model,
                "provider": args.provider,
                "harness": args.harness,
                "plugins": [],
            }]
        }
    }


def _baseline_arm_name(baseline_spec: str, args: argparse.Namespace) -> str:
    """Resolve a baseline treatment spec to its runtime arm name."""
    from agent_benchmarks.treatments import create_treatments

    treatment = create_treatments(
        [baseline_spec],
        top_k=args.top_k,
        rerank_threshold=args.rerank_threshold,
    )[0]
    return treatment.name


def _run_subject_work(descriptor, args: argparse.Namespace, *, out_dir: Path) -> dict | None:
    """Run executable task suites for a subject when explicitly requested."""
    if not descriptor.suite.tasks:
        return None
    if args.skip_work:
        return {
            "status": "skipped",
            "tasks": list(descriptor.suite.tasks),
            "arm_specs": _work_arm_specs(descriptor),
            "warnings": ["suite.tasks skipped by --skip-work"],
        }

    harnesses = [h.strip() for h in args.work_harnesses.split(",") if h.strip()]
    _validate_subject_work_args(descriptor, args)
    if args.work_baseline_harness and args.work_baseline_harness not in harnesses:
        harnesses.insert(0, args.work_baseline_harness)

    from agent_benchmarks.artifacts import save_artifact
    from agent_benchmarks.harnesses import TaskSuiteRunner, load_task
    from agent_benchmarks.report.task_runs_report import render_task_runs_report

    tasks = [load_task(task) for task in descriptor.suite.tasks]
    work_dir = Path(args.work_output_dir) if args.work_output_dir else out_dir / "work"
    task_runs_path = work_dir / "task-runs.json"
    runner = TaskSuiteRunner(
        tasks=tasks,
        harnesses=harnesses,
        model=args.work_model or args.model,
        baseline_harness=args.work_baseline_harness,
        output_root=work_dir,
        command_template=args.work_command_template,
        dry_run=args.work_dry_run,
        repeats=args.work_repeats,
    )
    artifact = runner.run()
    save_artifact("task_runs", artifact, task_runs_path)
    task_runs_md = task_runs_path.with_suffix(".md")
    task_runs_md.parent.mkdir(parents=True, exist_ok=True)
    task_runs_md.write_text(render_task_runs_report(artifact), encoding="utf-8")
    return {
        "status": "run",
        "tasks": list(descriptor.suite.tasks),
        "arm_specs": _work_arm_specs(descriptor),
        "harnesses": harnesses,
        "task_runs": str(task_runs_path),
        "task_report": str(task_runs_md),
        "summary": artifact.get("summary", {}),
    }


def _work_arm_specs(descriptor) -> list[str]:
    from agent_benchmarks.subjects.loader import work_arm_specs

    return work_arm_specs(descriptor)


def _validate_subject_work_args(descriptor, args: argparse.Namespace) -> None:
    if not descriptor.suite.tasks or args.skip_work:
        return
    harnesses = [h.strip() for h in args.work_harnesses.split(",") if h.strip()]
    if not harnesses:
        raise ValueError(
            "suite.tasks declared; pass --work-harnesses <harness[,harness]> "
            "to run them, or --skip-work to leave work.status=skipped"
        )
