"""Tests for the agentic tool-calling loop and agentic treatment arms."""

import json

import agent_benchmarks.eval.agent_runner as ar_mod
from agent_benchmarks.eval.agent_runner import run_agent_loop
from agent_benchmarks.treatments import (
    MCPAgentTreatment,
    SkillAgentTreatment,
    create_treatment,
)
from agent_benchmarks.treatments.tools import DocQueryTool, ViewSkillTool
from agent_benchmarks.skills import load_skill


# ── fake litellm plumbing ────────────────────────────────────────────────
class _FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, tool_call_id, name, arguments):
        self.id = tool_call_id
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeUsage:
    prompt_tokens = 5
    completion_tokens = 3
    total_tokens = 8


class _FakeResp:
    def __init__(self, message):
        self.choices = [type("C", (), {"message": message})()]
        self.usage = _FakeUsage()


def _scripted_completion(steps):
    """Return a chat_completion stub yielding the given messages in order."""
    calls = {"n": 0}

    def fake(messages, model, provider="openai", tools=None, tool_choice=None,
             api_key=None, **kw):
        idx = min(calls["n"], len(steps) - 1)
        calls["n"] += 1
        return _FakeResp(steps[idx])

    return fake, calls


class _FakeDocClient:
    def get_library_docs(self, library_id, query, max_results=5, **kw):
        return [{"content": f"DOC about {query}", "relevance_score": 1.0}]


# ── tools ─────────────────────────────────────────────────────────────────
def test_doc_query_tool_schema_and_call():
    tool = DocQueryTool(_FakeDocClient(), "lib/x")
    schema = tool.schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "search_documentation"
    assert "query" in schema["function"]["parameters"]["properties"]
    out = tool.call(query="parallel_for")
    assert "DOC about parallel_for" in out
    assert tool.calls == ["parallel_for"]


def test_view_skill_tool():
    skill = load_skill("data/skills/onetbb-quickstart")
    tool = ViewSkillTool(skill)
    assert tool.name.startswith("view_skill_")
    body = tool.call()
    assert "parallel_for" in body
    assert tool.viewed is True


def test_view_skill_tool_multifile(tmp_path):
    """Test that multi-file skills offer file parameter and can load sibling files."""
    # Create a minimal multi-file skill fixture
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()

    # Create SKILL.md
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("""---
name: test-skill
description: Test skill for multi-file support
---
# Test Skill

Navigation table here.
""")

    # Create topic files
    (skill_dir / "topic-a.md").write_text("# Topic A\nContent for topic A.")
    (skill_dir / "topic-b.md").write_text("# Topic B\nContent for topic B.")

    # Load skill and create tool
    skill = load_skill(skill_dir)
    tool = ViewSkillTool(skill)

    # Check that tool has file parameter with enum of available files
    assert "properties" in tool.parameters
    assert "file" in tool.parameters["properties"]

    # Multi-file skill: should have enum with SKILL.md + sibling .md files
    file_param = tool.parameters["properties"]["file"]
    assert file_param["type"] == "string"
    assert "enum" in file_param
    assert "SKILL.md" in file_param["enum"]
    assert "topic-a.md" in file_param["enum"]
    assert "topic-b.md" in file_param["enum"]
    assert len(file_param["enum"]) == 3  # SKILL.md + 2 topics

    # Test loading SKILL.md (default)
    body = tool.call()
    assert "test-skill" in body.lower()
    assert "Navigation table" in body
    assert tool.viewed is True

    # Test loading a specific topic file
    topic_content = tool.call(file="topic-a.md")
    assert "topic-a.md" in topic_content
    assert "Topic A" in topic_content
    assert "Content for topic A" in topic_content


# ── loop ────────────────────────────────────────────────────────────────
def test_agent_loop_calls_tool_then_answers(monkeypatch):
    tool = DocQueryTool(_FakeDocClient(), "lib/x")
    steps = [
        _FakeMessage(tool_calls=[_FakeToolCall("c1", "search_documentation",
                                              '{"query": "reduce"}')]),
        _FakeMessage(content="Final answer using docs."),
    ]
    fake, calls = _scripted_completion(steps)
    monkeypatch.setattr(ar_mod, "chat_completion", fake)

    result = run_agent_loop("How to reduce?", [tool], model="m", provider="openai")
    assert result["answer"] == "Final answer using docs."
    assert result["stopped_reason"] == "answered"
    assert result["tool_call_count"] == 1
    assert result["transcript"][0]["tool"] == "search_documentation"
    assert result["transcript"][0]["iteration"] == 1
    assert result["transcript"][0]["arguments"] == {"query": "reduce"}
    assert result["tool_usage"]["used_any_tool"] is True
    assert result["tool_usage"]["tool_call_count_by_name"]["search_documentation"] == 1
    assert result["token_usage"]["total_tokens"] == 16  # two rounds × 8
    # Telemetry: usage record, per-turn detail, per-tool timing.
    assert result["usage"]["total_tokens"] == 16
    assert result["usage"]["n_calls"] == 2
    assert len(result["per_turn"]) == 2
    assert "latency_sec" in result["per_turn"][0]
    assert "tool_elapsed_sec" in result["transcript"][0]
    json.dumps(result)


