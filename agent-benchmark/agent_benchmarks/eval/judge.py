"""Judge answers using LLM-as-judge approach."""

import logging
import json
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

from agent_benchmarks.llm import ChatOpenAI, ChatAnthropic, LANGCHAIN_AVAILABLE
from agent_benchmarks.eval.diagnoser import diagnose


JUDGE_PROMPT = """You are evaluating the quality of an answer to a technical question.

**Question:** __QUESTION__

**Answer:** __ANSWER__

**Context (retrieved from docs, if available):**
__CONTEXT__

**Evaluation criteria:**

1. **Correctness (0-100):** Is the answer factually accurate?
2. **Completeness (0-100):** Does it fully address the question?
3. **Specificity (0-100):** Is it specific to __LIBRARY_NAME__ (not generic)?
4. **Code Quality (0-100):** If code is included, is it correct and runnable?
5. **Actionability (0-100):** Can the user apply this immediately?

**Instructions:**
- Score each dimension 0-100
- Aggregate score is the average of all 5 dimensions
- Provide brief reasoning for each score

**Output format (JSON only, no other text):**
{
  "correctness": 85,
  "completeness": 90,
  "specificity": 80,
  "code_quality": 85,
  "actionability": 90,
  "aggregate": 86,
  "reasoning": {
    "correctness": "Answer is accurate according to docs",
    "completeness": "Covers main aspects",
    "specificity": "Uses __LIBRARY_NAME__-specific APIs",
    "code_quality": "Code compiles and follows best practices",
    "actionability": "Clear steps provided"
  }
}"""

# Extended prompt used when a ground-truth chunk is available.
# Adds a factual_grounding dimension that checks alignment with doc text.
JUDGE_PROMPT_GROUNDED = """You are evaluating the quality of an answer to a technical question.
The question was generated from the documentation excerpt below — use it as ground truth.

**Question:** __QUESTION__

**Answer:** __ANSWER__

**Ground-truth documentation excerpt (source of truth):**
```
__GROUND_TRUTH__
```

**Context (retrieved from docs, if available):**
__CONTEXT__

**Evaluation criteria:**

1. **Correctness (0-100):** Is the answer factually accurate compared to the ground-truth excerpt?
2. **Completeness (0-100):** Does it fully address the question using information from the excerpt?
3. **Specificity (0-100):** Is it specific to __LIBRARY_NAME__ (not generic)?
4. **Code Quality (0-100):** If code is included, is it correct and consistent with the excerpt?
5. **Actionability (0-100):** Can the user apply this immediately?
6. **Factual Grounding (0-100):** Does the answer stay faithful to the ground-truth excerpt?
   - 100: All facts match the excerpt exactly
   - 80: Minor omissions, no contradictions
   - 60: Some facts correct, some missing or vague
   - 40: Answer contradicts or ignores key information from excerpt
   - 0: Answer is completely inconsistent with the excerpt

**Instructions:**
- Score each dimension 0-100
- Aggregate = weighted mean: (correctness×2 + completeness + specificity + code_quality + actionability + factual_grounding×2) / 8
- Python computes the aggregate — do NOT compute it yourself, set aggregate=0
- Provide brief reasoning per dimension

**Output format (JSON only, no other text):**
{
  "correctness": 85,
  "completeness": 90,
  "specificity": 80,
  "code_quality": 85,
  "actionability": 90,
  "factual_grounding": 88,
  "aggregate": 0,
  "reasoning": {
    "correctness": "...",
    "completeness": "...",
    "specificity": "...",
    "code_quality": "...",
    "actionability": "...",
    "factual_grounding": "..."
  }
}"""


