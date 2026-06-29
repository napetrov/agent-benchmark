"""arms subcommand group: run (N-way treatment comparison)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_arms_run(args: argparse.Namespace) -> None:
    """Run an N-arm treatment comparison and optionally judge it."""
    try:
        specs = _parse_arm_specs(args.arms)
        questions = _load_questions(args.questions)
        _apply_named_matrix_cell(args)
        output = _build_arms_output(args, specs, questions)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error building arms/plugins: {exc}", file=sys.stderr)
        sys.exit(1)

    out_json = Path(args.out_json) if args.out_json else Path(f"results/arms/{args.product}.json")
    out_md = Path(args.out_md) if args.out_md else Path(f"results/arms/{args.product}.md")
    _save_arms_output(output, out_json, out_md)

    if output.get("summary", {}).get("per_arm"):
        print("\nSummary (avg aggregate):")
        for arm, stats in output["summary"]["per_arm"].items():
            avg = stats.get("avg_aggregate")
            delta = stats.get("delta_vs_baseline")
            avg_s = "n/a" if avg is None else f"{avg:.1f}"
            delta_s = "" if (delta is None or arm == args.baseline_arm) else f" (delta {delta:+.1f})"
            print(f"  {arm:<24} {avg_s}{delta_s}")


def cmd_arms_matrix_run(args: argparse.Namespace) -> None:
    """Run every cell in a matrix.cells descriptor and write a rollup."""
    from agent_benchmarks.artifacts import save_artifact
    from agent_benchmarks.eval.cells import load_matrix_cells
    from agent_benchmarks.eval.matrix_rollup import build_matrix_rollup, strip_internal_payloads
    from agent_benchmarks.report.matrix_rollup_report import render_matrix_rollup_report
    from agent_benchmarks.report.plugin_delta_report import render_plugin_delta_report

    try:
        specs = _parse_arm_specs(args.arms)
        questions = _load_questions(args.questions)
        cells = load_matrix_cells(args.matrix_cells)
        _validate_unique_cell_filenames(cells)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error loading matrix run inputs: {exc}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out_dir) if args.out_dir else Path(f"results/arms/{args.product}-matrix")
    out_dir.mkdir(parents=True, exist_ok=True)
    cell_artifacts = []
    for cell in cells:
        cell_args = argparse.Namespace(**vars(args))
        _apply_matrix_cell(cell_args, cell)
        safe_name = _safe_name(cell.name)
        out_json = out_dir / f"{safe_name}.json"
        out_md = out_dir / f"{safe_name}.md"
        try:
            output = _build_arms_output(cell_args, specs, questions)
        except (ValueError, FileNotFoundError) as exc:
            print(f"Error running matrix cell {cell.name!r}: {exc}", file=sys.stderr)
            sys.exit(1)
        _save_arms_output(output, out_json, out_md)
        cell_artifacts.append((cell.name, out_json, output))

    rollup = build_matrix_rollup(
        library_name=args.product,
        cell_artifacts=cell_artifacts,
        out_dir=out_dir,
        compute_plugin_deltas=args.plugin_deltas,
    )
    for row in rollup.get("plugin_deltas", []):
        payload = row.get("_artifact_payload")
        if not payload:
            continue
        delta_json = Path(row["artifact"])
        save_artifact("plugin_delta", payload, delta_json)
        delta_md = delta_json.with_suffix(".md")
        delta_md.write_text(render_plugin_delta_report(payload), encoding="utf-8")
        print(f"OK Saved plugin delta:    {delta_json}")

    persisted = strip_internal_payloads(rollup)
    out_json = Path(args.out_json) if args.out_json else out_dir / "matrix-rollup.json"
    out_md = Path(args.out_md) if args.out_md else out_json.with_suffix(".md")
    save_artifact("matrix_rollup", persisted, out_json)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_matrix_rollup_report(persisted), encoding="utf-8")
    print(f"OK Saved matrix rollup:   {out_json}")
    print(f"OK Saved matrix report:   {out_md}")


def cmd_arms_plugin_delta(args: argparse.Namespace) -> None:
    """Compare paired no-plugin/plugin arms artifacts."""
    from agent_benchmarks.artifacts import load_artifact, save_artifact
    from agent_benchmarks.eval.plugin_delta import PluginDeltaError, compare_plugin_runs
    from agent_benchmarks.report.plugin_delta_report import render_plugin_delta_report

    try:
        baseline = load_artifact("arms", Path(args.baseline_json))
        plugin = load_artifact("arms", Path(args.plugin_json))
        output = compare_plugin_runs(baseline, plugin)
    except (PluginDeltaError, ValueError, FileNotFoundError) as exc:
        print(f"Error computing plugin delta: {exc}", file=sys.stderr)
        sys.exit(1)

    out_json = Path(args.out_json) if args.out_json else Path("results/arms/plugin_delta.json")
    save_artifact("plugin_delta", output, out_json)
    print(f"OK Saved plugin delta: {out_json}")

    out_md = Path(args.out_md) if args.out_md else out_json.with_suffix(".md")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_plugin_delta_report(output), encoding="utf-8")
    print(f"OK Saved plugin delta report: {out_md}")

    print(
        f"Plugin delta: {output['baseline_plugin_set']} -> {output['plugin_set']} "
        f"({output['harness']}, {output['provider']}/{output['model']})"
    )
    for arm, row in output.get("score_deltas", {}).items():
        delta = row.get("aggregate_delta")
        delta_s = "n/a" if delta is None else f"{delta:+.1f}"
        print(f"  {arm:<24} judge delta {delta_s}, n={row.get('n', 0)}")


def register(sub, positive_int) -> None:
    """Add the `arms` subcommand group."""
    arms_p = sub.add_parser(
        "arms",
        help="Compare context-augmentation treatments (docs, MCP, skills, agent profiles)",
    )
    arms_sub = arms_p.add_subparsers(dest="arms_cmd", required=True)

    arms_run_p = arms_sub.add_parser(
        "run",
        help="Run an N-arm comparison and (optionally) judge it",
    )
    arms_run_p.add_argument("--product", required=True, help="Product name (e.g., oneTBB)")
    arms_run_p.add_argument("--questions", required=True, help="Path to questions JSON file")
    arms_run_p.add_argument(
        "--arms", required=True,
        help="Comma-separated arm specs. Examples: "
             "'baseline,docs', 'baseline,docs:local:./docs,profile:data/agent_profiles/concise_expert.md', "
             "'baseline,mcp:http=https://mcp.context7.com/mcp,skill:data/skills/onetbb-quickstart'",
    )
    arms_run_p.add_argument("--model", default="gpt-4o-mini", help="LLM for answering")
    arms_run_p.add_argument("--provider", default="openai",
                            choices=["openai", "anthropic", "amazon-bedrock", "google-vertex", "openrouter", "openai-codex"])
    arms_run_p.add_argument("--harness", default="arms-runner",
                            help="Execution harness label stamped into output (default: arms-runner)")
    arms_run_p.add_argument("--plugins", default="",
                            help="Comma-separated plugin refs, e.g. 'plugin:caveman' or 'plugin:caveman:ultra'")
    arms_run_p.add_argument("--matrix-cells", default=None, dest="matrix_cells",
                            help="JSON file containing matrix.cells descriptors")
    arms_run_p.add_argument("--matrix-cell", default=None, dest="matrix_cell",
                            help="Named matrix cell to run from --matrix-cells")
    arms_run_p.add_argument("--context7-id", default=None, dest="context7_id",
                            help="Explicit library id for doc/MCP arms (skips resolution)")
    arms_run_p.add_argument("--baseline-arm", default="baseline", dest="baseline_arm",
                            help="Arm name used as the delta baseline (default: baseline)")
    arms_run_p.add_argument("--judge", action="store_true",
                            help="Also score each arm with the LLM-as-judge")
    arms_run_p.add_argument("--judge-model", default="gpt-4o-mini", dest="judge_model")
    arms_run_p.add_argument("--judge-provider", default="openai", dest="judge_provider",
                            choices=["openai", "anthropic", "amazon-bedrock", "google-vertex", "openrouter", "openai-codex"])
    arms_run_p.add_argument("--top-k", type=positive_int, default=5, dest="top_k",
                            help="Docs to retrieve before reranking, for doc/MCP arms (default: 5)")
    arms_run_p.add_argument("--rerank-threshold", type=float, default=0.3, dest="rerank_threshold")
    arms_run_p.add_argument("--max-iterations", type=positive_int, default=6, dest="max_iterations",
                            help="Max tool-call rounds for agentic arms (agent:/skill-agent:, default: 6)")
    arms_run_p.add_argument("--concurrency", type=positive_int, default=5)
    arms_run_p.add_argument("--out-json", default=None, dest="out_json",
                            help="Output JSON path (default: results/arms/{product}.json)")
    arms_run_p.add_argument("--out-md", default=None, dest="out_md",
                            help="Output Markdown report path (default: results/arms/{product}.md)")
    arms_run_p.set_defaults(func=cmd_arms_run)

    matrix_run_p = arms_sub.add_parser(
        "matrix-run",
        help="Run every cell from a matrix.cells descriptor and write a rollup",
    )
    _add_common_run_args(matrix_run_p, positive_int, matrix_required=True)
    matrix_run_p.add_argument("--out-dir", default=None, dest="out_dir",
                              help="Directory for per-cell artifacts (default: results/arms/{product}-matrix)")
    matrix_run_p.add_argument("--out-json", default=None, dest="out_json",
                              help="Matrix rollup JSON path")
    matrix_run_p.add_argument("--out-md", default=None, dest="out_md",
                              help="Matrix rollup Markdown path")
    matrix_run_p.add_argument("--no-plugin-deltas", action="store_false", dest="plugin_deltas",
                              help="Do not compute paired plugin_delta artifacts")
    matrix_run_p.set_defaults(func=cmd_arms_matrix_run, plugin_deltas=True)

    plugin_delta_p = arms_sub.add_parser(
        "plugin-delta",
        help="Compare paired arms artifacts that differ only by plugin set",
    )
    plugin_delta_p.add_argument(
        "--baseline-json", required=True, dest="baseline_json",
        help="arms.v1 artifact for the baseline/no-plugin cell",
    )
    plugin_delta_p.add_argument(
        "--plugin-json", required=True, dest="plugin_json",
        help="arms.v1 artifact for the plugin-enabled cell",
    )
    plugin_delta_p.add_argument("--out-json", default=None, dest="out_json")
    plugin_delta_p.add_argument("--out-md", default=None, dest="out_md")
    plugin_delta_p.set_defaults(func=cmd_arms_plugin_delta)


def _resolve_doc_library_id(treatments, product: str, explicit_id=None):
    """Resolve a library id for the first doc arm, before plugin wrapping."""
    if explicit_id is not None:
        return explicit_id

    from agent_benchmarks.treatments.arms import DocTreatment

    for treatment in treatments:
        unwrapped = getattr(treatment, "inner", treatment)
        if isinstance(unwrapped, DocTreatment):
            try:
                return unwrapped.mcp_client.resolve_library_id(product)
            except Exception:
                return product
    return None


def _add_common_run_args(parser, positive_int, *, matrix_required: bool = False) -> None:
    parser.add_argument("--product", required=True, help="Product name (e.g., oneTBB)")
    parser.add_argument("--questions", required=True, help="Path to questions JSON file")
    parser.add_argument(
        "--arms", required=True,
        help="Comma-separated arm specs. Examples: "
             "'baseline,docs', 'baseline,docs:local:./docs,profile:data/agent_profiles/concise_expert.md', "
             "'baseline,mcp:http=https://mcp.context7.com/mcp,skill:data/skills/onetbb-quickstart'",
    )
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM for answering")
    parser.add_argument("--provider", default="openai",
                        choices=["openai", "anthropic", "amazon-bedrock", "google-vertex", "openrouter", "openai-codex"])
    parser.add_argument("--harness", default="arms-runner",
                        help="Execution harness label stamped into output (default: arms-runner)")
    parser.add_argument("--plugins", default="",
                        help="Comma-separated plugin refs, e.g. 'plugin:caveman' or 'plugin:caveman:ultra'")
    parser.add_argument("--matrix-cells", required=matrix_required, default=None, dest="matrix_cells",
                        help="JSON file containing matrix.cells descriptors")
    if not matrix_required:
        parser.add_argument("--matrix-cell", default=None, dest="matrix_cell",
                            help="Named matrix cell to run from --matrix-cells")
    else:
        parser.set_defaults(matrix_cell=None)
    parser.add_argument("--context7-id", default=None, dest="context7_id",
                        help="Explicit library id for doc/MCP arms (skips resolution)")
    parser.add_argument("--baseline-arm", default="baseline", dest="baseline_arm",
                        help="Arm name used as the delta baseline (default: baseline)")
    parser.add_argument("--judge", action="store_true",
                        help="Also score each arm with the LLM-as-judge")
    parser.add_argument("--judge-model", default="gpt-4o-mini", dest="judge_model")
    parser.add_argument("--judge-provider", default="openai", dest="judge_provider",
                        choices=["openai", "anthropic", "amazon-bedrock", "google-vertex", "openrouter", "openai-codex"])
    parser.add_argument("--top-k", type=positive_int, default=5, dest="top_k",
                        help="Docs to retrieve before reranking, for doc/MCP arms (default: 5)")
    parser.add_argument("--rerank-threshold", type=float, default=0.3, dest="rerank_threshold")
    parser.add_argument("--max-iterations", type=positive_int, default=6, dest="max_iterations",
                        help="Max tool-call rounds for agentic arms (agent:/skill-agent:, default: 6)")
    parser.add_argument("--concurrency", type=positive_int, default=5)


def _parse_arm_specs(raw: str) -> list[str]:
    specs = [s.strip() for s in raw.split(",") if s.strip()]
    if not specs:
        raise ValueError("--arms must list at least one arm spec.")
    return specs


def _load_questions(path: str) -> list[dict]:
    questions_data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(questions_data, dict):
        questions = questions_data.get("questions", questions_data)
    else:
        questions = questions_data
    if not isinstance(questions, list):
        raise ValueError(f"expected a list of questions in {path}")
    print(f"Loaded {len(questions)} questions from {path}")
    return questions


def _apply_named_matrix_cell(args: argparse.Namespace) -> None:
    from agent_benchmarks.eval.cells import load_matrix_cells, select_matrix_cell

    if args.matrix_cells or args.matrix_cell:
        if not args.matrix_cells or not args.matrix_cell:
            raise ValueError("--matrix-cells and --matrix-cell must be passed together")
        _apply_matrix_cell(args, select_matrix_cell(load_matrix_cells(args.matrix_cells), args.matrix_cell))


def _apply_matrix_cell(args: argparse.Namespace, matrix_cell) -> None:
    args.matrix_cell = matrix_cell.name
    args.model = matrix_cell.model
    args.provider = matrix_cell.provider
    args.harness = matrix_cell.harness
    args.plugins = ",".join(matrix_cell.plugin_specs)


def _build_arms_output(args: argparse.Namespace, specs: list[str], questions: list[dict]) -> dict:
    from agent_benchmarks.eval import Judge
    from agent_benchmarks.eval.arm_runner import ArmRunner
    from agent_benchmarks.plugins import (
        create_plugins,
        plugin_set_metadata,
        validate_plugins_for_harness,
        wrap_treatments,
    )
    from agent_benchmarks.treatments import create_treatments

    treatments = create_treatments(specs, top_k=args.top_k, rerank_threshold=args.rerank_threshold)
    library_id = _resolve_doc_library_id(treatments, args.product, args.context7_id)
    plugins = create_plugins([s.strip() for s in args.plugins.split(",") if s.strip()])
    validate_plugins_for_harness(plugins, args.harness)
    treatments = wrap_treatments(treatments, plugins)
    plugin_set = plugin_set_metadata(plugins)
    print(f"Arms: {', '.join(t.name for t in treatments)}")
    if args.matrix_cell:
        print(f"Matrix cell: {args.matrix_cell}")
    if plugin_set["plugins"]:
        print(f"Plugins: {plugin_set['plugin_set']} ({plugin_set['plugin_set_id']})")

    runner = ArmRunner(
        treatments,
        model=args.model,
        provider=args.provider,
        max_iterations=args.max_iterations,
        harness=args.harness,
        plugin_set=plugin_set,
        matrix_cell=args.matrix_cell,
    )
    records = runner.run(
        library_name=args.product,
        questions=questions,
        library_id=library_id,
        concurrency=args.concurrency,
    )

    evaluations = None
    judge = None
    if args.judge:
        judge = Judge(model=args.judge_model, provider=args.judge_provider)
        print("Judging arms...")
        evaluations = runner.judge(
            judge, args.product, records,
            baseline_arm=args.baseline_arm, concurrency=args.concurrency,
        )
    return runner.build_output(
        args.product, records, evaluations=evaluations, baseline_arm=args.baseline_arm,
        judge=judge,
    )


def _save_arms_output(output: dict, out_json: Path, out_md: Path) -> None:
    from agent_benchmarks.eval.arm_runner import ArmRunner
    from agent_benchmarks.report.arms_report import render_arms_report

    ArmRunner.save(output, out_json)
    print(f"OK Saved arms comparison: {out_json}")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_arms_report(output), encoding="utf-8")
    print(f"OK Saved arms report:     {out_md}")


def _validate_unique_cell_filenames(cells) -> None:
    """Reject matrix cells that would overwrite each other's artifacts."""
    seen: dict[str, str] = {}
    for cell in cells:
        safe_name = _safe_name(cell.name)
        if safe_name in seen:
            raise ValueError(
                "matrix cell names collide after filename sanitization: "
                f"{seen[safe_name]!r} and {cell.name!r} both map to {safe_name!r}"
            )
        seen[safe_name] = cell.name


def _safe_name(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in ("-", "_", ".") else "-" for c in name)
    return safe.strip("-") or "cell"
