#!/usr/bin/env python3
"""CLI for agent-benchmark: run, compare, report."""

from __future__ import annotations

import argparse

from agent_benchmarks.commands import (
    answers,
    arms,
    baseline,
    benchmark,
    dashboard,
    dataset,
    evaluate,
    explore,
    ingest,
    library,
    orchestrate,
    personas,
    questions,
    report,
    run,
    tasks,
)


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""

    def positive_int(value: str) -> int:
        """Argparse type that rejects non-positive integers."""
        try:
            ivalue = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"expected an integer, got '{value}'") from None
        if ivalue < 1:
            raise argparse.ArgumentTypeError(f"must be >= 1, got {value}")
        return ivalue

    p = argparse.ArgumentParser(prog="agent-benchmark-cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    # Order preserved to keep --help output stable.
    run.register(sub, positive_int)             # run
    orchestrate.register(sub, positive_int)     # evaluate (one-command pipeline)
    run.register_compare(sub, positive_int)     # compare
    baseline.register(sub, positive_int)        # baseline
    report.register(sub, positive_int)          # report
    personas.register(sub, positive_int)        # personas
    questions.register(sub, positive_int)       # questions
    answers.register(sub, positive_int)         # answers
    evaluate.register(sub, positive_int)        # eval
    library.register(sub, positive_int)         # library
    benchmark.register(sub, positive_int)       # benchmark
    dashboard.register(sub, positive_int)       # dashboard
    arms.register(sub, positive_int)            # arms
    tasks.register(sub, positive_int)           # tasks
    explore.register(sub, positive_int)         # explore (ExploreBench, #60)
    dataset.register(sub, positive_int)         # dataset
    ingest.register(sub, positive_int)          # ingest

    return p


def main() -> None:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
