"""Tests for the questions-and-tasks coverage contract (ADR Phase A)."""

from __future__ import annotations

from agent_benchmarks.coverage import (
    STATUS_COVERED,
    STATUS_PLANNED,
    STATUS_QUESTIONS_ONLY,
    ProductCoverage,
    coverage_issues,
    coverage_matrix_rows,
    resolve_coverage,
)


def test_committed_coverage_has_no_issues():
    """The real products.yaml must carry no broken coverage declarations."""
    assert coverage_issues() == []


def test_onetbb_is_covered_with_tasks_and_questions():
    covs = {c.key: c for c in resolve_coverage()}
    onetbb = covs["onetbb"]
    assert onetbb.has_awareness  # golden question set resolves
    assert onetbb.has_work       # >=1 terminal-bench task tagged onetbb
    assert onetbb.effective_status == STATUS_COVERED
    # work signal is derived from task tags, not hand-listed
    assert any(t.startswith("onetbb-") for t in onetbb.tasks)


def test_onedal_covered_via_sklearnex_alias():
    """sklearnex tasks accelerate oneDAL, so they count as oneDAL work."""
    covs = {c.key: c for c in resolve_coverage()}
    assert "sklearnex-classification" in covs["onedal"].tasks
    assert covs["onedal"].effective_status == STATUS_COVERED


def test_effective_status_transitions():
    aware_and_work = ProductCoverage("x", questions=["q.json"], tasks=["t"])
    assert aware_and_work.effective_status == STATUS_COVERED

    aware_only = ProductCoverage("x", questions=["q.json"], tasks=[])
    assert aware_only.effective_status == STATUS_QUESTIONS_ONLY

    neither = ProductCoverage("x", questions=[], tasks=[])
    assert neither.effective_status == STATUS_PLANNED


def test_covered_declaration_without_task_is_an_issue():
    cov = ProductCoverage(
        "ghost", questions=["data/questions/ghost.json"], tasks=[],
        declared_status=STATUS_COVERED,
    )
    issues = coverage_issues([cov])
    assert any("work half missing" in i for i in issues)


def test_covered_declaration_without_questions_is_an_issue():
    cov = ProductCoverage(
        "ghost", questions=[], tasks=["some-task"],
        declared_status=STATUS_COVERED,
    )
    issues = coverage_issues([cov])
    assert any("awareness half missing" in i for i in issues)


def test_declared_missing_questions_file_is_an_issue():
    cov = ProductCoverage(
        "ghost", questions=[], tasks=["t"],
        declared_status=STATUS_QUESTIONS_ONLY,
        missing_questions=["data/questions/nope.json"],
    )
    issues = coverage_issues([cov])
    assert any("not found" in i for i in issues)


def test_invalid_status_value_is_an_issue():
    cov = ProductCoverage("ghost", declared_status="totally-bogus")
    issues = coverage_issues([cov])
    assert any("invalid coverage_status" in i for i in issues)


def test_questions_only_missing_work_is_not_an_issue():
    """A visible questions-only gap must NOT fail CI (soft enforcement, O1)."""
    cov = ProductCoverage(
        "x", questions=["q.json"], tasks=[], declared_status=STATUS_QUESTIONS_ONLY,
    )
    assert coverage_issues([cov]) == []


def test_matrix_rows_cover_every_product():
    rows = coverage_matrix_rows()
    products = {c.key for c in resolve_coverage()}
    assert {r["product"] for r in rows} == products
    # at least the known-covered products report work > 0
    by_product = {r["product"]: r for r in rows}
    assert by_product["onetbb"]["work"] >= 1
    assert by_product["onemkl"]["work"] >= 1
