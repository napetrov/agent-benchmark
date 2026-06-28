"""arms subcommand group: run (N-way treatment comparison)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_arms_run(args: argparse.Namespace) -> None:
    """Run an N-arm treatment comparison and optionally judge it."""
    from agent_benchmarks.treatments import create_treatments
    from agent_benchmarks.eval.arm_runner import ArmRunner
    from agent_benchmarks.report.arms_report import render_arms_report
    from agent_benchmarks.plugins import create_plugins, plugin_set_metadata, wrap_treatments

    specs = [s.strip() for s in args.arms.split(",") if s.strip()]
    if not specs:
        print("Error: --arms must list at least one arm spec.", file=sys.stderr)
        sys.exit(1)

    questions_data = json.loads(Path(args.questions).read_text())
    if isinstance(questions_data, dict):
        questions = questions_data.get("questions", questions_data)
    else:
        questions = questions_data
    if not isinstance(questions, list):
        print(f"Error: expected a list of questions in {args.questions}", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded {len(questions)} questions from {args.questions}")

    try:
        treatments = create_treatments(
            specs, top_k=args.top_k, rerank_threshold=args.rerank_threshold
        )
        library_id = _resolve_doc_library_id(treatments, args.product, args.context7_id)
        plugin_specs = [s.strip() for s in args.plugins.split(",") if s.strip()]
        plugins = create_plugins(plugin_specs)
        treatments = wrap_treatments(treatments, plugins)
        plugin_set = plugin_set_metadata(plugins)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error building arms/plugins: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"Arms: {', '.join(t.name for t in treatments)}")
    if plugin_set["plugins"]:
        print(f"Plugins: {plugin_set['plugin_set']} ({plugin_set['plugin_set_id']})")

    runner = ArmRunner(
        treatments,
        model=args.model,
        provider=args.provider,
        max_iterations=args.max_iterations,
        harness=args.harness,
        plugin_set=plugin_set,
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
        from agent_benchmarks.eval import Judge
        judge = Judge(model=args.judge_model, provider=args.judge_provider)
        print("Judging arms…")
        evaluations = runner.judge(
            judge, args.product, records,
            baseline_arm=args.baseline_arm, concurrency=args.concurrency,
        )

    output = runner.build_output(
        args.product, records, evaluations=evaluations, baseline_arm=args.baseline_arm,
        judge=judge,
    )

    out_json = Path(args.out_json) if args.out_json else Path(f"results/arms/{args.product}.json")
    runner.save(output, out_json)
    print(f"OK Saved arms comparison: {out_json}")

    out_md = Path(args.out_md) if args.out_md else Path(f"results/arms/{args.product}.md")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_arms_report(output), encoding="utf-8")
    print(f"OK Saved arms report:     {out_md}")

    if output.get("summary", {}).get("per_arm"):
        print("\nSummary (avg aggregate):")
        for arm, stats in output["summary"]["per_arm"].items():
            avg = stats.get("avg_aggregate")
            delta = stats.get("delta_vs_baseline")
            avg_s = "n/a" if avg is None else f"{avg:.1f}"
            delta_s = "" if (delta is None or arm == args.baseline_arm) else f" (delta {delta:+.1f})"
            print(f"  {arm:<24} {avg_s}{delta_s}")


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
