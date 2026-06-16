"""Questions-and-tasks coverage contract (ADR 2026-06-10, Phase A).

Implements the *coverage contract* from
``docs/decisions/2026-06-10-questions-and-tasks-coverage-contract.md``: every
in-scope product declares an **awareness** signal (a golden question set) and a
**work** signal (>=1 executable terminal-bench task), and any gap is surfaced as
a checked matrix instead of being a silent default.

Design decisions taken here (resolving the ADR's open questions):

* **O4 — where the contract lives:** the canonical top-level ``products.yaml``.
  It already owns product identity and ``doc_sources`` and is the registry
  ``config_check`` treats as canonical, so the ``questions`` /
  ``coverage_status`` fields live alongside identity rather than in a third
  sync surface.
* **work signal is *derived*, not hand-listed:** a product's tasks are computed
  by scanning ``terminal-bench-tasks/*/task.toml`` ``tags`` for the product key.
  This avoids the ADR's noted negative ("a per-product ``tasks`` list is a
  second place task identity lives") — the task directory stays the single
  source of truth.
* **O1 — soft enforcement:** :func:`coverage_issues` only reports a *hard* error
  for a broken declaration (a product that declares ``coverage_status: covered``
  but resolves to no task, or names a ``questions`` file that does not exist).
  A simply-missing work half is a tracked, visible ``questions-only`` gap, not a
  failure.

Awareness and work are never blended into one scalar (ADR §3.4).
"""

from __future__ import annotations

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # Python 3.10 fallback
    import tomli as tomllib  # type: ignore[no-redef]
from dataclasses import dataclass, field
from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parent.parent
_PRODUCTS_PATH = _REPO_ROOT / "products.yaml"
_TASKS_DIR = _REPO_ROOT / "terminal-bench-tasks"
_QUESTIONS_DIR = _REPO_ROOT / "data" / "questions"

# Honest self-report states (ADR §3.1).
STATUS_COVERED = "covered"            # has questions AND >=1 task
STATUS_QUESTIONS_ONLY = "questions-only"  # awareness only; a visible TODO
STATUS_PLANNED = "planned"            # neither yet (onboarding)
_VALID_STATUSES = {STATUS_COVERED, STATUS_QUESTIONS_ONLY, STATUS_PLANNED}


@dataclass
class ProductCoverage:
    """Resolved awareness/work coverage for one product."""

    key: str
    questions: list[str] = field(default_factory=list)  # resolvable question files
    tasks: list[str] = field(default_factory=list)       # task dir names (derived)
    declared_status: str | None = None                   # from products.yaml
    missing_questions: list[str] = field(default_factory=list)  # declared-but-absent

    @property
    def has_awareness(self) -> bool:
        return bool(self.questions)

    @property
    def has_work(self) -> bool:
        return bool(self.tasks)

    @property
    def effective_status(self) -> str:
        """Honest status derived from what actually resolves."""
        if self.has_awareness and self.has_work:
            return STATUS_COVERED
        if self.has_awareness:
            return STATUS_QUESTIONS_ONLY
        return STATUS_PLANNED


def _load_products(path: Path | None = None) -> dict:
    path = Path(path or _PRODUCTS_PATH)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    products = data.get("products", {})
    return products if isinstance(products, dict) else {}


def _task_product_tags(tasks_dir: Path) -> dict[str, set[str]]:
    """Map each task dir name -> set of lowercased tags from its task.toml."""
    out: dict[str, set[str]] = {}
    if not tasks_dir.is_dir():
        return out
    for task_dir in sorted(p for p in tasks_dir.iterdir() if p.is_dir()):
        toml_path = task_dir / "task.toml"
        if not toml_path.is_file():
            continue
        try:
            meta = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            continue
        # tags live under [metadata] in task.toml; fall back to top level.
        meta_tbl = meta.get("metadata", {})
        tags = meta_tbl.get("tags") if isinstance(meta_tbl, dict) else None
        if not tags:
            tags = meta.get("tags", [])
        out[task_dir.name] = {str(t).lower() for t in (tags or []) if isinstance(t, str)}
    return out


# Product key -> extra tag aliases that also indicate a task covers it.
# Derived from observed task tags (e.g. sklearnex tasks tag both sklearnex and
# the onedal library they accelerate).
_TAG_ALIASES: dict[str, set[str]] = {
    "onedal": {"sklearnex"},
}