def test_agent_loop_answers_without_tools(monkeypatch):
    tool = DocQueryTool(_FakeDocClient(), "lib/x")
    fake, _ = _scripted_completion([_FakeMessage(content="Direct answer.")])
    monkeypatch.setattr(ar_mod, "chat_completion", fake)
    result = run_agent_loop("q", [tool], model="m")
    assert result["answer"] == "Direct answer."
    assert result["tool_call_count"] == 0
    assert result["tool_usage"]["used_any_tool"] is False
    assert result["tool_usage"]["called_tools"] == []


def test_agent_loop_reports_skill_discoverability(monkeypatch):
    skill = load_skill("data/skills/onetbb-quickstart")
    tool = ViewSkillTool(skill)
    steps = [
        _FakeMessage(tool_calls=[_FakeToolCall("c1", tool.name, "{}")]),
        _FakeMessage(content="Used skill."),
    ]
    fake, _ = _scripted_completion(steps)
    monkeypatch.setattr(ar_mod, "chat_completion", fake)

    result = run_agent_loop("q", [tool], model="m")

    skill_usage = result["tool_usage"]["skill"]
    assert skill_usage["offered"] is True
    assert skill_usage["called"] is True
    assert skill_usage["call_count"] == 1
    assert skill_usage["first_call_iteration"] == 1
    assert skill_usage["offered_tools"][0]["skill_name"] == "onetbb-quickstart"


def test_agent_loop_hits_max_iterations(monkeypatch):
    tool = DocQueryTool(_FakeDocClient(), "lib/x")
    # Always asks for a tool → never answers until forced.
    loop_step = _FakeMessage(tool_calls=[_FakeToolCall("c", "search_documentation",
                                                       '{"query": "x"}')])
    final = _FakeMessage(content="Forced final answer.")
    steps = [loop_step, loop_step, final]
    fake, _ = _scripted_completion(steps)
    monkeypatch.setattr(ar_mod, "chat_completion", fake)

    result = run_agent_loop("q", [tool], model="m", max_iterations=2)
    assert result["stopped_reason"] == "max_iterations"
    assert result["iterations"] == 2
    assert result["answer"] == "Forced final answer."


def test_agent_loop_unknown_tool_is_handled(monkeypatch):
    tool = DocQueryTool(_FakeDocClient(), "lib/x")
    steps = [
        _FakeMessage(tool_calls=[_FakeToolCall("c1", "nonexistent", "{}")]),
        _FakeMessage(content="ok"),
    ]
    fake, _ = _scripted_completion(steps)
    monkeypatch.setattr(ar_mod, "chat_completion", fake)
    result = run_agent_loop("q", [tool], model="m")
    assert "unknown tool" in result["transcript"][0]["result_preview"]


# ── agentic arms ──────────────────────────────────────────────────────────
def test_mcp_agent_treatment_is_agentic():
    t = MCPAgentTreatment(_FakeDocClient())
    cfg = t.prepare("q", "oneTBB", "lib/x")
    assert cfg.is_agentic
    assert len(cfg.tools) == 1
    assert cfg.metadata["arm_kind"] == "mcp_agent"


def test_skill_agent_treatment_is_agentic():
    skill = load_skill("data/skills/onetbb-quickstart")
    t = SkillAgentTreatment(skill)
    cfg = t.prepare("q", "oneTBB")
    assert cfg.is_agentic
    assert cfg.tools[0].name.startswith("view_skill_")


def test_factory_builds_agentic_specs():
    assert isinstance(create_treatment("skill-agent:data/skills/onetbb-quickstart"),
                      SkillAgentTreatment)
    # 'agent:<source>' with a nested colon must not be mis-parsed
    t = create_treatment("agent:context7")
    assert isinstance(t, MCPAgentTreatment)
