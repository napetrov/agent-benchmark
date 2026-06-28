"""Tests for Phase D subject descriptors and scorecards."""

from __future__ import annotations

import json
from pathlib import Path

import agent_benchmarks.eval.arm_runner as arm_runner_mod
from agent_benchmarks.artifacts import validate_artifact
from agent_benchmarks.cli import build_parser
from agent_benchmarks.commands.subjects import _baseline_arm_name, _matrix_config_for_run
from agent_benchmarks.report.subject_report import render_subject_scorecard
from agent_benchmarks.subjects import build_subject_scorecard, load_subject
from agent_benchmarks.subjects.loader import awareness_arm_specs, matrix_config, work_arm_specs


def test_load_subject_maps_skill_to_awareness_and_work_arms(tmp_path: Path):
    descriptor_path = tmp_path / "subject.toml"
    descriptor_path.write_text(
        """
[subject]
id = "skill-subject"
kind = "skill"
ref = "data/skills/example"

[suite]
products = ["oneTBB"]
questions = ["questions.json"]
tasks = ["tasks/example"]

baseline = "baseline"

[[matrix.cells]]
id = "agent-none"
model = "m"
provider = "openai"
harness = "agent"
plugins = []
""".strip(),
        encoding="utf-8",
    )

    descriptor = load_subject(descriptor_path)

    assert descriptor.id == "skill-subject"
    assert awareness_arm_specs(descriptor) == ["baseline", "skill:data/skills/example"]
    assert work_arm_specs(descriptor) == ["baseline", "skill-agent:data/skills/example"]
    assert matrix_config(descriptor)["matrix"]["cells"][0]["id"] == "agent-none"


def test_subjects_show_parser_accepts_descriptor():
    args = build_parser().parse_args(["subjects", "show", "subjects/onetbb-quickstart.toml"])

    assert args.cmd == "subjects"
    assert args.subjects_cmd == "show"


def test_mcp_subject_normalizes_transport_prefix(tmp_path: Path):
    descriptor_path = tmp_path / "subject.toml"
    descriptor_path.write_text(
        """
[subject]
id = "mcp-subject"
kind = "mcp"
ref = "mcp:http=https://mcp.context7.com/mcp"

[suite]
products = ["oneTBB"]
questions = ["questions.json"]
""".strip(),
        encoding="utf-8",
    )

    descriptor = load_subject(descriptor_path)

    assert awareness_arm_specs(descriptor) == ["baseline", "mcp:http=https://mcp.context7.com/mcp"]
    assert work_arm_specs(descriptor) == ["baseline", "agent:mcp:http=https://mcp.context7.com/mcp"]


def test_subject_run_default_cell_honors_cli_model_provider(tmp_path: Path):
    descriptor_path = tmp_path / "subject.toml"
    descriptor_path.write_text(
        """
[subject]
id = "docs-subject"
kind = "doc-source"
ref = "local:docs"

[suite]
products = ["oneTBB"]
questions = ["questions.json"]
""".strip(),
        encoding="utf-8",
    )
    descriptor = load_subject(descriptor_path)
    args = build_parser().parse_args([
        "subjects",
        "run",
        str(descriptor_path),
        "--model",
        "custom-model",
        "--provider",
        "openrouter",
    ])

    cell = _matrix_config_for_run(descriptor, args)["matrix"]["cells"][0]

    assert cell["model"] == "custom-model"
    assert cell["provider"] == "openrouter"


def test_subject_run_derives_baseline_arm_name_from_spec(tmp_path: Path):
    docs = tmp_path / "docs.md"
    docs.write_text("# Docs\n", encoding="utf-8")
    args = build_parser().parse_args([
        "subjects",
        "run",
        "subject.toml",
    ])

    assert _baseline_arm_name(f"docs:local:{docs}", args) == "docs"


