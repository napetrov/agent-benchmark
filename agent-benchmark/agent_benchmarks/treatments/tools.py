"""Tools offered to the model during agentic treatment arms.

These let the model *decide* to use a capability rather than receiving
pre-injected context: query an MCP doc server, or load a skill on demand
(progressive disclosure — the model first sees only the skill's name and
one-line description, and calls the tool to read the full body).

Faithful skill *script execution* deliberately does not live here: running
bundled scripts needs real sandboxing and belongs on the terminal-bench task
track. These tools are read-only.
"""

import logging

from agent_benchmarks.skills import Skill

from .base import Tool

logger = logging.getLogger(__name__)


class DocQueryTool(Tool):
    """Let the model query a documentation source (MCP/HTTP/local) on demand."""

    kind = "documentation"
    name = "search_documentation"
    description = (
        "Search the official documentation for the library and return the most "
        "relevant excerpts. Call this whenever you are unsure of an exact API, "
        "signature, header, or usage detail."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A focused search query or topic.",
            }
        },
        "required": ["query"],
    }

    def __init__(self, mcp_client, library_id: str, max_results: int = 5, keep: int = 3):
        self.mcp_client = mcp_client
        self.library_id = library_id
        self.max_results = max_results
        self.keep = keep
        self.calls = []  # query strings, for transcript/provenance

    def call(self, query: str = "", **_) -> str:
        self.calls.append(query)
        try:
            docs = self.mcp_client.get_library_docs(
                library_id=self.library_id, query=query, max_results=self.max_results
            )
        except Exception as exc:
            logger.exception("DocQueryTool retrieval failed")
            return f"(documentation search failed: {exc})"
        if not docs:
            return "(no relevant documentation found)"
        chunks = [d.get("content", "") for d in docs[: self.keep]]
        return "\n\n---\n\n".join(c for c in chunks if c) or "(no content)"

    def telemetry_metadata(self):
        meta = super().telemetry_metadata()
        meta.update({
            "library_id": self.library_id,
            "max_results": self.max_results,
            "keep": self.keep,
        })
        return meta


class ViewSkillTool(Tool):
    """Progressive disclosure: load a skill's full instructions on demand.

    Supports multi-file skills: if sibling .md files exist, the tool accepts
    a 'file' parameter to load them individually. SKILL.md is always loaded
    when no file is specified.
    """

    kind = "skill"

    def __init__(self, skill: Skill, max_chars: int = 12_000):
        self.skill = skill
        self.max_chars = max_chars
        self.viewed = False
        # Unique-but-stable tool name per skill.
        safe = "".join(c if c.isalnum() else "_" for c in skill.name)
        self.name = f"view_skill_{safe}"
        self.description = (
            f"Load the full instructions for the '{skill.name}' skill. "
            f"Use it when the task matches: {skill.description}"
        )

        # Build file enum from sibling .md resources
        md_files = [r.name for r in skill.resources if r.suffix == '.md']
        if md_files:
            # Multi-file skill: offer file picker
            self.parameters = {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "enum": ["SKILL.md"] + sorted(md_files),
                        "description": (
                            "Which file to load. Start with 'SKILL.md' to see the navigation "
                            "table that maps your task to the right topic file, then load "
                            "that specific file for detailed guidance."
                        ),
                    }
                },
                "required": [],
            }
        else:
            # Single-file skill: no parameters
            self.parameters = {"type": "object", "properties": {}}

    def call(self, file: str = "SKILL.md", **_) -> str:
        self.viewed = True

        if file == "SKILL.md":
            return self.skill.as_context(self.max_chars)

        # Load sibling .md file
        target = self.skill.path.parent / file
        if not target.exists() or target.suffix != '.md':
            return f"(file '{file}' not found or not a .md file)"

        try:
            content = target.read_text(encoding="utf-8")
            if len(content) > self.max_chars:
                content = content[:self.max_chars].rstrip() + "\n…"
            return f"# Skill: {self.skill.name} — {file}\n\n{content}"
        except Exception as exc:
            logger.exception("Failed to read skill file")
            return f"(failed to read '{file}': {exc})"

    def telemetry_metadata(self):
        meta = super().telemetry_metadata()
        meta.update({
            "skill_name": self.skill.name,
            "skill_path": str(self.skill.path),
            "max_chars": self.max_chars,
        })
        return meta
