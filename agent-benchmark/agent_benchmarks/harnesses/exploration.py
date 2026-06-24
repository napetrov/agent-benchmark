"""Derive exploration-quality metrics from a harness operation stream.

Companion to ``agent_benchmarks/metrics/exploration.py`` (citation scoring),
implementing the trajectory-shape slice of
``docs/decisions/2026-06-23-exploration-quality-fastcontext.md`` (BACKLOG #60).

Given the ``OperationRecord`` list a harness already collects (see
``operations.py``), summarize *how* the agent explored before it acted: how many
read/search calls preceded the first edit, how often it re-read the same file,
how many broad searches it ran, and whether broad search continued *after* a
subagent had already returned focused evidence. It also splits token accounting
into main-agent vs subagent buckets so context-discovery savings are never
overstated.

The summary is emitted only when the stream actually contains exploration
signal (a read / search / subagent / edit op); otherwise the caller omits the
block entirely, keeping artifacts for non-exploring harnesses unchanged. When a
specific metric cannot be derived from the available telemetry it is ``None``
with a recorded reason, never fabricated.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from agent_benchmarks.metrics.exploration import normalize_path

from .models import OperationRecord

# Operation classification. Matched against ``type`` first, then ``name``.
_READ_WORDS = ("read", "view", "cat", "open_file")
_SEARCH_WORDS = ("search", "grep", "glob", "find", "ripgrep", "rg")
_EDIT_WORDS = ("edit", "write", "apply_patch", "str_replace", "patch", "create_file")
_SUBAGENT_WORDS = ("subagent",)

# Markers that make a search "broad" when no explicit metadata.broad flag is set.
_BROAD_MARKERS = ("grep -r", "grep -R", "rg ", "find ", "-r ", "-R ", " -rn", "--recursive")


def _classify(op: OperationRecord) -> Optional[str]:
    haystacks = (str(op.type).lower(), str(op.name).lower())

    def _hit(words: Sequence[str]) -> bool:
        return any(any(w in h for w in words) for h in haystacks)

    # Subagent and edit take precedence over read/search (an edit op may also
    # mention "file"; a subagent op may mention "search" in its query name).
    if _hit(_SUBAGENT_WORDS):
        return "subagent"
    if _hit(_EDIT_WORDS):
        return "edit"
    if _hit(_SEARCH_WORDS):
        return "search"
    if _hit(_READ_WORDS):
        return "read"
    return None


def _op_path(op: OperationRecord) -> Optional[str]:
    for key in ("path", "file", "target", "filename"):
        value = op.metadata.get(key)
        if value:
            return normalize_path(str(value))
    return None


def _is_broad(op: OperationRecord) -> tuple[bool, bool]:
    """Return ``(is_broad, inferred)``.

    ``inferred`` is True when broadness was guessed from the command/query text
    rather than an explicit ``metadata.broad`` flag — surfaced so a reader can
    tell heuristic counts from authoritative ones.
    """
    flag = op.metadata.get("broad")
    if isinstance(flag, bool):
        return flag, False
    text = " ".join(
        str(op.metadata.get(k, "")) for k in ("command", "query", "args", "line")
    ).lower()
    return any(m.lower() in text for m in _BROAD_MARKERS), True


def _subagent_cited_paths(op: OperationRecord) -> set[str]:
    for key in ("citation_paths", "citations", "cited_paths", "citation_files_list"):
        value = op.metadata.get(key)
        if isinstance(value, (list, tuple)):
            return {normalize_path(str(v)) for v in value if v}
    return set()


def summarize_exploration(
    operations: Sequence[OperationRecord],
    *,
    main_tokens: Optional[int] = None,
) -> Optional[dict[str, Any]]:
    """Summarize exploration behavior from an operation stream.

    Args:
        operations: The ordered operations recorded for one task run.
        main_tokens: Total main-agent tokens for the run, if known (used for the
            read/search token share and the main/full token split). ``None``
            when the harness does not report token usage.

    Returns:
        A metrics dict suitable for ``results[].metrics.exploration_metrics``,
        or ``None`` when the stream contains no exploration signal.
    """
    classes = [(_classify(op), op) for op in operations]
    if not any(kind for kind, _ in classes):
        return None

    reads = [op for kind, op in classes if kind == "read"]
    searches = [op for kind, op in classes if kind == "search"]
    subagents = [op for kind, op in classes if kind == "subagent"]

    first_edit_idx = next(
        (i for i, (kind, _) in enumerate(classes) if kind == "edit"), None
    )

    # ── trajectory shape (pre-edit) ─────────────────────────────────────────
    if first_edit_idx is not None:
        pre = classes[:first_edit_idx]
        pre_tool = [op for kind, op in pre if kind in ("read", "search", "subagent")]
        pre_reads = sum(1 for kind, _ in pre if kind == "read")
        pre_searches = sum(1 for kind, _ in pre if kind == "search")
        pre_elapsed = sum(op.elapsed_sec for _, op in pre)
        time_to_first_edit = round(pre_elapsed, 4) if pre_elapsed > 0 else None
        pre_edit_tool_calls: Optional[int] = len(pre_tool)
    else:
        # No edit observed (e.g. a pure exploration or Q&A run): pre-edit
        # framing does not apply.
        pre_reads = pre_searches = 0
        time_to_first_edit = None
        pre_edit_tool_calls = None

    # ── repeated reads ──────────────────────────────────────────────────────
    read_paths = [p for p in (_op_path(op) for op in reads) if p]
    if read_paths:
        seen: set[str] = set()
        repeats = 0
        for p in read_paths:
            if p in seen:
                repeats += 1
            seen.add(p)
        repeated_read_ratio: Optional[float] = round(repeats / len(read_paths), 4)
    else:
        repeated_read_ratio = None

    # ── broad search (and broad search after a subagent returned) ───────────
    first_subagent_idx = next(
        (i for i, (kind, _) in enumerate(classes) if kind == "subagent"), None
    )
    broad_count = 0
    broad_inferred = 0
    broad_after_subagent = 0
    for i, (kind, op) in enumerate(classes):
        if kind != "search":
            continue
        is_broad, inferred = _is_broad(op)
        if not is_broad:
            continue
        broad_count += 1
        if inferred:
            broad_inferred += 1
        if first_subagent_idx is not None and i > first_subagent_idx:
            broad_after_subagent += 1

    # ── delegation health: do main reads overlap subagent citations? ────────
    cited = set().union(*(_subagent_cited_paths(op) for op in subagents)) if subagents else set()
    if cited and read_paths:
        overlap = len({p for p in read_paths} & cited) / len(set(read_paths))
        main_reads_overlap = round(overlap, 4)
    else:
        main_reads_overlap = None

    # ── token accounting (main vs subagent) ─────────────────────────────────
    subagent_tokens = _sum_subagent_tokens(subagents)
    read_search_token_share = _read_search_token_share(reads, searches, main_tokens)
    full_system_tokens = (
        (main_tokens or 0) + subagent_tokens
        if (main_tokens is not None or subagent_tokens)
        else None
    )

    metrics: dict[str, Any] = {
        "read_count": len(reads),
        "search_count": len(searches),
        "subagent_invocation_count": len(subagents),
        "pre_edit_tool_calls": pre_edit_tool_calls,
        "pre_edit_reads": pre_reads,
        "pre_edit_searches": pre_searches,
        "time_to_first_edit_sec": time_to_first_edit,
        "repeated_read_ratio": repeated_read_ratio,
        "broad_search_count": broad_count,
        "broad_search_inferred_count": broad_inferred,
        "broad_search_after_subagent_count": broad_after_subagent,
        "main_reads_overlap_with_citations": main_reads_overlap,
        "read_search_token_share": read_search_token_share,
        "main_agent_tokens": main_tokens,
        "subagent_tokens": subagent_tokens,
        "full_system_tokens": full_system_tokens,
    }
    return metrics


def _sum_subagent_tokens(subagents: Sequence[OperationRecord]) -> int:
    total = 0
    for op in subagents:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = op.metadata.get(key)
            # Prefer total_tokens when present to avoid double counting.
            if key == "total_tokens" and value:
                total += int(value)
                break
        else:
            prompt = op.metadata.get("prompt_tokens") or 0
            completion = op.metadata.get("completion_tokens") or 0
            total += int(prompt) + int(completion)
    return total


def _read_search_token_share(
    reads: Sequence[OperationRecord],
    searches: Sequence[OperationRecord],
    main_tokens: Optional[int],
) -> Optional[float]:
    """Fraction of main-agent tokens spent on read/search ops.

    Requires per-op token metadata and a positive ``main_tokens`` total; returns
    ``None`` when either is unavailable.
    """
    if not main_tokens or main_tokens <= 0:
        return None
    spent = 0
    have_any = False
    for op in (*reads, *searches):
        tokens = op.metadata.get("total_tokens")
        if tokens is None:
            prompt = op.metadata.get("prompt_tokens")
            completion = op.metadata.get("completion_tokens")
            if prompt is None and completion is None:
                continue
            tokens = (prompt or 0) + (completion or 0)
        have_any = True
        spent += int(tokens)
    if not have_any:
        return None
    return round(min(spent / main_tokens, 1.0), 4)
