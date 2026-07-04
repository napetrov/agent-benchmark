"""Tests for OKFClient (Google Open Knowledge Format doc source)."""

import pytest

from agent_benchmarks.mcp import MCPConnectionError
from agent_benchmarks.mcp.okf_client import OKFClient, split_frontmatter


@pytest.fixture
def okf_bundle(tmp_path):
    """Create a small OKF bundle: Markdown files with YAML frontmatter."""
    (tmp_path / "parallel_for.md").write_text(
        "---\n"
        "title: parallel_for\n"
        "type: api\n"
        "tags: [threading, loops]\n"
        "---\n"
        "# parallel_for\n\n"
        "The parallel_for function divides a range into chunks and processes "
        "them in parallel using a thread pool."
    )
    (tmp_path / "runbooks").mkdir()
    (tmp_path / "runbooks" / "install.md").write_text(
        "---\n"
        "title: Installation\n"
        "type: runbook\n"
        "---\n"
        "# Installation\n\n"
        "Run `pip install onetbb` to install the library."
    )
    # A file with no frontmatter — must still be indexed.
    (tmp_path / "notes.md").write_text(
        "# Notes\n\nMiscellaneous notes about task_group and concurrency."
    )
    return tmp_path


# ── split_frontmatter ─────────────────────────────────────────────────────────

def test_split_frontmatter_parses_yaml():
    fm, body = split_frontmatter("---\ntitle: X\ntags: [a, b]\n---\n# Body\n\ntext")
    assert fm == {"title": "X", "tags": ["a", "b"]}
    assert body.startswith("# Body")


def test_split_frontmatter_no_fence():
    fm, body = split_frontmatter("# Just markdown\n\nno frontmatter here")
    assert fm == {}
    assert body.startswith("# Just markdown")


def test_split_frontmatter_malformed_yaml_degrades():
    # Unbalanced brackets -> YAMLError -> empty dict, body preserved.
    fm, body = split_frontmatter("---\ntitle: [unclosed\n---\nbody text")
    assert fm == {}
    assert "body text" in body


def test_split_frontmatter_non_mapping_ignored():
    fm, body = split_frontmatter("---\n- just\n- a\n- list\n---\nbody")
    assert fm == {}
    assert body == "body"


# ── check_connection ──────────────────────────────────────────────────────────

def test_check_connection_existing_bundle(okf_bundle):
    assert OKFClient(okf_bundle).check_connection() is True


def test_check_connection_missing_path(tmp_path):
    assert OKFClient(tmp_path / "nope").check_connection() is False


def test_check_connection_empty_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert OKFClient(empty).check_connection() is False


# ── resolve_library_id ────────────────────────────────────────────────────────

def test_resolve_library_id(okf_bundle):
    assert OKFClient(okf_bundle).resolve_library_id("oneTBB") == f"okf:{okf_bundle}"


# ── get_library_docs ──────────────────────────────────────────────────────────

def test_get_library_docs_returns_results(okf_bundle):
    docs = OKFClient(okf_bundle).get_library_docs("okf:oneTBB", "parallel_for thread pool")
    assert len(docs) > 0
    assert all(d["source"] == "okf" for d in docs)
    assert all("content" in d and "relevance_score" in d for d in docs)


def test_get_library_docs_exposes_frontmatter_metadata(okf_bundle):
    docs = OKFClient(okf_bundle).get_library_docs("okf:oneTBB", "parallel_for")
    top = docs[0]
    assert top["metadata"].get("title") == "parallel_for"
    assert top["metadata"].get("type") == "api"


def test_get_library_docs_body_excludes_frontmatter(okf_bundle):
    docs = OKFClient(okf_bundle).get_library_docs("okf:oneTBB", "parallel_for")
    for d in docs:
        assert "---" not in d["content"].splitlines()[0]
        assert "type: api" not in d["content"]


def test_frontmatter_boosts_relevance(okf_bundle):
    # "runbook" only appears in install.md's frontmatter type field.
    docs = OKFClient(okf_bundle).get_library_docs("okf:oneTBB", "runbook", max_results=5)
    assert docs[0]["file"].endswith("install.md")


def test_file_without_frontmatter_indexed(okf_bundle):
    docs = OKFClient(okf_bundle).get_library_docs("okf:oneTBB", "task_group concurrency")
    assert any(d["file"] == "notes.md" for d in docs)
    note = next(d for d in docs if d["file"] == "notes.md")
    assert note["metadata"] == {}


def test_get_library_docs_respects_max_results(okf_bundle):
    docs = OKFClient(okf_bundle).get_library_docs("okf:oneTBB", "install library", max_results=1)
    assert len(docs) == 1


def test_relevance_score_present(okf_bundle):
    docs = OKFClient(okf_bundle).get_library_docs("okf:oneTBB", "install pip")
    assert all(d["relevance_score"] >= 0.0 for d in docs)


def test_single_file_bundle(tmp_path):
    single = tmp_path / "readme.md"
    single.write_text("---\ntitle: README\n---\n# README\n\nMain documentation file.")
    client = OKFClient(single)
    assert client.check_connection() is True
    docs = client.get_library_docs(f"okf:{single}", "documentation")
    assert len(docs) == 1
    assert docs[0]["metadata"]["title"] == "README"


def test_missing_path_raises(tmp_path):
    client = OKFClient(tmp_path / "missing")
    with pytest.raises(MCPConnectionError):
        client.get_library_docs("okf:missing", "anything")


def test_non_markdown_files_ignored(tmp_path):
    (tmp_path / "doc.md").write_text("---\ntitle: Doc\n---\n# Doc\n\nreal content")
    (tmp_path / "data.json").write_text('{"not": "okf"}')
    (tmp_path / "page.html").write_text("<html>ignored</html>")
    docs = OKFClient(tmp_path).get_library_docs("okf:x", "content")
    assert all(d["file"].endswith(".md") for d in docs)


def test_determinism(okf_bundle):
    client = OKFClient(okf_bundle)
    first = client.get_library_docs("okf:oneTBB", "library install parallel")
    second = client.get_library_docs("okf:oneTBB", "library install parallel")
    assert [d["file"] for d in first] == [d["file"] for d in second]
