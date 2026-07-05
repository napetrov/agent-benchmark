"""Question-set reproducibility tests for the evaluation pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_benchmarks.orchestrator.pipeline import (
    EvaluationPipeline,
    compute_question_set_hash,
    load_questions_payload,
)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _stub_expensive_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_generate_questions(self, personas):
        raise AssertionError("question generation should be skipped")

    def generate_answers(self, questions, concurrency=5, question_set_hash=None):
        assert question_set_hash == compute_question_set_hash(questions)
        return [
            {
                "question_id": q["id"],
                "question_text": q["question"],
                "with_docs": {"answer": "context"},
                "without_docs": {"answer": "baseline"},
            }
            for q in questions
        ]

    def evaluate_answers(self, answers, concurrency=5, question_set_hash=None):
        data = {
            "run_metadata": {"question_set_hash": question_set_hash},
            "evaluations": [],
        }
        self.eval_path.write_text(json.dumps(data), encoding="utf-8")
        return []

    def generate_report(self, evaluations, questions):
        self.report_path.write_text("report", encoding="utf-8")
        return "report"

    monkeypatch.setattr(EvaluationPipeline, "_generate_questions", no_generate_questions)
    monkeypatch.setattr(EvaluationPipeline, "_generate_answers", generate_answers)
    monkeypatch.setattr(EvaluationPipeline, "_evaluate_answers", evaluate_answers)
    monkeypatch.setattr(EvaluationPipeline, "_generate_report", generate_report)


def test_cached_questions_skip_generation_and_get_question_set_id(tmp_path, monkeypatch):
    _stub_expensive_steps(monkeypatch)
    questions = [
        {"id": "q2", "question": "How do I sort in parallel?", "source_type": "generated"},
        {"id": "q1", "question": "How do I configure workers?", "source_type": "manual"},
    ]
    output_dir = tmp_path / "run"
    _write_json(output_dir / "personas" / "oneTBB.json", {"personas": []})
    _write_json(output_dir / "questions" / "oneTBB.json", {"questions": questions})

    pipeline = EvaluationPipeline(
        product="oneTBB",
        output_dir=output_dir,
        description="Threading Building Blocks",
    )
    result = pipeline.run(concurrency=1)

    expected_hash = compute_question_set_hash(questions)
    saved = json.loads((output_dir / "questions" / "oneTBB.json").read_text())
    assert result["question_set_hash"] == expected_hash
    assert saved["question_set_hash"] == expected_hash
    assert saved["question_set_id"] == expected_hash
    assert saved["questions"] == questions
    assert result["steps"]["questions_generated"]["cached"] is True


def test_questions_from_directory_is_reused_and_normalized(tmp_path, monkeypatch):
    _stub_expensive_steps(monkeypatch)
    questions = [
        {"id": "q1", "question": "What does task_group do?", "source_type": "generated"}
    ]
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "target"
    _write_json(source_dir / "questions" / "oneTBB.json", questions)
    _write_json(output_dir / "personas" / "oneTBB.json", {"personas": []})

    pipeline = EvaluationPipeline(
        product="oneTBB",
        output_dir=output_dir,
        description="Threading Building Blocks",
        questions_from=source_dir,
    )
    result = pipeline.run(concurrency=1)

    expected_hash = compute_question_set_hash(questions)
    saved = json.loads((output_dir / "questions" / "oneTBB.json").read_text())
    assert result["question_set_hash"] == expected_hash
    assert saved["question_set_hash"] == expected_hash
    assert saved["question_set_id"] == expected_hash
    assert saved["questions"] == questions
    assert result["steps"]["questions_generated"]["external_source"].endswith(
        "source/questions/oneTBB.json"
    )


def test_load_questions_payload_rejects_invalid_wrapped_payload(tmp_path):
    path = tmp_path / "questions.json"
    _write_json(path, {"questions": {"q1": "not a list"}})

    with pytest.raises(ValueError, match="Expected a list of questions"):
        load_questions_payload(path)
