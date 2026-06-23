"""Thin LLM wrapper using litellm — one interface for all providers.

Usage:
    from agent_benchmarks.llm import llm_call
    text = llm_call("Your prompt", model="gpt-4o-mini", provider="openai")
"""
import os
import time
import logging
from typing import Optional

from agent_benchmarks.metrics.usage import UsageRecord

logger = logging.getLogger(__name__)

# Models for which litellm has no pricing — logged once each, then suppressed.
_COST_UNKNOWN_LOGGED: set = set()

# Backward-compatibility shims for existing tests/modules.
LANGCHAIN_AVAILABLE = True

# Errors that are worth retrying (rate limits, timeouts, transient network)
_RETRYABLE_SUBSTRINGS = (
    "rate_limit", "ratelimit", "rate limit",
    "timeout", "timed out",
    "connection", "server error", "503", "502", "529",
    "overloaded",
)


class _Resp:
    def __init__(self, content: str, usage=None):
        self.content = content
        self.usage = usage   # UsageRecord | None — lets callers (judge) track cost


class ChatOpenAI:
    """LangChain-compatible shim backed by llm_call."""

    def __init__(self, model: str, api_key: Optional[str] = None, **kwargs):
        self.model = model
        self.api_key = api_key

    def invoke(self, prompt: str):
        """Invoke the model with a prompt; response carries a UsageRecord."""
        text, usage = llm_call_with_usage(prompt, self.model, provider="openai", api_key=self.api_key)
        return _Resp(text, usage=usage)


class ChatAnthropic:
    """LangChain-compatible shim backed by llm_call."""

    def __init__(self, model: str, api_key: Optional[str] = None, **kwargs):
        self.model = model
        self.api_key = api_key

    def invoke(self, prompt: str):
        """Invoke the model with a prompt; response carries a UsageRecord."""
        text, usage = llm_call_with_usage(prompt, self.model, provider="anthropic", api_key=self.api_key)
        return _Resp(text, usage=usage)


def _is_retryable(exc: Exception) -> bool:
    """Return True if the exception is worth retrying."""
    msg = str(exc).lower()
    return any(s in msg for s in _RETRYABLE_SUBSTRINGS)


def _resolve_api_key(provider: str, api_key: Optional[str]) -> str:
    """Resolve API key from env vars or file: references."""
    if not api_key:
        env_map = {
            "anthropic":  "ANTHROPIC_API_KEY",
            "openai":     "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "bedrock":    "AWS_ACCESS_KEY_ID",
            "google":     "GEMINI_API_KEY",
            "gemini":     "GEMINI_API_KEY",
        }
        api_key = os.environ.get(env_map.get(provider, "OPENAI_API_KEY"), "")
    if api_key and api_key.startswith("file:"):
        key_path = os.path.expanduser(api_key[len("file:"):])
        try:
            with open(key_path) as _f:
                api_key = _f.read().strip()
        except OSError as exc:
            raise ValueError(f"Cannot read API key from file '{key_path}': {exc}") from exc
    return api_key


def _build_litellm_model(model: str, provider: str) -> str:
    """Build litellm model string from model + provider."""
    if provider == "openrouter":
        return model if model.startswith("openrouter/") else f"openrouter/{model}"
    elif provider == "openai-codex":
        return f"openai/{model}"
    elif "/" in model:
        return model
    elif provider == "openai":
        return model
    elif provider in ("google", "gemini", "google-vertex"):
        return f"vertex_ai/{model}"
    elif provider == "amazon-bedrock":
        return f"bedrock/{model}"
    else:
        return f"{provider}/{model}"


def _safe_completion_cost(resp, model: str, litellm_model: Optional[str] = None) -> Optional[float]:
    """Dollar cost of a completion via litellm, or ``None`` if no pricing.

    A missing price is logged once per model and returns ``None`` — distinct
    from a genuinely free ``0.0`` call.

    ``litellm_model`` is the provider-prefixed model string (e.g.
    ``vertex_ai/claude-3-5-haiku@20241022``). Passing it is required for
    providers whose response ``model`` field is bare (Vertex AI returns
    ``claude-3-5-haiku@...`` with no ``vertex_ai/`` prefix), which otherwise
    makes ``completion_cost`` fail with "LLM Provider NOT provided" → null cost.
    """
    try:
        from litellm import completion_cost

        kwargs = {"completion_response": resp}
        if litellm_model:
            kwargs["model"] = litellm_model
        cost = completion_cost(**kwargs)
        if cost is None:
            raise ValueError("completion_cost returned None")
        return float(cost)
    except Exception as exc:
        if model not in _COST_UNKNOWN_LOGGED:
            _COST_UNKNOWN_LOGGED.add(model)
            logger.info("No litellm pricing for model %r; cost_usd will be null (%s)", model, exc)
        return None


