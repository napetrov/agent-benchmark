"""Runtime plugins for treatment-arm runs.

Plugins are behavior modifiers applied inside a fixed model/harness cell.  The
first implementation supports prompt-middleware plugins, including a Caveman
style brevity plugin, and records a canonical plugin-set identity for reports.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from agent_benchmarks.treatments.base import AgentConfig, Treatment


EMPTY_PLUGIN_SET_ID = "sha256:e3b0c44298fc1c149afbf4c8996fb924"


_CAVEMAN_LEVELS = {
    "lite": (
        "Be concise. Prefer short direct sentences. Keep all technical facts, "
        "numbers, warnings, and code intact."
    ),
    "full": (
        "Respond in caveman style: terse, blunt, low-fluff fragments. Keep all "
        "technical substance, exact API names, numbers, warnings, and code intact."
    ),
    "ultra": (
        "Respond in ultra-compressed caveman style. Use minimal words. Preserve "
        "technical correctness, required caveats, exact identifiers, and code."
    ),
}

_PROMPT_MIDDLEWARE_HARNESSES = {
    "arms-runner",
    "single-shot",
    "agent",
    "openclaw-agent",
}


@dataclass(frozen=True)
class Plugin:
    """A runtime behavior modifier applied to an ``AgentConfig``."""

    id: str
    ref: str
    kind: str
    version: str
    config: Dict[str, Any] = field(default_factory=dict)
    system_prompt: Optional[str] = None

    def apply(self, cfg: AgentConfig) -> AgentConfig:
        """Return a copy of *cfg* with this plugin applied."""
        system_prompt = cfg.system_prompt
        if self.system_prompt:
            system_prompt = (
                f"{system_prompt.rstrip()}\n\n{self.system_prompt}"
                if system_prompt
                else self.system_prompt
            )

        metadata = dict(cfg.metadata)
        plugins = list(metadata.get("plugins", []))
        plugins.append(self.metadata())
        metadata["plugins"] = plugins
        return AgentConfig(
            system_prompt=system_prompt,
            injected_context=list(cfg.injected_context),
            tools=list(cfg.tools),
            metadata=metadata,
        )

    def metadata(self) -> Dict[str, Any]:
        """Stable, serialisable plugin metadata."""
        return {
            "id": self.id,
            "ref": self.ref,
            "kind": self.kind,
            "version": self.version,
            "config": dict(self.config),
            "config_hash": _hash_obj(self.config),
        }


class PluginWrappedTreatment(Treatment):
    """Treatment wrapper that applies a plugin set after arm preparation."""

    def __init__(self, inner: Treatment, plugins: Iterable[Plugin]):
        self.inner = inner
        self.plugins = list(plugins)
        self.name = inner.name
        self.plugin_set = plugin_set_metadata(self.plugins)

    def prepare(self, question_text, library_name, library_id=None) -> AgentConfig:
        cfg = self.inner.prepare(question_text, library_name, library_id)
        for plugin in self.plugins:
            cfg = plugin.apply(cfg)

        metadata = dict(cfg.metadata)
        metadata["plugin_set"] = self.plugin_set["plugin_set"]
        metadata["plugin_set_id"] = self.plugin_set["plugin_set_id"]
        return AgentConfig(
            system_prompt=cfg.system_prompt,
            injected_context=cfg.injected_context,
            tools=cfg.tools,
            metadata=metadata,
        )


def create_plugin(spec: str) -> Plugin:
    """Create one plugin from a CLI spec.

    Supported refs:
      - ``plugin:caveman``
      - ``plugin:caveman:<lite|full|ultra>``
      - ``caveman`` / ``caveman:<level>`` as a shorthand
    """
    raw = spec.strip()
    if not raw:
        raise ValueError("Empty plugin spec")

    ref = raw
    if raw.startswith("plugin:"):
        raw = raw[len("plugin:"):]

    parts = raw.split(":")
    plugin_id = parts[0].strip()
    if plugin_id != "caveman":
        raise ValueError(
            f"Unknown plugin spec: '{spec}'. Valid specs: 'plugin:caveman[:lite|full|ultra]'."
        )
    if len(parts) > 2:
        raise ValueError(
            f"Invalid caveman plugin spec: '{spec}'. Use 'plugin:caveman[:level]'."
        )
    level = parts[1].strip() if len(parts) == 2 else "full"
    if level not in _CAVEMAN_LEVELS:
        raise ValueError(
            f"Invalid caveman level '{level}'. Valid levels: {', '.join(_CAVEMAN_LEVELS)}."
        )

    return Plugin(
        id="caveman",
        ref=ref if ref.startswith("plugin:") else f"plugin:{ref}",
        kind="prompt_middleware",
        version="0.1.0",
        config={"level": level, "target_style": "terse"},
        system_prompt=_CAVEMAN_LEVELS[level],
    )


def create_plugins(specs: Iterable[str]) -> List[Plugin]:
    """Create plugins from a sequence of CLI specs."""
    return [create_plugin(s) for s in specs if s.strip()]


def validate_plugins_for_harness(plugins: Iterable[Plugin], harness: str) -> None:
    """Reject plugin/harness combinations that cannot execute faithfully."""
    for plugin in plugins:
        if plugin.kind == "prompt_middleware" and harness not in _PROMPT_MIDDLEWARE_HARNESSES:
            raise ValueError(
                f"Plugin '{plugin.ref}' is prompt_middleware and is not supported by "
                f"harness '{harness}'. Supported harnesses: "
                f"{', '.join(sorted(_PROMPT_MIDDLEWARE_HARNESSES))}."
            )


def wrap_treatments(treatments: Iterable[Treatment], plugins: Iterable[Plugin]) -> List[Treatment]:
    """Apply the same plugin set to every treatment arm."""
    plugins = list(plugins)
    if not plugins:
        return list(treatments)
    return [PluginWrappedTreatment(t, plugins) for t in treatments]


def plugin_set_metadata(plugins: Iterable[Plugin]) -> Dict[str, Any]:
    """Return canonical metadata for an ordered plugin set."""
    items = [p.metadata() for p in plugins]
    if not items:
        return {
            "plugin_set": "none",
            "plugin_set_id": EMPTY_PLUGIN_SET_ID,
            "plugins": [],
        }
    label = "+".join(
        f"{p['id']}:{p.get('config', {}).get('level')}"
        if p.get("id") == "caveman" and p.get("config", {}).get("level")
        else p["id"]
        for p in items
    )
    return {
        "plugin_set": label,
        "plugin_set_id": _hash_obj(items),
        "plugins": items,
    }


def _hash_obj(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()[:32]