def test_bundle_with_first_mcp_keeps_later_members(tmp_path: Path):
    descriptor_path = tmp_path / "subject.toml"
    descriptor_path.write_text(
        """
[subject]
id = "bundle-subject"
kind = "bundle"
members = [
  {kind = "mcp", ref = "mcp:http=https://mcp.context7.com/mcp"},
  {kind = "skill", ref = "data/skills/example"},
]

[suite]
products = ["oneTBB"]
questions = ["questions.json"]
""".strip(),
        encoding="utf-8",
    )

    descriptor = load_subject(descriptor_path)

    assert awareness_arm_specs(descriptor) == [
        "baseline",
        "skill:data/skills/example+mcp:http=https://mcp.context7.com/mcp",
    ]


def test_subject_scorecard_validates_and_renders(tmp_path: Path):
    descriptor_path = tmp_path / "subject.toml"
    descriptor_path.write_text(
        """
[subject]
id = "docs-subject"
kind = "doc-source"
ref = "local:docs"

[suite]
products = ["oneTBB"]
questions = ["questions.json"]
""".strip(),
        encoding="utf-8",
    )
    descriptor = load_subject(descriptor_path)
    rollup = {
        "schema_version": "matrix_rollup.v1",
        "library_name": "oneTBB",
        "cells": [
            {
                "matrix_cell": "agent-none",
                "artifact": "out/agent-none.json",
                "model": "m",
                "provider": "openai",
                "harness": "agent",
                "plugin_set": "none",
                "summary": {},
                "cost_summary": {},
            }
        ],
        "plugin_deltas": [],
        "warnings": [],
    }

    scorecard = build_subject_scorecard(
        descriptor,
        awareness_runs=[{
            "product": "oneTBB",
            "questions": "questions.json",
            "matrix_rollup": "out/matrix-rollup.json",
            "rollup": rollup,
        }],
        out_dir=tmp_path,
    )

    validate_artifact("subject_scorecard", scorecard)
    md = render_subject_scorecard(scorecard)
    assert "# Subject scorecard: docs-subject" in md
    assert "`out/matrix-rollup.json`" in md


def test_subject_digest_uses_runtime_root_for_repo_relative_refs(tmp_path: Path, monkeypatch):
    repo_root = tmp_path
    skill_dir = repo_root / "data" / "skills" / "example"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("version one", encoding="utf-8")
    subjects_dir = repo_root / "subjects"
    subjects_dir.mkdir()
    descriptor_path = subjects_dir / "subject.toml"
    descriptor_path.write_text(
        """
[subject]
id = "skill-subject"
kind = "skill"
ref = "data/skills/example"

[suite]
products = ["oneTBB"]
questions = ["questions.json"]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(repo_root)
    descriptor = load_subject(descriptor_path)

    first = build_subject_scorecard(descriptor, awareness_runs=[], out_dir=tmp_path)["subject"]["ref_digest"]
    skill_file.write_text("version two", encoding="utf-8")
    second = build_subject_scorecard(descriptor, awareness_runs=[], out_dir=tmp_path)["subject"]["ref_digest"]

    assert first != second


def test_subjects_run_writes_scorecard(tmp_path: Path, monkeypatch):
    def fake_call(prompt, model, provider="openai", api_key=None, system=None, **kw):
        return "answer", {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }

    monkeypatch.setattr(arm_runner_mod, "llm_call_with_usage", fake_call)
    docs = tmp_path / "docs.md"
    docs.write_text("# oneTBB\nUse parallel_for for loops.\n", encoding="utf-8")
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{"id": "q1", "question": "What API runs loops?"}]), encoding="utf-8")
    descriptor = tmp_path / "subject.toml"
    descriptor.write_text(
        f"""
[subject]
id = "docs-subject"
kind = "doc-source"
ref = "local:{docs}"

[suite]
products = ["oneTBB"]
questions = ["{questions}"]

[[matrix.cells]]
id = "arms-runner"
model = "m"
provider = "openai"
harness = "arms-runner"
plugins = []
""".strip(),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    args = build_parser().parse_args([
        "subjects",
        "run",
        str(descriptor),
        "--out-dir",
        str(out_dir),
    ])

    args.func(args)

    scorecard = json.loads((out_dir / "subject-scorecard.json").read_text(encoding="utf-8"))
    assert scorecard["schema_version"] == "subject_scorecard.v1"
    assert scorecard["subject"]["id"] == "docs-subject"
    assert (out_dir / "oneTBB" / "matrix-rollup.json").is_file()
