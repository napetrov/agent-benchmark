"""Core treatment-arm abstraction."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class Tool(ABC):
    """A callable the agent may invoke during an agentic arm.

    Tools turn a treatment from "inject this context" into "offer this
    capability and let the model decide whether to use it" — e.g. querying an
    MCP doc server or loading a skill on demand (progressive disclosure).
    """

    #: Tool name exposed to the model (must be a valid function name).
    name: str = "tool"
    #: One-line description the model uses to decide when to call it.
    description: str = ""
    #: JSON-schema ``parameters`` object for the tool's arguments.
    parameters: Dict[str, Any] = {"type": "object", "properties": {}}

    @abstractmethod
    def call(self, **kwargs) -> str:
        """Execute the tool and return a string result for the model."""
        raise NotImplementedError

    def schema(self) -> Dict[str, Any]:
        """Return the OpenAI/litellm tool schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def telemetry_metadata(self) -> Dict[str, Any]:
        """Return stable, non-secret metadata for usage/discoverability reports."""
        return {
            "name": self.name,
            "kind": getattr(self, "kind", "tool"),
        }


@dataclass
class AgentConfig:
    """The agent setup produced by a treatment for one question.

    Attributes:
        system_prompt: Optional system prompt (agent persona). ``None`` keeps
            the model's default behavior.
        injected_context: Retrieved/loaded chunks to prepend to the prompt.
            Each chunk is a dict with at least a ``content`` key, matching the
            shape returned by ``MCPClient.get_library_docs``.
        tools: Tools offered to the model. When non-empty, the arm is run
            through the agentic tool-calling loop instead of single-shot
            injection.
        metadata: Free-form provenance for the report (retrieval stats, profile
            id, skill name, …).
    """

    system_prompt: Optional[str] = None
    injected_context: List[Dict[str, Any]] = field(default_factory=list)
    tools: List[Tool] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_context(self) -> bool:
        return bool(self.injected_context)

    @property
    def is_agentic(self) -> bool:
        return bool(self.tools)


class Treatment(ABC):
    """One arm of an N-way evaluation.

    Subclasses implement :meth:`prepare`, returning the :class:`AgentConfig`
    used to answer a single question. Treatments must be safe to reuse across
    questions (any per-question state lives in the returned config).
    """

    #: Stable arm identifier used as the key in result/report tables.
    name: str = "treatment"

    @abstractmethod
    def prepare(
        self,
        question_text: str,
        library_name: str,
        library_id: Optional[str] = None,
    ) -> AgentConfig:
        """Build the agent config for *question_text*."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<{type(self).__name__} name={self.name!r}>"
