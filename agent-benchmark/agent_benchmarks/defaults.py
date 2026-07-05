"""Central defaults for benchmark runs.

Keep user-facing CLI defaults in one place so docs, commands, and tests do not
quietly drift. Model names are LiteLLM/provider-facing strings.
"""

DEFAULT_ANSWER_PROVIDER = "openai"
DEFAULT_ANSWER_MODEL = "gpt-5.5"
DEFAULT_JUDGE_PROVIDER = "anthropic"
DEFAULT_JUDGE_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_GENERATOR_PROVIDER = "openai"
DEFAULT_GENERATOR_MODEL = "gpt-5.5"

# Decision (2026-03-04): one fixed semantic retrieval config.
DEFAULT_RETRIEVAL_TOP_K = 3
DEFAULT_MAX_TOKENS_PER_QUESTION = 4000
DEFAULT_CONCURRENCY = 5
DEFAULT_RESULTS_SUFFIX = "_final"
