"""Concrete treatment arms for each evaluation scenario."""

import logging
from typing import Any, Dict, List, Optional

from agent_benchmarks.agent_profiles import AgentProfile
from agent_benchmarks.skills import Skill

from .base import AgentConfig, Treatment

logger = logging.getLogger(__name__)


class BaselineTreatment(Treatment):
    """No augmentation — the control arm (equivalent to ``without_docs``)."""

    def __init__(self, name: str = "baseline"):
        self.name = name

    def prepare(self, question_text, library_name, library_id=None) -> AgentConfig:
        return AgentConfig(metadata={"arm_kind": "baseline"})


class DocTreatment(Treatment):
    """Documentation injection via an ``MCPClient`` (the original ``with_docs``).

    Retrieves chunks for the question, reranks them, and injects the top
    survivors as context. Works for any doc source — local files, a URL, the
    Context7 HTTP API, or a real MCP server — since they all implement the same
    ``MCPClient`` retrieval contract.
    """

    def __init__(
        self,
        mcp_client,
        name: str = "docs",
        top_k: int = 5,
        rerank_threshold: float = 0.3,
        keep: int = 3,
        reranker=None,
        arm_kind: str = "docs",
    ):
        self.name = name
        self.mcp_client = mcp_client
        self.top_k = top_k
        self.keep = keep
        self.arm_kind = arm_kind
        self.reranker = reranker or self._default_reranker(rerank_threshold)

    @staticmethod
    def _default_reranker(threshold: float):
        from agent_benchmarks.eval.reranker import (
            SimpleReranker,
            SentenceTransformerReranker,
            SENTENCE_TRANSFORMERS_AVAILABLE,
        )

        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                return SentenceTransformerReranker(threshold=threshold)
            except Exception as exc:  # pragma: no cover - env dependent
                logger.warning("Semantic reranker unavailable (%s); using lexical", exc)
        return SimpleReranker(threshold=threshold)

    def prepare(self, question_text, library_name, library_id=None) -> AgentConfig:
        lib_id = library_id or library_name
        metadata: Dict[str, Any] = {
            "arm_kind": self.arm_kind,
            "raw_count": 0,
            "after_rerank": 0,
            "top_score": None,
        }
        try:
            raw_docs = self.mcp_client.get_library_docs(
                library_id=lib_id, query=question_text, max_results=self.top_k
            )
        except Exception:
            logger.exception("Context retrieval failed for arm %s", self.name)
            metadata["error"] = "retrieval_failed"
            return AgentConfig(metadata=metadata)

        metadata["raw_count"] = len(raw_docs)
        if not raw_docs:
            return AgentConfig(metadata=metadata)

        try:
            reranked = self.reranker.rerank(question_text, raw_docs)
        except Exception:
            logger.exception("Rerank failed for arm %s; using raw docs", self.name)
            metadata["error"] = "rerank_failed"
            reranked = raw_docs
        metadata["after_rerank"] = len(reranked)
        if not reranked:
            return AgentConfig(metadata=metadata)

        scores = [d.get("relevance_score", 0) for d in reranked]
        metadata["top_score"] = round(max(scores), 3) if scores else None
        return AgentConfig(injected_context=reranked[: self.keep], metadata=metadata)


class MCPAgentTreatment(Treatment):
    """Agentic MCP doc use — offer a doc-search tool; the model decides to call it.

    This is the faithful test of whether a doc source is *usable by an agent*,
    not just whether its text is relevant: the model must choose good queries
    and integrate the results. Contrast with :class:`DocTreatment`, which
    pre-injects retrieved chunks.
    """

    def __init__(
        self,
        mcp_client,
        name: str = "mcp_agent",
        max_results: int = 5,
        keep: int = 3,
        arm_kind: str = "mcp_agent",
    ):
        self.name = name
        self.mcp_client = mcp_client
        self.max_results = max_results
        self.keep = keep
        self.arm_kind = arm_kind

    def prepare(self, question_text, library_name, library_id=None) -> AgentConfig:
        from .tools import DocQueryTool

        lib_id = library_id or library_name
        tool = DocQueryTool(
            self.mcp_client, lib_id, max_results=self.max_results, keep=self.keep
        )
        return AgentConfig(
            tools=[tool],
            metadata={"arm_kind": self.arm_kind, "library_id": lib_id},
        )


