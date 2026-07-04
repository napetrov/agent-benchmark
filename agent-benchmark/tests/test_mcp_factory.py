"""Tests for create_doc_source_client factory."""

import pytest
from pathlib import Path

from agent_benchmarks.mcp.factory import create_doc_source_client
from agent_benchmarks.mcp.context7 import Context7Client
from agent_benchmarks.mcp.local_markdown import LocalMarkdownClient
from agent_benchmarks.mcp.url_client import URLClient
from agent_benchmarks.mcp.okf_client import OKFClient


def test_context7_default(tmp_path):
    client = create_doc_source_client("context7", cache_dir=tmp_path)
    assert isinstance(client, Context7Client)


def test_context7_creates_cache_dir(tmp_path):
    cache = tmp_path / "ctx7cache"
    client = create_doc_source_client("context7", cache_dir=cache)
    assert isinstance(client, Context7Client)
    assert cache.exists()


def test_local_source(tmp_path):
    client = create_doc_source_client(f"local:{tmp_path}")
    assert isinstance(client, LocalMarkdownClient)
    assert client.path == tmp_path


def test_local_source_relative_path():
    client = create_doc_source_client("local:docs/onetbb")
    assert isinstance(client, LocalMarkdownClient)
    assert client.path == Path("docs/onetbb")


def test_url_source(tmp_path):
    url = "https://example.com/api-docs"
    client = create_doc_source_client(f"url:{url}", cache_dir=tmp_path)
    assert isinstance(client, URLClient)
    assert client.url == url


def test_url_source_no_cache():
    client = create_doc_source_client("url:https://example.com/docs")
    assert isinstance(client, URLClient)


def test_okf_source(tmp_path):
    client = create_doc_source_client(f"okf:{tmp_path}")
    assert isinstance(client, OKFClient)
    assert client.path == tmp_path


def test_okf_source_relative_path():
    client = create_doc_source_client("okf:docs/onetbb-okf")
    assert isinstance(client, OKFClient)
    assert client.path == Path("docs/onetbb-okf")


def test_okf_missing_path_raises():
    with pytest.raises(ValueError, match="okf:.*path"):
        create_doc_source_client("okf:")


def test_local_missing_path_raises():
    with pytest.raises(ValueError, match="local:.*path"):
        create_doc_source_client("local:")


def test_url_missing_url_raises():
    with pytest.raises(ValueError, match="url:.*URL"):
        create_doc_source_client("url:")


def test_unknown_source_raises():
    with pytest.raises(ValueError, match="Unknown.*doc-source"):
        create_doc_source_client("s3://bucket/docs")


def test_unknown_source_plain_string_raises():
    with pytest.raises(ValueError):
        create_doc_source_client("confluence")


def test_returns_mcp_client_interface():
    """All returned clients must satisfy the MCPClient interface."""
    import tempfile
    from agent_benchmarks.mcp import MCPClient

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "test.md").write_text("# Test\n\nSome content here.")
        sources = [
            "context7",
            f"local:{tmp_path}",
            "url:https://example.com/docs",
            f"okf:{tmp_path}",
        ]
        for source in sources:
            client = create_doc_source_client(source)
            assert isinstance(client, MCPClient), f"{source} did not return MCPClient"
            assert hasattr(client, "resolve_library_id")
            assert hasattr(client, "get_library_docs")
            assert hasattr(client, "check_connection")