class Judge:
    """
    Evaluate answer quality using LLM-as-judge.
    
    Scores answers on 5 dimensions (0-100):
    - Correctness
    - Completeness
    - Specificity
    - Code Quality
    - Actionability
    """
    
    def __init__(
        self,
        model: str = "claude-sonnet-4",
        provider: str = "anthropic",
        api_key: Optional[str] = None,
        run_metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            model: LLM model for judging (should differ from answerer model)
            provider: "openai" or "anthropic"
            api_key: Optional API key
        """
        if not LANGCHAIN_AVAILABLE:
            raise ImportError(
                "LLM dependencies not available. "
                "Install: pip install litellm"
            )

        self.model = model
        self.provider = provider
        self.api_key = api_key
        self.run_metadata = dict(run_metadata) if run_metadata else {}
        # Accumulate judge-side token/cost telemetry across all judge calls
        # (Phase-C.0 covered answering; the judge path was untracked).
        self._usage_lock = threading.Lock()
        self._usage_totals = {
            "calls": 0, "cost_known_calls": 0, "cost_usd": 0.0,
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        }

        if provider == "openai":
            self.llm = ChatOpenAI(model=model, api_key=api_key)
        elif provider == "anthropic":
            self.llm = ChatAnthropic(model=model, api_key=api_key)
        elif provider in ("google", "gemini", "google-vertex", "openrouter",
                          "amazon-bedrock", "vertex_ai"):
            from agent_benchmarks.utils import get_llm
            import os
            fallback_key = os.environ.get("OPENROUTER_API_KEY") if provider == "openrouter" else None
            self.llm = get_llm(provider, model, api_key or fallback_key)
        else:
            raise ValueError(
                f"Unsupported provider: '{provider}'. "
                "Use 'openai', 'anthropic', 'google', 'openrouter', or 'amazon-bedrock'."
            )
        
        logger.info(f"Judge initialized: {provider}/{model}")
    
    def evaluate_answers(
        self,
        library_name: str,
        answers: List[Dict[str, Any]],
        output_path: Optional[Path] = None,
        concurrency: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Evaluate all context-arm and baseline answers.

        Args:
            library_name: Library name for context
            answers: List of answer dicts from Answerer
            output_path: If set, write incrementally after each evaluation
            concurrency: Number of parallel judge calls (default: 1 = sequential)

        Returns:
            List of evaluation dicts ordered by input order.
        """
        n = len(answers)
        results: Dict[int, Dict] = {}
        lock = threading.Lock()
        completed = [0]

        def _process(idx: int, answer: Dict) -> None:
            q_id = answer["question_id"]
            t0 = time.time()
            try:
                eval_result = self._evaluate_answer_pair(library_name, answer)
                elapsed = time.time() - t0
                delta = eval_result.get("delta")
                delta_str = f"delta={delta:+}" if delta is not None else "delta=n/a"
                with lock:
                    results[idx] = eval_result
                    completed[0] += 1
                    print(f"[{completed[0]}/{n}] {q_id} ✓ {delta_str} ({elapsed:.1f}s)", flush=True)
                    if output_path is not None:
                        ordered = [results[i] for i in sorted(results)]
                        self._save_incremental(ordered, output_path)
            except Exception as e:
                elapsed = time.time() - t0
                logger.exception(f"Evaluation failed for {q_id}")
                with lock:
                    results[idx] = {
                        "question_id": answer["question_id"],
                        "question_text": answer["question_text"],
                        "category": answer.get("category"),
                        "difficulty": answer.get("difficulty"),
                        "persona": answer.get("persona"),
                        "error": str(e),
                        "with_docs": None,
                        "without_docs": None,
                        "delta": None
                    }
                    completed[0] += 1
                    print(f"[{completed[0]}/{n}] {q_id} ✗ ({elapsed:.1f}s): {e}", flush=True)
                    if output_path is not None:
                        ordered = [results[i] for i in sorted(results)]
                        self._save_incremental(ordered, output_path)

        print(f"Evaluating {n} answers with judge: {self.provider}/{self.model} (concurrency={concurrency})", flush=True)

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_process, i, a): i for i, a in enumerate(answers)}
            for f in as_completed(futures):
                f.result()  # wait for completion

        evaluations = [results[i] for i in range(n)]
        valid = [e for e in evaluations if e.get("delta") is not None]
        if valid:
            avg_with = sum((e.get("with_docs") or {}).get("aggregate", 0) for e in valid) / len(valid)
            avg_without = sum((e.get("without_docs") or {}).get("aggregate", 0) for e in valid) / len(valid)
            avg_delta = sum(e["delta"] for e in valid) / len(valid)
            print("\n✓ Evaluation complete:", flush=True)
            print(f"  Context avg:      {avg_with:.1f}", flush=True)
            print(f"  Baseline avg:     {avg_without:.1f}", flush=True)
            print(f"  Average delta:    {avg_delta:.1f}", flush=True)
        return evaluations
    
    def _evaluate_answer_pair(
        self,
        library_name: str,
        answer: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate a single context-arm/baseline answer pair."""
        question_text = answer["question_text"]
        ground_truth = answer.get("ground_truth_chunk")  # present for chunk-grounded questions

        # Evaluate context arm
        with_docs_eval = None
        if answer.get("with_docs") and answer["with_docs"].get("answer"):
            context = self._format_context(answer["with_docs"].get("retrieved_docs", []))
            with_docs_eval = self._judge_answer(
                library_name=library_name,
                question=question_text,
                answer=answer["with_docs"]["answer"],
                context=context,
                ground_truth=ground_truth,
            )

        # Evaluate baseline
        without_docs_eval = None
        if answer.get("without_docs") and answer["without_docs"].get("answer"):
            without_docs_eval = self._judge_answer(
                library_name=library_name,
                question=question_text,
                answer=answer["without_docs"]["answer"],
                context="(No documentation provided)",
                ground_truth=ground_truth,
            )
        
        # Calculate delta
        delta = None
        if with_docs_eval and without_docs_eval:
            delta = with_docs_eval["aggregate"] - without_docs_eval["aggregate"]

        result = {
            "question_id": answer["question_id"],
            "question_text": question_text,
            "category": answer.get("category"),
            "difficulty": answer.get("difficulty"),
            "persona": answer.get("persona"),
            "with_docs": with_docs_eval,
            "without_docs": without_docs_eval,
            "delta": delta,
        }

        # Classify retrieval outcome (why docs helped or didn't)
        result["diagnosis"] = diagnose(answer, result)
        return result
    
    # Dimensions for standard (no ground truth) evaluation
    _STANDARD_DIMS = {"correctness", "completeness", "specificity", "code_quality", "actionability", "aggregate"}
    # Dimensions for grounded evaluation (adds factual_grounding)
    _GROUNDED_DIMS = _STANDARD_DIMS | {"factual_grounding"}

    def _judge_answer(
        self,
        library_name: str,
        question: str,
        answer: str,
        context: str,
        ground_truth: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Judge a single answer, optionally using a ground-truth doc chunk."""
        import textwrap
        from agent_benchmarks.llm import extract_json_object

        grounded = bool(ground_truth)

        if grounded:
            prompt = (
                JUDGE_PROMPT_GROUNDED
                .replace("__QUESTION__", question)
                .replace("__ANSWER__", answer)
                .replace("__CONTEXT__", context)
                .replace("__LIBRARY_NAME__", library_name)
                .replace("__GROUND_TRUTH__", textwrap.shorten(ground_truth, width=1500, placeholder="…"))
            )
        else:
            prompt = (
                JUDGE_PROMPT
                .replace("__QUESTION__", question)
                .replace("__ANSWER__", answer)
                .replace("__CONTEXT__", context)
                .replace("__LIBRARY_NAME__", library_name)
            )

        response = self.llm.invoke(prompt)
        raw = response.content if hasattr(response, "content") else str(response)
        self._accumulate_usage(getattr(response, "usage", None))

        scores = extract_json_object(raw)

        # Validate required fields
        required = self._GROUNDED_DIMS if grounded else self._STANDARD_DIMS
        missing = required - scores.keys()
        if missing:
            raise ValueError(f"Missing keys in judge response: {missing}")

        # Python computes aggregate for grounded eval
        # (LLM sets aggregate=0 per instructions)
        if grounded:
            c = float(scores.get("correctness", 0))
            comp = float(scores.get("completeness", 0))
            sp = float(scores.get("specificity", 0))
            cq = float(scores.get("code_quality", 0))
            ac = float(scores.get("actionability", 0))
            fg = float(scores.get("factual_grounding", 0))
            # Weighted: correctness×2, factual_grounding×2, others×1 → /8
            scores["aggregate"] = round((c * 2 + comp + sp + cq + ac + fg * 2) / 8, 1)
            scores["grounded"] = True
        
        return scores
    
    def score_answer(
        self,
        library_name: str,
        question: str,
        answer: str,
        context: str = "(No documentation retrieved)",
        ground_truth: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Public single-answer scorer — reused by the treatment-arm runner."""
        return self._judge_answer(
            library_name=library_name,
            question=question,
            answer=answer,
            context=context,
            ground_truth=ground_truth,
        )

    @staticmethod
    def _format_context(docs: List[Dict[str, Any]]) -> str:
        """Format retrieved docs as context string."""
        if not docs:
            return "(No documentation retrieved)"
        
        formatted = []
        for i, doc in enumerate(docs):
            snippet = doc.get("snippet", doc.get("content", ""))
            formatted.append(f"Doc {i+1}: {snippet}")
        
        return "\n".join(formatted)
    
    def _accumulate_usage(self, usage) -> None:
        """Fold one judge call's UsageRecord into the running totals (thread-safe).

        Defensive: a real UsageRecord has int token fields, but test doubles may
        carry non-numeric attributes — coerce and skip what does not convert so
        telemetry capture never breaks a judging run.
        """
        from agent_benchmarks.metrics.usage import UsageRecord
        if not isinstance(usage, UsageRecord):
            return

        def _int(v):
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        with self._usage_lock:
            t = self._usage_totals
            t["calls"] += 1
            t["prompt_tokens"] += _int(usage.prompt_tokens)
            t["completion_tokens"] += _int(usage.completion_tokens)
            t["total_tokens"] += _int(usage.total_tokens)
            cost = usage.cost_usd
            if isinstance(cost, (int, float)):
                t["cost_usd"] += float(cost)
                t["cost_known_calls"] += 1

    def _build_evaluation_output(self, evaluations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build the serialisable output structure for a set of evaluations."""
        output = {
            "schema_version": "eval.v1",
            "evaluated_at": self._get_timestamp(),
            "judge_model": self.model,
            "judge_provider": self.provider,
            "total_evaluations": len(evaluations),
            "evaluations": evaluations,
        }
        with self._usage_lock:
            totals = dict(self._usage_totals)
        # cost_usd is null (not 0.0) when no judge call had known pricing, so a
        # missing price reads distinct from a genuinely free judge.
        totals["cost_usd"] = (
            round(totals["cost_usd"], 6) if totals["cost_known_calls"] else None
        )
        output["judge_metrics"] = totals
        if self.run_metadata:
            output["run_metadata"] = self.run_metadata
        return output

    def _save_incremental(self, evaluations: List[Dict[str, Any]], output_path: Path) -> None:
        """Write current evaluations to disk atomically (called after each question)."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(self._build_evaluation_output(evaluations), f, indent=2)
        os.replace(tmp_path, output_path)

    def save_evaluations(
        self,
        evaluations: List[Dict[str, Any]],
        output_path: Path
    ):
        """Save evaluations to JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self._build_evaluation_output(evaluations), f, indent=2)
        logger.info(f"✓ Saved evaluations for {len(evaluations)} answers to {output_path}")
    
    @staticmethod
    def load_evaluations(input_path: Path) -> Dict[str, Any]:
        """Load evaluations from JSON file."""
        with open(input_path, 'r') as f:
            return json.load(f)
    
    @staticmethod
    def _get_timestamp() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
