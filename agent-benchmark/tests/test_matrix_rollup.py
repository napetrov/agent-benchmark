"""Tests for matrix cell rollup artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import agent_benchmarks.eval.arm_runner as arm_runner_mod
from agent_benchmarks.artifacts import validate_artifact
from agent_benchmarks.cli import build_parser
from agent_benchmarks.eval.matrix_rollup import build_matrix_rollup, strip_internal_payloads
from agent_benchmarks.report.matrix_rollup_report import render_matrix_rollup_report


def _arms_artifact(matrix_cell: str, plugin_set: str = "none") -> dict:
    plugin_id = "empty" if plugin_set == "none" else "sha"
    return {
        "schema_version": "arms.v1",
        "library_name": "oneTBB",
        "matrix_cell": matrix_cell,
        "model": "m",
        "provider": "openai",
        "harness": "agent",
        "judge_model": "judge-m",
        "judge_provider": "openai",
        "plugin_set": plugin_set,
        "plugin_set_id": f"sha256:{plugin_id}",
        "plugins": [] if plugin_set == "none" else [{"id": "caveman"}],
        "arms": ["baseline", "skill"],
        "baseline_arm": "baseline",
        "total_questions": 1,
        "answers": [
            {
                "question_id": "q1",
                "arms": {
                    "baseline": {"metrics": {"raw_answer_chars": 100, "final_answer_chars": 100}},
                    "skill": {"metrics": {"raw_answer_chars": 120, "final_answer_chars": 120}},
                },
            }
        ],
        "evaluations": [
            {
                "question_id": "q1",
                "scores": {
                    "baseline": {"aggregate": 70},
                    "skill": {"aggregate": 80 if plugin_set == "none" else 76},
                },
            }
        ],
        "summary": {"per_arm": {"baseline": {"avg_aggregate": 70.0, "n": 1}}},
        "cost_summary": {
            "baseline": {"completion_tokens": 20},
            "skill": {"completion_tokens": 40 if plugin_set == "none" else 30},
        },
    }


def test_build_matrix_rollup_pairs_plugin_cells(tmp_path: Path):
    baseline = _arms_artifact("agent-none")
    plugin = _arms_artifact("agent-caveman", "caveman:full")

    rollup = build_matrix_rollup(
        library_name="oneTBB",
        cell_artifacts=[
            ("agent-none", tmp_path / "agent-none.json", baseline),
            ("agent-caveman", tmp_path / "agent-caveman.json", plugin),
        ],
        out_dir=tmp_path,
    )
    persisted = strip_internal_payloads(rollup)

    validate_artifact("matrix_rollup", persisted)
    assert persisted["total_cells"] == 2
    assert persisted["plugin_deltas"][0]["baseline_cell"] == "agent-none"
    assert persisted["plugin_deltas"][0]["plugin_cell"] == "agent-caveman"
    assert "_artifact_payload" not in persisted["plugin_deltas"][0]


def test_matrix_rollup_report_lists_cells_and_deltas(tmp_path: Path):
    rollup = strip_internal_payloads(build_matrix_rollup(
        library_name="oneTBB",
        cell_artifacts=[
            ("agent-none", tmp_path / "agent-none.json", _arms_artifact("agent-none")),
            (
                "agent-caveman",
                tmp_path / "agent-caveman.json",
                _arms_artifact("agent-caveman", "caveman:full"),
            ),
        ],
        out_dir=tmp_path,
    ))

    md = render_matrix_rollup_report(rollup)

    assert "# Matrix rollup" in md
    assert "`agent-none` -> `agent-caveman`" in md


def test_arms_matrix_run_parser_accepts_required_args():
    args = build_parser().parse_args([
        "arms",
        "matrix-run",
        "--product",
        "oneTBB",
        "--questions",
        "questions.json",
        "--arms",
        "baseline,docs",
        "--matrix-cells",
        "matrix.json",
    ])

    assert args.arms_cmd == "matrix-run"
    assert args.matrix_cells == "matrix.json"
    assert args.plugin_deltas is True


def test_arms_matrix_run_writes_cells_rollup_and_plugin_delta(tmp_path: Path, monkeypatch):
    def fake_call(prompt, model, provider="openai", api_key=None, system=None, **kw):
        return "short answer" if system else "longer baseline answer", {
            "prompt_tokens": 10,
            "completion_tokens": 5 if system else 8,
            "total_tokens": 15 if system else 18,
        }

    monkeypatch.setattr(arm_runner_mod, "llm_call_with_usage", fake_call)
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{"id": "q1", "question": "How?"}]), encoding="utf-8")
    matrix = tmp_path / "matrix.json"
    matrix.write_text(
        json.dumps({
            "matrix": {
                "cells": [
                    {
                        "name": "agent-none",
                        "model": "m",
                        "provider": "openai",
                        "harness": "agent",
                        "plugins": [],
                    },
                    {
                        "name": "agent-caveman",
                        "model": "m",
                        "provider": "openai",
                        "harness": "agent",
                        "plugins": ["plugin:caveman"],
                    },
                ]
            }
        }),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    args = build_parser().parse_args([
        "arms",
        "matrix-run",
        "--product",
        "oneTBB",
        "--questions",
        str(questions),
        "--arms",
        "baseline",
        "--matrix-cells",
        str(matrix),
        "--out-dir",
        str(out_dir),
    ])

    args.func(args)

    assert (out_dir / "agent-none.json").is_file()
    assert (out_dir / "agent-caveman.json").is_file()
    assert (out_dir / "matrix-rollup.json").is_file()
    assert (out_dir / "plugin-delta-agent-none-to-agent-caveman.json").is_file()
