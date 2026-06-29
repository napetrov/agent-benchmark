"""Tests for Phase D subject descriptors and scorecards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_benchmarks.eval.arm_runner as arm_runner_mod
from agent_benchmarks.artifacts import validate_artifact
from agent_benchmarks.cli import build_parser
from agent_benchmarks.commands.subjects import (
    _baseline_arm_name,
    _matrix_config_for_run,
    _run_subject_work,
    _safe_subject_id,
    _validate_unique_awareness_arm_names,
    _validate_unique_product_output_dirs,
)
from agent_benchmarks.report.subject_report import render_subject_scorecard
from agent_benchmarks.subjects import build_subject_scorecard, load_subject
from agent_benchmarks.subjects.loader import awareness_arm_specs, matrix_config, work_arm_specs


def test_load_subject_maps_skill_to_awareness_and_work_arms(tmp_path: Path):
    descriptor_path = tmp_path / "subject.toml"
    descriptor_path.write_text(
        """
baseline = "baseline"

[subject]
id = "skill-subject"
kind = "skill"
ref = "data/skills/example"

[suite]
products = ["oneTBB"]
questions = ["questions.json"]
tasks = ["tasks/example"]

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


def test_all_mcp_bundle_is_rejected_until_names_are_unique(tmp_path: Path):
    descriptor_path = tmp_path / "subject.toml"
    descriptor_path.write_text(
        """
[subject]
id = "bundle-subject"
kind = "bundle"
members = [
  {kind = "mcp", ref = "mcp:http=https://mcp.context7.com/a"},
  {kind = "mcp", ref = "mcp:http=https://mcp.context7.com/b"},
]

[suite]
products = ["oneTBB"]
questions = ["questions.json"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="all-MCP bundles are not supported"):
        load_subject(descriptor_path)


def test_subject_rejects_suite_scoped_baseline(tmp_path: Path):
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
baseline = "docs:local:old"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="baseline must be top-level"):
        load_subject(descriptor_path)


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


def test_subject_scorecard_embeds_work_task_run_summary(tmp_path: Path):
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
tasks = ["terminal-bench-tasks/example"]
""".strip(),
        encoding="utf-8",
    )
    descriptor = load_subject(descriptor_path)
    scorecard = build_subject_scorecard(
        descriptor,
        awareness_runs=[],
        out_dir=tmp_path,
        work_run={
            "status": "run",
            "tasks": ["terminal-bench-tasks/example"],
            "arm_specs": ["baseline", "skill-agent:data/skills/example"],
            "harnesses": ["codex"],
            "task_runs": "out/task-runs.json",
            "task_report": "out/task-runs.md",
            "summary": {
                "per_harness": {
                    "codex": {
                        "n": 1,
                        "passed": 0,
                        "pass_rate": 0.0,
                    }
                }
            },
        },
    )

    validate_artifact("subject_scorecard", scorecard)
    assert scorecard["work"]["status"] == "run"
    assert scorecard["work"]["task_runs"] == "out/task-runs.json"
    md = render_subject_scorecard(scorecard)
    assert "## Work runs" in md
    assert "`out/task-runs.json`" in md
    assert "| Harness | Pass rate | Passed | Runs |" in md
    assert "| `codex` | 0.00% | 0 | 1 |" in md


def test_subject_rejects_subject_scoped_baseline(tmp_path: Path):
    descriptor_path = tmp_path / "subject.toml"
    descriptor_path.write_text(
        """
[subject]
id = "docs-subject"
kind = "doc-source"
ref = "local:docs"
baseline = "docs:local:old"

[suite]
products = ["oneTBB"]
questions = ["questions.json"]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="baseline must be top-level"):
        load_subject(descriptor_path)


def test_subject_rejects_empty_top_level_baseline(tmp_path: Path):
    descriptor_path = tmp_path / "subject.toml"
    descriptor_path.write_text(
        """
baseline = ""

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

    with pytest.raises(ValueError, match="baseline must not be empty"):
        load_subject(descriptor_path)


def test_subject_rejects_explicit_empty_matrix_cells(tmp_path: Path):
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

[matrix]
cells = []
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="matrix.cells must contain at least one cell"):
        load_subject(descriptor_path)


def test_subject_rejects_explicit_empty_matrix_table(tmp_path: Path):
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

[matrix]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="matrix must declare cells"):
        load_subject(descriptor_path)


