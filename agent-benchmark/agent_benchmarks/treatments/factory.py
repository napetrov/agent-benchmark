"""Build treatment arms from ``--arms`` spec strings."""

from pathlib import Path
from typing import List, Optional

from .base import Treatment
from .arms import (
    BaselineTreatment,
    DocTreatment,
    MCPAgentTreatment,
    SkillAgentTreatment,
    AgentProfileTreatment,
    SkillTreatment,
    CombinedTreatment,
)


def _parse_combined_spec(spec: str) -> List[str]:
    """Parse a combined spec like 'docs+skill:path' into parts.

    Splits on '+' but only between treatment types, not within paths.
    Example: 'docs+skill:data/skills/my+folder' → ['docs', 'skill:data/skills/my+folder']
    """
    TREATMENT_STARTS = [
        "baseline",
        "docs:",
        "docs",
        "skill:",
        "skill-agent:",
        "agent:",
        "profile:",
        "mcp:",
    ]

    parts = spec.split("+")
    result = []

    for part in parts:
        part = part.strip()
        # Check if this looks like a valid treatment start
        is_treatment_start = any(
            part == prefix.rstrip(":") or part.startswith(prefix)
            for prefix in TREATMENT_STARTS
        )

        if is_treatment_start or not result:
            # Start of a new treatment or first part
            result.append(part)
        else:
            # '+' was part of a path, merge with previous
            result[-1] += "+" + part

    return result


def create_treatment(
    spec: str,
    top_k: int = 5,
    rerank_threshold: float = 0.3,
    cache_dir: Optional[Path] = None,
) -> Treatment:
    """Create a single :class:`Treatment` from an arm spec.

    Supported specs
    ---------------
    ``baseline``
        Control arm — no augmentation.
    ``docs`` / ``docs:<doc-source>``
        Documentation injection. ``<doc-source>`` is any value accepted by
        :func:`agent_benchmarks.mcp.factory.create_doc_source_client`
        (``context7`` default, ``local:<path>``, ``url:<url>``). Note: because
        a doc source may itself contain a colon (``local:/x``), everything
        after the first ``docs:`` is treated as the doc source.
    ``mcp:<ref>``
        Documentation retrieved through a real MCP server. ``<ref>`` is passed
        to the MCP-protocol client (see ``mcp:`` in the doc-source factory).
    ``profile:<path>``
        Agent persona prompt loaded from a Markdown file.
    ``skill:<path>``
        Agent skill loaded from a ``SKILL.md`` file or directory.
    ``agent:<doc-source>``
        Agentic doc use — the model is given a documentation-search tool over
        ``<doc-source>`` and decides when to call it (defaults to ``context7``).
    ``skill-agent:<path>``
        Agentic skill use — the model is offered the skill via progressive
        disclosure and decides whether to load it.
    ``<spec1>+<spec2>[+...]``
        Combined treatment — merges multiple treatments into one arm.
        Example: ``docs+skill:data/skills/dpnp-quickstart``
        The contexts from all sub-treatments are concatenated.

    Raises:
        ValueError: If the spec is unrecognised or missing an argument.
    """
    spec = spec.strip()

    # Check for combined treatment (e.g., 'docs+skill:path')
    # Exclude mcp: URLs which may contain '+' in query params
    if "+" in spec and not spec.startswith("mcp:"):
        parts = _parse_combined_spec(spec)
        if len(parts) > 1:
            # Recursively create sub-treatments
            sub_treatments = [
                create_treatment(p, top_k=top_k, rerank_threshold=rerank_threshold, cache_dir=cache_dir)
                for p in parts
            ]
            return CombinedTreatment(sub_treatments)

    if spec == "baseline":
        return BaselineTreatment()

    # NOTE: check 'skill-agent:' before 'skill:' / 'agent:' prefix tests.
    if spec.startswith("skill-agent:"):
        from agent_benchmarks.skills import load_skill
        path = spec[len("skill-agent:"):]
        if not path:
            raise ValueError("'skill-agent:' arm requires a path, e.g. 'skill-agent:data/skills/onetbb-quickstart'")
        return SkillAgentTreatment(load_skill(path))

    if spec == "agent" or spec.startswith("agent:"):
        from agent_benchmarks.mcp.factory import create_doc_source_client
        doc_source = spec[len("agent:"):] if spec.startswith("agent:") else "context7"
        client = create_doc_source_client(doc_source or "context7", cache_dir=cache_dir)
        return MCPAgentTreatment(client, name="agent", max_results=top_k)

    if spec == "docs" or spec.startswith("docs:"):
        from agent_benchmarks.mcp.factory import create_doc_source_client
        doc_source = spec[len("docs:"):] if spec.startswith("docs:") else "context7"
        client = create_doc_source_client(doc_source or "context7", cache_dir=cache_dir)
        return DocTreatment(
            client, name="docs", top_k=top_k, rerank_threshold=rerank_threshold
        )

    if spec.startswith("mcp:"):
        from agent_benchmarks.mcp.factory import create_doc_source_client
        if not spec[len("mcp:"):].strip():
            raise ValueError(
                "'mcp:' arm requires a reference, e.g. 'mcp:http=https://mcp.context7.com/mcp'"
            )
        client = create_doc_source_client(spec, cache_dir=cache_dir)
        return DocTreatment(
            client,
            name="mcp_doc",
            top_k=top_k,
            rerank_threshold=rerank_threshold,
            arm_kind="mcp_doc",
        )

    if spec.startswith("profile:"):
        from agent_benchmarks.agent_profiles import load_agent_profile
        path = spec[len("profile:"):]
        if not path:
            raise ValueError("'profile:' arm requires a path, e.g. 'profile:data/agent_profiles/concise_expert.md'")
        return AgentProfileTreatment(load_agent_profile(path))

    if spec.startswith("skill:"):
        from agent_benchmarks.skills import load_skill
        path = spec[len("skill:"):]
        if not path:
            raise ValueError("'skill:' arm requires a path, e.g. 'skill:data/skills/onetbb-quickstart'")
        return SkillTreatment(load_skill(path))

    raise ValueError(
        f"Unknown arm spec: '{spec}'. Valid specs: 'baseline', 'docs[:<source>]', "
        "'mcp:<ref>', 'profile:<path>', 'skill:<path>'."
    )


def create_treatments(
    specs: List[str],
    top_k: int = 5,
    rerank_threshold: float = 0.3,
    cache_dir: Optional[Path] = None,
) -> List[Treatment]:
    """Create a list of treatments, rejecting duplicate arm names."""
    treatments = [
        create_treatment(s, top_k=top_k, rerank_threshold=rerank_threshold, cache_dir=cache_dir)
        for s in specs
    ]
    seen = set()
    for t in treatments:
        if t.name in seen:
            raise ValueError(
                f"Duplicate arm name '{t.name}'. Each arm must have a unique name; "
                "load distinct profiles/skills or rename them."
            )
        seen.add(t.name)
    return treatments