def _tasks_for_product(key: str, task_tags: dict[str, set[str]]) -> list[str]:
    aliases = {key} | _TAG_ALIASES.get(key, set())
    return sorted(name for name, tags in task_tags.items() if aliases & tags)


def resolve_coverage(
    products: dict | None = None,
    *,
    tasks_dir: Path | None = None,
    questions_dir: Path | None = None,
) -> list[ProductCoverage]:
    """Resolve per-product coverage from the registry, tasks, and question sets."""
    products = products if products is not None else _load_products()
    tasks_dir = Path(tasks_dir or _TASKS_DIR)
    questions_dir = Path(questions_dir or _QUESTIONS_DIR)
    task_tags = _task_product_tags(tasks_dir)

    result: list[ProductCoverage] = []
    for key, cfg in products.items():
        cfg = cfg if isinstance(cfg, dict) else {}
        declared_status = cfg.get("coverage_status")

        # Awareness: explicit `questions:` list, else the conventional golden file.
        declared_q = cfg.get("questions")
        if isinstance(declared_q, str):
            declared_q = [declared_q]
        elif not isinstance(declared_q, list):
            declared_q = []
        questions: list[str] = []
        missing: list[str] = []
        candidates = declared_q or [f"data/questions/{key}_golden.json"]
        for rel in candidates:
            path = _REPO_ROOT / rel
            if path.is_file():
                questions.append(rel)
            elif declared_q:  # only a *declared* path counts as missing/broken
                missing.append(rel)

        result.append(
            ProductCoverage(
                key=key,
                questions=questions,
                tasks=_tasks_for_product(key, task_tags),
                declared_status=declared_status,
                missing_questions=missing,
            )
        )
    return result


def coverage_issues(coverages: list[ProductCoverage] | None = None) -> list[str]:
    """Hard-error issues for CI (ADR O1: soft enforcement).

    Only a *broken declaration* is an error:
      * ``coverage_status: covered`` but no task resolves, or no question set;
      * a declared ``questions`` file that does not exist;
      * an unknown ``coverage_status`` value.
    A missing work half on an undeclared/`questions-only`/`planned` product is a
    tracked gap, not an error.
    """
    coverages = coverages if coverages is not None else resolve_coverage()
    issues: list[str] = []
    for c in coverages:
        if c.declared_status is not None and c.declared_status not in _VALID_STATUSES:
            issues.append(
                f"{c.key}: invalid coverage_status {c.declared_status!r} "
                f"(expected one of {sorted(_VALID_STATUSES)})"
            )
        if c.missing_questions:
            issues.append(
                f"{c.key}: declared questions file(s) not found: "
                f"{', '.join(c.missing_questions)}"
            )
        if c.declared_status == STATUS_COVERED:
            if not c.has_work:
                issues.append(
                    f"{c.key}: coverage_status=covered but no terminal-bench task "
                    f"tags it (work half missing)"
                )
            if not c.has_awareness:
                issues.append(
                    f"{c.key}: coverage_status=covered but no question set resolves "
                    f"(awareness half missing)"
                )
    return issues


def coverage_matrix_rows(
    coverages: list[ProductCoverage] | None = None,
) -> list[dict]:
    """Render-ready rows for the COVERAGE.md product x {questions, tasks} matrix."""
    coverages = coverages if coverages is not None else resolve_coverage()
    rows = []
    for c in sorted(coverages, key=lambda x: x.key):
        rows.append(
            {
                "product": c.key,
                "awareness": "yes" if c.has_awareness else "no",
                "questions": c.questions,
                "work": len(c.tasks),
                "tasks": c.tasks,
                "status": c.effective_status,
            }
        )
    return rows


def _print_matrix() -> None:
    """CLI entry: print the coverage matrix as a Markdown table to stdout."""
    rows = coverage_matrix_rows()
    print("| Product | Awareness (questions) | Work (tasks) | Status |")
    print("| --- | --- | --- | --- |")
    for r in rows:
        aware = "yes" if r["awareness"] == "yes" else "no"
        print(f"| `{r['product']}` | {aware} | {r['work']} | {r['status']} |")
    issues = coverage_issues()
    if issues:
        print("\nISSUES:")
        for i in issues:
            print(f"  - {i}")


if __name__ == "__main__":
    _print_matrix()
