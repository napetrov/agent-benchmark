"""tasks subcommand group: run executable coding tasks through harnesses."""

from __future__ import annotations

import argparse
from pathlib import Path


def cmd_tasks_list(args: argparse.Namespace) -> None:
    from agent_benchmarks.harnesses import discover_tasks

    tasks = discover_tasks(Path(args.tasks_root) if args.tasks_root else None)
    for task in tasks:
        tags = task.metadata.get("tags") or []
        difficulty = task.metadata.get("difficulty", "?")
        print(f"{task.name}\t{difficulty}\t{','.join(tags)}")


def cmd_tasks_harnesses(args: argparse.Namespace) -> None:
    from agent_benchmarks.harnesses import known_harnesses

    for name, description in known_harnesses().items():
        print(f"{name}\t{description}")


def cmd_tasks_run(args: argparse.Namespace) -> None:
    from agent_benchmarks.harnesses import TaskSuiteRunner, discover_tasks, load_task

    root = Path(args.tasks_root) if args.tasks_root else None
    if args.all:
        tasks = discover_tasks(root)
    else:
        task_names = [t.strip() for t in args.tasks.split(",") if t.strip()]
        tasks = [load_task(t, root=root) for t in task_names]
    if not tasks:
        raise SystemExit("No tasks selected. Pass --tasks <name[,name]> or --all.")

    harnesses = [h.strip() for h in args.harnesses.split(",") if h.strip()]
    if not harnesses:
        raise SystemExit("No harnesses selected. Pass --harnesses codex,claude-code.")
    if args.baseline_harness and args.baseline_harness not in harnesses:
        harnesses.insert(0, args.baseline_harness)

    runner = TaskSuiteRunner(
        tasks=tasks,
        harnesses=harnesses,
        model=args.model,
        baseline_harness=args.baseline_harness,
        output_root=Path(args.output_dir),
        command_template=args.command_template,
        dry_run=args.dry_run,
    )
    output = runner.run()

    out_json = Path(args.out_json) if args.out_json else Path(args.output_dir) / "task_runs.json"
    from agent_benchmarks.artifacts import save_artifact
    save_artifact("task_runs", output, out_json)
    print(f"Saved task run artifact: {out_json}")

    for harness, stats in output["summary"]["per_harness"].items():
        rate = stats["pass_rate"]
        rate_s = "n/a" if rate is None else f"{rate:.2%}"
        print(
            f"{harness}: {stats['passed']}/{stats['n']} pass ({rate_s}), "
            f"ops={stats['operation_count']}, elapsed={stats['elapsed_sec']:.2f}s"
        )
    for harness, cmp_row in output["summary"]["comparisons"].items():
        delta = cmp_row["pass_rate_delta"]
        delta_s = "n/a" if delta is None else f"{delta:+.2%}"
        print(f"{harness} vs {cmp_row['baseline_harness']}: pass-rate delta {delta_s}")


def register(sub, positive_int) -> None:
    """Add the `tasks` subcommand group."""

    tasks_p = sub.add_parser(
        "tasks",
        help="Run executable coding tasks through Codex, Claude Code, or terminal-bench harnesses",
    )
    tasks_sub = tasks_p.add_subparsers(dest="tasks_cmd", required=True)

    list_p = tasks_sub.add_parser("list", help="List terminal-bench task metadata")
    list_p.add_argument("--tasks-root", default=None)
    list_p.set_defaults(func=cmd_tasks_list)

    harnesses_p = tasks_sub.add_parser("harnesses", help="List known coding harness aliases")
    harnesses_p.set_defaults(func=cmd_tasks_harnesses)

    run_p = tasks_sub.add_parser("run", help="Run selected tasks through one or more harnesses")
    group = run_p.add_mutually_exclusive_group(required=True)
    group.add_argument("--tasks", default="", help="Comma-separated task names or paths")
    group.add_argument("--all", action="store_true", help="Run all discovered tasks")
    run_p.add_argument(
        "--harnesses",
        required=True,
        help="Comma-separated harness ids: codex, claude-code, terminal-bench:<agent>",
    )
    run_p.add_argument("--baseline-harness", default=None, dest="baseline_harness")
    run_p.add_argument("--model", default=None, help="Model ref passed to the harness")
    run_p.add_argument("--tasks-root", default=None)
    run_p.add_argument("--output-dir", default="results/task-runs", dest="output_dir")
    run_p.add_argument("--out-json", default=None, dest="out_json")
    run_p.add_argument(
        "--command-template",
        default=None,
        help=(
            "Override command for every harness. Placeholders: {task_path}, {task}, "
            "{model}, {output_dir}, {prompt}, {prompt_quoted}."
        ),
    )
    run_p.add_argument("--dry-run", action="store_true", help="Build artifact without invoking agents")
    run_p.set_defaults(func=cmd_tasks_run)
