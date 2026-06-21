"""Known coding harness aliases and command-template resolution."""

from __future__ import annotations

from .command import CommandHarness


def known_harnesses() -> dict[str, str]:
    """Human-readable descriptions of built-in harness aliases."""

    return {
        "codex": "Codex CLI via Harbor agent 'codex'",
        "claude-code": "Claude Code via Harbor agent 'claude-code'",
        "terminal-bench:<agent>": "Arbitrary Harbor/terminal-bench agent id",
        "command:<template>": "Custom shell-like command template",
    }


def create_harness(harness: str, *, command_template: str | None = None) -> CommandHarness:
    """Create a command-backed harness adapter.

    Built-ins use Harbor because the repository's executable tasks already follow
    the Harbor/terminal-bench task format. A custom template may use placeholders:
    ``{task_path}``, ``{task}``, ``{model}``, ``{output_dir}``, ``{prompt}``.
    """

    if command_template:
        return CommandHarness(harness_id=harness, command_template=command_template, kind="command")
    if harness == "codex":
        return _harbor("codex", "codex")
    if harness == "claude-code":
        return _harbor("claude-code", "claude-code")
    if harness.startswith("terminal-bench:"):
        agent = harness.split(":", 1)[1]
        if not agent:
            raise ValueError("terminal-bench harness requires an agent id, e.g. terminal-bench:codex")
        return _harbor(harness, agent)
    if harness.startswith("command:"):
        template = harness.split(":", 1)[1]
        if not template:
            raise ValueError("command harness requires a command template")
        return CommandHarness(harness_id=harness, command_template=template, kind="command")
    raise ValueError(
        f"Unknown harness '{harness}'. Known: {', '.join(known_harnesses())}; "
        "or pass --command-template."
    )


def _harbor(harness_id: str, agent: str) -> CommandHarness:
    return CommandHarness(
        harness_id=harness_id,
        kind="harbor",
        command_template=(
            "harbor run -p {task_path} -a " + agent + " -m {model} "
            "--jobs-dir {output_dir}"
        ),
    )