class SkillAgentTreatment(Treatment):
    """Agentic skill use — offer the skill via progressive disclosure.

    The model sees only the skill's name + one-line description (in the tool
    schema) and must *decide* to load the full instructions, mirroring how
    skills are actually consumed. Running the skill's bundled scripts needs a
    sandbox and stays on the terminal-bench task track.
    """

    def __init__(self, skill: Skill, name: Optional[str] = None, max_chars: int = 12_000):
        self.skill = skill
        self.max_chars = max_chars
        self.name = name or f"skill_agent:{skill.name}"

    def prepare(self, question_text, library_name, library_id=None) -> AgentConfig:
        from .tools import ViewSkillTool

        return AgentConfig(
            tools=[ViewSkillTool(self.skill, self.max_chars)],
            metadata={
                "arm_kind": "skill_agent",
                "skill_name": self.skill.name,
                "skill_path": str(self.skill.path),
            },
        )


class AgentProfileTreatment(Treatment):
    """Agent persona prompt — swaps the answering agent's system prompt."""

    def __init__(self, profile: AgentProfile, name: Optional[str] = None):
        self.profile = profile
        self.name = name or f"profile:{profile.id}"

    def prepare(self, question_text, library_name, library_id=None) -> AgentConfig:
        return AgentConfig(
            system_prompt=self.profile.system_prompt,
            metadata={
                "arm_kind": "agent_profile",
                "profile_id": self.profile.id,
                "profile_name": self.profile.name,
            },
        )


class SkillTreatment(Treatment):
    """Agent skill injected as context (skill-as-context evaluation mode).

    This is the cheap, single-shot mode: the skill body is injected like a doc
    chunk. The faithful agentic mode (the agent decides to invoke the skill and
    run its bundled scripts) belongs on the terminal-bench task track.
    """

    def __init__(self, skill: Skill, name: Optional[str] = None, max_chars: int = 12_000):
        self.skill = skill
        self.max_chars = max_chars
        self.name = name or f"skill:{skill.name}"

    def prepare(self, question_text, library_name, library_id=None) -> AgentConfig:
        chunk = {
            "content": self.skill.as_context(self.max_chars),
            "source": f"skill:{self.skill.name}",
            "relevance_score": 1.0,
        }
        return AgentConfig(
            injected_context=[chunk],
            metadata={
                "arm_kind": "skill",
                "skill_name": self.skill.name,
                "skill_path": str(self.skill.path),
            },
        )


class CombinedTreatment(Treatment):
    """Combine multiple treatments into a single arm (e.g., docs + skill).

    This treatment merges the contexts, tools, and metadata from multiple
    sub-treatments, allowing evaluation of combined approaches (e.g., "does
    docs + skill together outperform skill alone?").

    The sub-treatments are prepared independently, then their outputs are merged:
    - injected_context: concatenated (docs first, then skills)
    - tools: concatenated (for agentic arms)
    - system_prompt: first non-None value wins
    - metadata: tracks all sub-treatment metadata

    Example spec: ``docs+skill:data/skills/dpnp-quickstart``
    """

    def __init__(self, treatments: List[Treatment], name: Optional[str] = None):
        self.treatments = treatments
        self.name = name or "+".join(t.name for t in treatments)

    def prepare(self, question_text, library_name, library_id=None) -> AgentConfig:
        # Prepare all sub-treatments independently
        configs = [
            t.prepare(question_text, library_name, library_id) for t in self.treatments
        ]

        # Merge injected contexts (docs first, then skills, for consistency)
        merged_context = []
        for cfg in configs:
            merged_context.extend(cfg.injected_context)

        # Merge tools (for agentic arms - rare, but supported)
        merged_tools = []
        for cfg in configs:
            merged_tools.extend(cfg.tools)

        # Merge metadata - track each sub-treatment's contribution
        merged_metadata = {
            "arm_kind": "combined",
            "combined_count": len(self.treatments),
            "treatments": [],
        }
        for t, cfg in zip(self.treatments, configs, strict=True):
            merged_metadata["treatments"].append(
                {"name": t.name, "arm_kind": cfg.metadata.get("arm_kind"), **cfg.metadata}
            )

        # System prompt: first non-None wins (profiles rarely combined with docs/skills)
        system_prompt = next((c.system_prompt for c in configs if c.system_prompt), None)

        return AgentConfig(
            system_prompt=system_prompt,
            injected_context=merged_context,
            tools=merged_tools,
            metadata=merged_metadata,
        )
