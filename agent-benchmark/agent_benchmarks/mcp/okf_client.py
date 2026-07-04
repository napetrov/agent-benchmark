"""OKF (Open Knowledge Format) documentation source client.

OKF is Google Cloud's vendor-neutral open specification (v0.1, 2026) for
representing organizational knowledge as a *directory of Markdown files, each
with YAML frontmatter*. There is no SDK: a bundle is just plain files that are
readable by both humans and agents, version-controlled in git, and portable
across serving systems.

This client reads an OKF bundle as a doc source so it can be benchmarked as a
treatment arm against other sources (``context7``, ``local:``, ``url:``,
``mcp:``). The frontmatter fields (``title``, ``tags``, ``type``,
``description``) carry curated signal, so they are scored in addition to the
Markdown body and passed through in each chunk's ``metadata``.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from . import MCPClient, MCPConnectionError
from .utils import score_chunk

logger = logging.getLogger(__name__)

# OKF bundles are Markdown-only.
_OKF_EXTENSIONS = {".md", ".markdown"}

# Frontmatter fields that carry curated retrieval signal.
_FRONTMATTER_SIGNAL_FIELDS = ("title", "tags", "type", "description")

# Weight applied to frontmatter matches relative to body matches.
_FRONTMATTER_WEIGHT = 0.5


def split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Split an OKF document into (frontmatter dict, body).

    A document opens with a ``---`` fence, the YAML frontmatter, a closing
    ``---`` fence, then the Markdown body. If no well-formed frontmatter block
    is present, returns an empty dict and the original text as the body.
    Malformed YAML is tolerated: it degrades to an empty frontmatter dict
    rather than raising, so a single bad file cannot abort a scan.
    """
    if not text.startswith("---"):
        return {}, text
    # Split into ["", frontmatter, body] around the first two fences.
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        logger.debug("OKFClient: malformed frontmatter, ignoring: %s", exc)
        frontmatter = None
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, parts[2].lstrip("\n")


class OKFClient(MCPClient):
    """Documentation client that reads a Google OKF knowledge bundle.

    Usage::

        client = OKFClient(Path("/path/to/okf-bundle"))
        docs = client.get_library_docs("okf:/path/to/okf-bundle", "parallel_for")
    """

    def __init__(
        self,
        path: Path,
        encoding: str = "utf-8",
        max_file_size_kb: int = 512,
    ):
        """
        Args:
            path: Root directory (or single ``.md`` file) of the OKF bundle.
            encoding: Text encoding used when reading files.
            max_file_size_kb: Skip files larger than this (avoids OOM).
        """
        self.path = Path(path)
        self.encoding = encoding
        self.max_file_size_bytes = max_file_size_kb * 1024

    # ── MCPClient interface ────────────────────────────────────────────────

    def resolve_library_id(self, library_name: str) -> str:
        """Return a canonical ID for this OKF bundle."""
        return f"okf:{self.path}"

    def get_library_docs(
        self,
        library_id: str,
        query: str,
        max_results: int = 5,
        max_tokens: int = 8000,
    ) -> List[Dict[str, Any]]:
        """Return the most query-relevant documents from the OKF bundle.

        Each document is scored by keyword overlap on its Markdown body plus a
        weighted overlap on its frontmatter signal fields. The top
        *max_results* are returned, sorted by score then path for determinism.

        Args:
            library_id: Passed through into each result (path is fixed at init).
            query: Natural-language search query.
            max_results: Maximum number of documents to return.
            max_tokens: Soft limit — each body is capped at ``max_tokens * 4`` chars.

        Returns:
            List of dicts with keys: content, source, file, library_id, query,
            relevance_score, metadata (the parsed OKF frontmatter).
        """
        if not self.path.exists():
            raise MCPConnectionError(f"OKFClient: path does not exist: {self.path}")

        files = self._collect_files()
        if not files:
            logger.warning("OKFClient: no OKF documents found under %s", self.path)
            return []

        char_limit = max_tokens * 4  # rough chars-per-token estimate

        scored: List[Tuple[float, Path, Dict[str, Any], str]] = []
        for fp in files:
            try:
                raw = fp.read_text(encoding=self.encoding)
            except Exception as exc:
                logger.debug("OKFClient: skipping %s: %s", fp, exc)
                continue

            frontmatter, body = split_frontmatter(raw)
            if not body.strip():
                continue

            frontmatter_text = " ".join(
                _stringify(frontmatter.get(field, ""))
                for field in _FRONTMATTER_SIGNAL_FIELDS
            )
            score = score_chunk(query, body) + _FRONTMATTER_WEIGHT * score_chunk(
                query, frontmatter_text
            )
            scored.append((score, fp, frontmatter, body[:char_limit]))

        # Sort by score descending, then by file name for determinism.
        scored.sort(key=lambda item: (-item[0], str(item[1])))

        results: List[Dict[str, Any]] = []
        for score, fp, frontmatter, body in scored[:max_results]:
            results.append(
                {
                    "content": body,
                    "source": "okf",
                    "file": str(
                        fp.relative_to(self.path)
                        if fp.is_relative_to(self.path)
                        else fp
                    ),
                    "library_id": library_id,
                    "query": query,
                    "relevance_score": round(score, 4),
                    "metadata": frontmatter,
                }
            )

        logger.info(
            "OKFClient: returning %d/%d documents for query='%s...'",
            len(results),
            len(scored),
            query[:40],
        )
        return results

    def check_connection(self) -> bool:
        """Return True if the path exists and holds at least one OKF document."""
        if not self.path.exists():
            return False
        return any(True for _ in self._iter_candidate_files())

    # ── internals ──────────────────────────────────────────────────────────

    def _iter_candidate_files(self):
        """Yield candidate OKF files (single file or recursive directory)."""
        if self.path.is_file():
            if self.path.suffix.lower() in _OKF_EXTENSIONS:
                yield self.path
            return
        for fp in self.path.rglob("*"):
            if fp.is_file() and fp.suffix.lower() in _OKF_EXTENSIONS:
                yield fp

    def _collect_files(self) -> List[Path]:
        """Collect OKF files under the size limit, sorted for determinism."""
        files = []
        for fp in self._iter_candidate_files():
            try:
                if fp.stat().st_size > self.max_file_size_bytes:
                    logger.debug("OKFClient: skipping oversize file %s", fp)
                    continue
            except OSError:
                continue
            files.append(fp)
        return sorted(files, key=str)


def _stringify(value: Any) -> str:
    """Flatten a frontmatter value (str, list, scalar) into searchable text."""
    if isinstance(value, (list, tuple)):
        return " ".join(_stringify(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_stringify(v) for v in value.values())
    return str(value)