def test_subject_scorecard_hashes_local_baseline_content(tmp_path: Path):
    docs = tmp_path / "old-docs.md"
    docs.write_text("version one", encoding="utf-8")
    descriptor_path = tmp_path / "subject.toml"
    descriptor_path.write_text(
        f"""
baseline = "docs:local:{docs}"

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

    first = build_subject_scorecard(descriptor, awareness_runs=[], out_dir=tmp_path)["baseline_digest"]
    docs.write_text("version two", encoding="utf-8")
    second = build_subject_scorecard(descriptor, awareness_runs=[], out_dir=tmp_path)["baseline_digest"]

    assert first != second


def test_subject_scorecard_hashes_local_baseline_path_with_plus(tmp_path: Path):
    docs = tmp_path / "old+b.md"
    docs.write_text("version one", encoding="utf-8")
    descriptor_path = tmp_path / "subject.toml"
    descriptor_path.write_text(
        f"""
baseline = "docs:local:{docs}"

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

    first = build_subject_scorecard(descriptor, awareness_runs=[], out_dir=tmp_path)["baseline_digest"]
    docs.write_text("version two", encoding="utf-8")
    second = build_subject_scorecard(descriptor, awareness_runs=[], out_dir=tmp_path)["baseline_digest"]

    assert first != second


def test_subjects_reject_colliding_product_output_dirs():
    with pytest.raises(ValueError, match="collide after output directory sanitization"):
        _validate_unique_product_output_dirs(("one/TBB", "one-TBB"))


def test_subjects_reject_dot_only_product_output_dirs():
    with pytest.raises(ValueError, match="must not resolve"):
        _validate_unique_product_output_dirs(("..",))


def test_subjects_reject_duplicate_runtime_arm_names(tmp_path: Path):
    old_docs = tmp_path / "old.md"
    new_docs = tmp_path / "new.md"
    old_docs.write_text("old", encoding="utf-8")
    new_docs.write_text("new", encoding="utf-8")
    args = build_parser().parse_args(["subjects", "run", "subject.toml"])

    with pytest.raises(ValueError, match="duplicate runtime names"):
        _validate_unique_awareness_arm_names(
            [f"docs:local:{old_docs}", f"docs:local:{new_docs}"],
            args,
        )


def test_subjects_default_out_dir_sanitizes_subject_id(tmp_path: Path, monkeypatch):
    def fake_matrix_run(args):
        run_dir = Path(args.out_dir)
        run_dir.mkdir(parents=True)
        (run_dir / "matrix-rollup.json").write_text(json.dumps({
            "schema_version": "matrix_rollup.v1",
            "library_name": args.product,
            "cells": [],
            "plugin_deltas": [],
            "warnings": [],
        }), encoding="utf-8")

    monkeypatch.setattr("agent_benchmarks.commands.arms.cmd_arms_matrix_run", fake_matrix_run)
    descriptor_path = tmp_path / "subject.toml"
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{"id": "q1", "question": "Q?"}]), encoding="utf-8")
    descriptor_path.write_text(
        f"""
[subject]
id = "../unsafe"
kind = "doc-source"
ref = "local:docs"

[suite]
products = ["oneTBB"]
questions = ["{questions}"]
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(["subjects", "run", str(descriptor_path)])

    args.func(args)

    assert (tmp_path / "results" / "subjects" / "..-unsafe" / "subject-scorecard.json").is_file()
    assert not (tmp_path / "results" / "unsafe").exists()


def test_safe_subject_id_rejects_dot_dot():
    with pytest.raises(ValueError, match="subject.id must not resolve"):
        _safe_subject_id("..")


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


def test_subject_work_requires_explicit_harness_when_tasks_declared(tmp_path: Path):
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
tasks = ["terminal-bench-tasks/example"]
""".strip(),
        encoding="utf-8",
    )
    descriptor = load_subject(descriptor_path)
    args = build_parser().parse_args(["subjects", "run", str(descriptor_path)])

    with pytest.raises(ValueError, match="pass --work-harnesses"):
        _run_subject_work(descriptor, args, out_dir=tmp_path)


def test_subject_work_preflight_loads_tasks_before_awareness(tmp_path: Path, monkeypatch, capsys):
    def fail_if_called(args):
        raise AssertionError("awareness matrix should not run before task preflight")

    monkeypatch.setattr("agent_benchmarks.commands.arms.cmd_arms_matrix_run", fail_if_called)
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{"id": "q1", "question": "Q?"}]), encoding="utf-8")
    docs = tmp_path / "docs.md"
    docs.write_text("# Docs\n", encoding="utf-8")
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
tasks = ["{tmp_path / 'missing-task'}"]
""".strip(),
        encoding="utf-8",
    )
    args = build_parser().parse_args([
        "subjects",
        "run",
        str(descriptor),
        "--work-harnesses",
        "codex",
    ])

    with pytest.raises(SystemExit) as excinfo:
        args.func(args)

    assert excinfo.value.code == 1
    assert "Error loading subject work: Task directory not found" in capsys.readouterr().err


def test_subjects_run_writes_work_task_runs_when_requested(tmp_path: Path, monkeypatch):
    def fake_matrix_run(args):
        run_dir = Path(args.out_dir)
        run_dir.mkdir(parents=True)
        (run_dir / "matrix-rollup.json").write_text(json.dumps({
            "schema_version": "matrix_rollup.v1",
            "library_name": args.product,
            "cells": [],
            "plugin_deltas": [],
            "warnings": [],
        }), encoding="utf-8")

    monkeypatch.setattr("agent_benchmarks.commands.arms.cmd_arms_matrix_run", fake_matrix_run)
    task_dir = tmp_path / "task-one"
    task_dir.mkdir()
    (task_dir / "instruction.md").write_text("Edit the code.", encoding="utf-8")
    (task_dir / "task.toml").write_text(
        """
[metadata]
difficulty = "smoke"
tags = ["onetbb"]
""".strip(),
        encoding="utf-8",
    )
    questions = tmp_path / "questions.json"
    questions.write_text(json.dumps([{"id": "q1", "question": "Q?"}]), encoding="utf-8")
    docs = tmp_path / "docs.md"
    docs.write_text("# Docs\n", encoding="utf-8")
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
tasks = ["{task_dir}"]
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
        "--work-harnesses",
        "codex",
        "--work-dry-run",
    ])

    args.func(args)

    scorecard = json.loads((out_dir / "subject-scorecard.json").read_text(encoding="utf-8"))
    assert scorecard["work"]["status"] == "run"
    assert scorecard["work"]["harnesses"] == ["codex"]
    assert scorecard["work"]["summary"]["per_harness"]["codex"]["n"] == 1
    assert (out_dir / "work" / "task-runs.json").is_file()
    task_runs = json.loads((out_dir / "work" / "task-runs.json").read_text(encoding="utf-8"))
    assert task_runs["schema_version"] == "task_runs.v1"
    assert task_runs["results"][0]["metrics"]["dry_run"] is True