def _extract_usage(
    resp,
    model: str,
    provider: str,
    latency_sec: float = 0.0,
    ttft_sec: Optional[float] = None,
    litellm_model: Optional[str] = None,
) -> UsageRecord:
    """Build a :class:`UsageRecord` from a litellm response (defensive).

    Pulls tokens, cache tokens (Anthropic ``cache_creation_input_tokens`` /
    ``cache_read_input_tokens``; OpenAI ``prompt_tokens_details.cached_tokens``),
    and reasoning tokens (``completion_tokens_details.reasoning_tokens``) where
    the provider exposes them; every field defaults to 0 otherwise.
    """
    prompt_tokens = completion_tokens = total_tokens = 0
    reasoning_tokens = cache_read = cache_write = 0

    u = getattr(resp, "usage", None)
    if u:
        prompt_tokens = getattr(u, "prompt_tokens", 0) or 0
        completion_tokens = getattr(u, "completion_tokens", 0) or 0
        total_tokens = getattr(u, "total_tokens", 0) or 0
        # Anthropic-style cache fields live on usage directly.
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        # OpenAI-style cached tokens live under prompt_tokens_details.
        ptd = getattr(u, "prompt_tokens_details", None)
        if ptd is not None and not cache_read:
            cache_read = (getattr(ptd, "cached_tokens", None)
                          or (ptd.get("cached_tokens") if isinstance(ptd, dict) else 0)
                          or 0)
        ctd = getattr(u, "completion_tokens_details", None)
        if ctd is not None:
            reasoning_tokens = (getattr(ctd, "reasoning_tokens", None)
                                or (ctd.get("reasoning_tokens") if isinstance(ctd, dict) else 0)
                                or 0)

    # Resolve the provider-prefixed model so cost works even when a caller omits
    # litellm_model (e.g. agent_runner) — Vertex/Bedrock return a bare
    # response.model that otherwise makes completion_cost emit null.
    resolved_litellm_model = litellm_model or _build_litellm_model(model, provider)
    cost_usd = _safe_completion_cost(resp, model, litellm_model=resolved_litellm_model)
    return UsageRecord(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=reasoning_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        cost_usd=cost_usd,
        latency_sec=latency_sec,
        ttft_sec=ttft_sec,
        model=model,
        provider=provider,
        n_calls=1,
        cost_known_calls=1 if cost_usd is not None else 0,
    )


def llm_call(
    prompt: str,
    model: str,
    provider: str = "openai",
    api_key: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    system: Optional[str] = None,
) -> str:
    """Call any LLM via litellm with automatic retry on transient errors.

    Args:
        prompt: User prompt string.
        model: Model name (e.g. "gpt-4o-mini", "claude-3-5-sonnet-20241022").
        provider: Provider name — "openai", "anthropic", "openrouter", "bedrock".
        api_key: Optional API key (falls back to env var).
        max_retries: Max retry attempts on transient errors (default 3).
        retry_delay: Initial delay in seconds; doubles each attempt (exponential backoff).
        system: Optional system prompt. When provided it is sent as a leading
            ``system`` message — used to vary the answering agent's persona.

    Returns:
        Model response as a plain string.
    """
    text, _ = llm_call_with_usage(
        prompt=prompt, model=model, provider=provider,
        api_key=api_key, max_retries=max_retries, retry_delay=retry_delay,
        system=system,
    )
    return text


def llm_call_with_usage(
    prompt: str,
    model: str,
    provider: str = "openai",
    api_key: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    system: Optional[str] = None,
    stream: bool = False,
) -> "tuple[str, UsageRecord]":
    """Like llm_call, but returns ``(text, UsageRecord)``.

    The :class:`~agent_benchmarks.metrics.usage.UsageRecord` carries tokens,
    cache read/write tokens, dollar cost (``None`` when litellm has no pricing),
    per-call latency, and — when ``stream=True`` — time-to-first-token. All
    fields default to 0 / None when the provider does not expose them.

    Args:
        system: Optional system prompt sent as a leading ``system`` message.
        stream: When True, stream the response and measure ``ttft_sec`` (time to
            the first content chunk). Default off — the non-streaming path keeps
            the well-tested retry/usage behavior; TTFT is opt-in for
            latency-sensitive sweeps.

    Returns:
        (response_text: str, usage: UsageRecord)
    """
    from litellm import completion

    api_key = _resolve_api_key(provider, api_key)
    litellm_model = _build_litellm_model(model, provider)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    last_exc: Optional[Exception] = None
    delay = retry_delay

    for attempt in range(max_retries + 1):
        try:
            if stream:
                return _stream_call(completion, litellm_model, messages, api_key,
                                    model, provider)

            t0 = time.time()
            resp = completion(
                model=litellm_model,
                messages=messages,
                api_key=api_key or None,
            )
            latency = time.time() - t0
            text = resp.choices[0].message.content
            return text, _extract_usage(resp, model, provider, latency_sec=latency,
                                        litellm_model=litellm_model)

        except Exception as exc:
            last_exc = exc
            if attempt < max_retries and _is_retryable(exc):
                logger.warning(
                    f"LLM call failed (attempt {attempt+1}/{max_retries+1}), "
                    f"retrying in {delay:.0f}s: {exc}"
                )
                time.sleep(delay)
                delay *= 2
            else:
                raise

    raise last_exc  # should never reach here


