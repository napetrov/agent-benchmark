"""Command-level tests for fixed question-set benchmark runs."""

from __future__ import annotations

import argparse

from agent_benchmarks.commands import benchmark
from agent_benchmarks.registry import ProductEntry


class _Registry:
    def get(self, key: str) -> ProductEntry:
        assert key == "onetbb"
        return ProductEntry(
            key="onetbb",
            name="oneTBB",
            description="Threading Building Blocks",
            doc_sources=["local:docs"],
        )


def test_multi_run_reuses_first_run_questions(monkeypatch, tmp_path, capsys):
    calls: list[dict[str, object]] = []

    def fake_run_single_library(entry, **kwargs):
        calls.append(kwargs)
        return {
            "library": entry.key,
            "name": entry.name,
            "status": "ok",
            "result": {
                "steps": {
                    "evaluation": {
                        "summary": {"with_avg": 80.0},
                    }
                }
            },
        }

    monkeypatch.setattr(benchmark, "_load_registry", lambda args: _Registry())
    monkeypatch.setattr(benchmark, "_run_single_library", fake_run_single_library)

    output_dir = tmp_path / "onetbb_eval"
    args = argparse.Namespace(
        library="onetbb",
        output_dir=str(output_dir),
        model="gpt-4o-mini",
        provider="openai",
        judge_model="gpt-4o",
        judge_provider="openai",
        doc_source=None,
        max_tokens=4000,
        force_regen=True,
        concurrency=2,
        questions_from=None,
        multi_run=3,
    )

    benchmark.cmd_benchmark_run(args)

    assert [call["output_dir"] for call in calls] == [
        f"{output_dir}_run1",
        f"{output_dir}_run2",
        f"{output_dir}_run3",
    ]
    assert [call["questions_from"] for call in calls] == [
        None,
        f"{output_dir}_run1",
        f"{output_dir}_run1",
    ]
    assert [call["force_regen"] for call in calls] == [True, False, False]

    captured = capsys.readouterr()
    assert "Multi-run summary (3 runs)" in captured.out
