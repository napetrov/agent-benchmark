"""Agentic tool-calling loop for treatment arms that offer tools.

Given an :class:`~agent_benchmarks.treatments.base.AgentConfig` whose ``tools``
list is non-empty, this runs a bounded loop: send the conversation + tool
schemas to the model, execute any tool calls it makes, feed the results back,
and repeat until the model answers or the iteration budget is exhausted. It
returns the final answer plus a transcript of the tool calls made — the signal
for whether an agent actually *uses* an MCP doc server or a skill.

In-process tools are read-only (doc search, skill viewing). Faithful skill
*script execution* lives on the terminal-bench task track, which provides real
sandbox isolation.
"""

import json
import logging
import time
from typing import Any, Dict, List

from agent_benchmarks.llm import chat_completion, _extract_usage
from agent_benchmarks.metrics.usage import UsageRecord
from agent_benchmarks.treatments.base import Tool

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 6


def _message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return content or ""


def _extract_tool_calls(message: Any) -> List[Any]:
    calls = getattr(message, "tool_calls", None)
    if calls is None and isinstance(message, dict):
        calls = message.get("tool_calls")
    return calls or []


def _tool_call_fields(tc: Any):
    """Return (id, name, arguments_str) from a tool-call object or dict."""
    if isinstance(tc, dict):
        fn = tc.get("function", {})
        return tc.get("id"), fn.get("name"), fn.get("arguments") or "{}"
    fn = getattr(tc, "function", None)
    name = getattr(fn, "name", None)
    args = getattr(fn, "arguments", None) or "{}"
    return getattr(tc, "id", None), name, args


def run_agent_loop(
    question: str,
    tools: List[Tool],
    model: str,
    provider: str = "openai",
    system_prompt: str = None,
    api_key: str = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> Dict[str, Any]:
    """Drive a tool-calling conversation to a final answer.

    Returns a dict with: ``answer``, ``transcript`` (list of tool-call records,
    each with ``tool_elapsed_sec``), ``iterations``, ``stopped_reason``,
    ``usage`` (serialised metrics accumulated across turns), ``token_usage`` (the
    legacy 3-key alias), and ``per_turn`` (per-turn latency/token detail).
    """
    by_name = {t.name: t for t in tools}
    schemas = [t.schema() for t in tools]

    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": question})

    transcript: List[Dict[str, Any]] = []
    usage_total = UsageRecord(model=model, provider=provider, n_calls=0)
    per_turn: List[Dict[str, Any]] = []
    stopped_reason = "answered"
    answer = ""

    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        t_turn = time.time()
        resp = chat_completion(
            messages=messages, model=model, provider=provider,
            tools=schemas, api_key=api_key,
        )
        turn_usage = _extract_usage(resp, model, provider, latency_sec=time.time() - t_turn)
        usage_total = usage_total + turn_usage
        per_turn.append({
            "latency_sec": round(turn_usage.latency_sec, 4),
            "prompt_tokens": turn_usage.prompt_tokens,
            "completion_tokens": turn_usage.completion_tokens,
            "cache_read_tokens": turn_usage.cache_read_tokens,
        })

        message = resp.choices[0].message
        tool_calls = _extract_tool_calls(message)

        if not tool_calls:
            answer = _message_text(message)
            stopped_reason = "answered"
            break

        # Record the assistant turn (with its tool calls) so the model has context.
        serialized_calls = []
        for tc in tool_calls:
            tc_id, name, args = _tool_call_fields(tc)
            serialized_calls.append({
                "id": tc_id,
                "type": "function",
                "function": {"name": name, "arguments": args},
            })
        messages.append({
            "role": "assistant",
            "content": _message_text(message),
            "tool_calls": serialized_calls,
        })

        # Execute each tool call and append its result.
        for tc in tool_calls:
            tc_id, name, args_str = _tool_call_fields(tc)
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {}
            tool = by_name.get(name)
            t_tool = time.time()
            if tool is None:
                result = f"(unknown tool: {name})"
            else:
                try:
                    result = tool.call(**args)
                except Exception as exc:  # tool failures must not crash the run
                    logger.exception("Tool %s raised", name)
                    result = f"(tool error: {exc})"
            transcript.append({"tool": name, "arguments": args,
                               "result_preview": result[:200],
                               "tool_elapsed_sec": round(time.time() - t_tool, 4)})
            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": result,
            })
    else:
        stopped_reason = "max_iterations"
        # Make a final, tool-free attempt so we still return an answer.
        messages.append({
            "role": "user",
            "content": "Provide your final answer now without calling tools.",
        })
        t_turn = time.time()
        resp = chat_completion(messages=messages, model=model, provider=provider, api_key=api_key)
        turn_usage = _extract_usage(resp, model, provider, latency_sec=time.time() - t_turn)
        usage_total = usage_total + turn_usage
        per_turn.append({
            "latency_sec": round(turn_usage.latency_sec, 4),
            "prompt_tokens": turn_usage.prompt_tokens,
            "completion_tokens": turn_usage.completion_tokens,
            "cache_read_tokens": turn_usage.cache_read_tokens,
        })
        answer = _message_text(resp.choices[0].message)

    return {
        "answer": answer,
        "transcript": transcript,
        "iterations": iteration,
        "tool_call_count": len(transcript),
        "stopped_reason": stopped_reason,
        "usage": usage_total.as_metrics_dict(answer_chars=len(answer or "")),
        "token_usage": usage_total.as_token_usage_dict(),
        "per_turn": per_turn,
    }