def _stream_call(completion, litellm_model, messages, api_key, model, provider):
    """Streaming variant of a single completion that also measures TTFT.

    Requests usage in the terminal chunk (``stream_options``) and stamps
    ``ttft_sec`` at the first content delta. Falls back to ``None`` usage fields
    if the provider omits the usage chunk.
    """
    t0 = time.time()
    ttft: Optional[float] = None
    parts: list = []
    final_chunk = None

    stream_resp = completion(
        model=litellm_model,
        messages=messages,
        api_key=api_key or None,
        stream=True,
        stream_options={"include_usage": True},
    )
    for chunk in stream_resp:
        final_chunk = chunk
        try:
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
        except (AttributeError, IndexError):
            piece = None
        if piece:
            if ttft is None:
                ttft = time.time() - t0
            parts.append(piece)

    latency = time.time() - t0
    text = "".join(parts)
    # The terminal chunk carries usage when include_usage is honored. Some
    # providers/proxies ignore it — warn so all-zero tokens are not mistaken
    # for a genuinely empty call.
    if final_chunk is None or not getattr(final_chunk, "usage", None):
        logger.warning(
            "Streaming response for %r returned no usage chunk; token/cost "
            "metrics will be zero/None for this call.", model
        )
    usage = _extract_usage(final_chunk, model, provider, latency_sec=latency, ttft_sec=ttft,
                           litellm_model=litellm_model)
    return text, usage


def chat_completion(
    messages: list,
    model: str,
    provider: str = "openai",
    tools: Optional[list] = None,
    tool_choice: Optional[str] = None,
    api_key: Optional[str] = None,
    max_retries: int = 3,
    retry_delay: float = 2.0,
):
    """Multi-turn completion with optional tool-calling.

    Unlike :func:`llm_call_with_usage` (single user prompt), this accepts a full
    message list and optional ``tools`` schemas, returning the raw litellm
    response so callers can inspect ``choices[0].message.tool_calls``. Used by
    the agentic treatment runner.

    Args:
        messages: OpenAI-style message dicts.
        tools: Optional list of tool schemas (OpenAI/litellm format).
        tool_choice: Optional tool-choice directive (e.g. ``"auto"``).

    Returns:
        The litellm completion response object.
    """
    from litellm import completion

    api_key = _resolve_api_key(provider, api_key)
    litellm_model = _build_litellm_model(model, provider)

    kwargs = {}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"

    last_exc: Optional[Exception] = None
    delay = retry_delay
    for attempt in range(max_retries + 1):
        try:
            return completion(
                model=litellm_model,
                messages=messages,
                api_key=api_key or None,
                **kwargs,
            )
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries and _is_retryable(exc):
                logger.warning(
                    f"chat_completion failed (attempt {attempt+1}/{max_retries+1}), "
                    f"retrying in {delay:.0f}s: {exc}"
                )
                time.sleep(delay)
                delay *= 2
            else:
                raise
    raise last_exc  # pragma: no cover


# ── Robust JSON extraction ─────────────────────────────────────────────────────

import re as _re

def extract_json_object(text: str) -> dict:
    """Extract a JSON object from LLM output, handling markdown fences and leading text."""
    text = (text or "").strip()
    if not text:
        raise ValueError("LLM returned empty response")
    # Direct parse
    try:
        return __import__("json").loads(text)
    except Exception:
        pass
    # Markdown fence
    fence = _re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        try:
            return __import__("json").loads(fence.group(1).strip())
        except Exception:
            pass
    # First { ... } block
    m = _re.search(r"\{[\s\S]*\}", text)
    if m:
        return __import__("json").loads(m.group(0))
    raise ValueError(f"No JSON object found in LLM response: {text[:200]!r}")


def extract_json_array(text: str) -> list:
    """Extract a JSON array from LLM output, handling markdown fences and leading text."""
    text = (text or "").strip()
    if not text:
        raise ValueError("LLM returned empty response")
    # Direct parse
    try:
        result = __import__("json").loads(text)
        if isinstance(result, list):
            return result
    except Exception:
        pass
    # Markdown fence
    fence = _re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        try:
            result = __import__("json").loads(fence.group(1).strip())
            if isinstance(result, list):
                return result
        except Exception:
            pass
    # First [ ... ] block
    m = _re.search(r"\[[\s\S]*\]", text)
    if m:
        result = __import__("json").loads(m.group(0))
        if isinstance(result, list):
            return result
    raise ValueError(f"No JSON array found in LLM response: {text[:200]!r}")
