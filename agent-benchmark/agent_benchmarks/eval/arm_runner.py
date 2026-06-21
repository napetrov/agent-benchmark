"""Run an N-arm treatment comparison: generate (and optionally judge) answers.

Generalizes the binary ``with_docs``/``without_docs`` answerer to an arbitrary
set of :class:`~agent_benchmarks.treatments.base.Treatment` arms — documentation
injection, MCP-served docs, agent persona prompts, and skills — scored by the
same LLM-as-judge used elsewhere.
"""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_benchmarks.llm import llm_call_with_usage
from agent_benchmarks.eval.cells import Cell
from agent_benchmarks.metrics.usage import to_record
from agent_benchmarks.treatments.base import Treatment

logger = logging.getLogger(__name__)

ANSWER_PROMPT_WITH_CONTEXT = """You are answering a user question.

**Question:** {question}

**Relevant context:**
{context}

**Task:**
Answer the question using the provided context above where relevant. Be specific, accurate, and actionable. Include code examples if relevant.

**Answer:**"""

ANSWER_PROMPT_PLAIN = """Answer the following user question. Be specific and include code examples if relevant.

**Question:** {question}

**Answer:**"""

MAX_CONTEXT_CHARS = 15_000


class ArmRunner:
    """Generate answers for each treatment arm and (optionally) judge them."""

    def __init__(
        self,
        treatments: List[Treatment],
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        api_key: Optional[str] = None,
        max_iterations: int = 6,
        harness: str = "arms-runner",
        plugin_set: Optional[Dict[str, Any]] = None,
    ):
        if not treatments:
            raise ValueError("ArmRunner requires at least one treatment arm")
        self.treatments = treatments
        self.model = model
        self.provider = provider
        self.api_key = api_key
        self.max_iterations = max_iterations
        self.harness = harness
        self.plugin_set = plugin_set or {
            "plugin_set": "none",
            "plugin_set_id": "sha256:e3b0c44298fc1c149afbf4c8996fb924",
            "plugins": [],
        }

    @property
    def arm_names(self) -> List[str]:
        return [t.name for t in self.treatments]

    def run(
        self,
        library_name: str,
        questions: List[Dict[str, Any]],
        library_id: Optional[str] = None,
        concurrency: int = 5,
    ) -> List[Dict[str, Any]]:
        """Answer every question under every arm. Returns one record per question."""
        n = len(questions)
        results: Dict[int, Dict[str, Any]] = {}
        lock = threading.Lock()
        done = [0]

        def _process(idx: int, q: Dict[str, Any]) -> None:
            rec = self._answer_question(library_name, library_id, q)
            with lock:
                results[idx] = rec
                done[0] += 1
                print(f"[{done[0]}/{n}] {rec['question_id']} ✓", flush=True)

        print(f"Running {len(self.treatments)} arms over {n} questions "
              f"(arms: {', '.join(self.arm_names)})", flush=True)
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(_process, i, q) for i, q in enumerate(questions)]
            for f in as_completed(futures):
                f.result()

        return [results[i] for i in range(n)]

    def _answer_question(
        self, library_name: str, library_id: Optional[str], q: Dict[str, Any]
    ) -> Dict[str, Any]:
        question_text = q.get("question") or q.get("text") or q.get("question_text", "")
        qid = q.get("id") or q.get("question_id") or "unknown_q"

        arms: Dict[str, Any] = {}
        for treatment in self.treatments:
            arms[treatment.name] = self._answer_one_arm(
                treatment, question_text, library_name, library_id
            )

        rec = {
            "question_id": qid,
            "question_text": question_text,
            "library_name": library_name,
            "category": q.get("category"),
            "difficulty": q.get("difficulty"),
            "persona": q.get("persona"),
            "arms": arms,
        }
        if q.get("ground_truth_chunk"):
            rec["ground_truth_chunk"] = q["ground_truth_chunk"]
        return rec

    def _answer_one_arm(
        self,
        treatment: Treatment,
        question_text: str,
        library_name: str,
        library_id: Optional[str],
    ) -> Dict[str, Any]:
        t0 = time.time()
        try:
            cfg = treatment.prepare(question_text, library_name, library_id)
        except Exception as exc:
            logger.exception("Arm %s prepare() failed", treatment.name)
            return {"error": f"prepare_failed: {exc}", "answer": None}

        if cfg.is_agentic:
            return self._answer_agentic_arm(cfg, question_text, t0)

        if cfg.has_context:
            context = "\n\n---\n\n".join(c["content"] for c in cfg.injected_context)
            prompt = ANSWER_PROMPT_WITH_CONTEXT.format(
                question=question_text, context=context[:MAX_CONTEXT_CHARS]
            )
        else:
            prompt = ANSWER_PROMPT_PLAIN.format(question=question_text)

        try:
            answer_text, usage = llm_call_with_usage(
                prompt=prompt,
                model=self.model,
                provider=self.provider,
                api_key=self.api_key,
                system=cfg.system_prompt,
            )
        except Exception as exc:
            logger.exception("Arm %s answer generation failed", treatment.name)
            return {"error": f"generation_failed: {exc}", "answer": None,
                    "metadata": cfg.metadata}

        rec = to_record(usage, self.model, self.provider)
        return {
            "answer": answer_text,
            "model": self.model,
            "harness": self.harness,
            "plugin_set": self.plugin_set["plugin_set"],
            "plugin_set_id": self.plugin_set["plugin_set_id"],
            "used_system_prompt": bool(cfg.system_prompt),
            "context_chunks": [
                {
                    "source": c.get("source", "unknown"),
                    "snippet": (c["content"][:200] + "…") if len(c["content"]) > 200 else c["content"],
                    "relevance_score": c.get("relevance_score"),
                }
                for c in cfg.injected_context
            ],
            "token_usage": rec.as_token_usage_dict(),
            "metrics": rec.as_metrics_dict(answer_chars=len(answer_text or "")),
            "metadata": cfg.metadata,
            "elapsed_sec": round(time.time() - t0, 2),
        }

    def _answer_agentic_arm(
        self, cfg, question_text: str, t0: float
    ) -> Dict[str, Any]:
        """Run an arm whose treatment offers tools via the agent loop."""
        from agent_benchmarks.eval.agent_runner import run_agent_loop

        try:
            result = run_agent_loop(
                question=question_text,
                tools=cfg.tools,
                model=self.model,
                provider=self.provider,
                system_prompt=cfg.system_prompt,
                api_key=self.api_key,
                max_iterations=self.max_iterations,
            )
        except Exception as exc:
            logger.exception("Agentic arm failed")
            return {"error": f"agent_failed: {exc}", "answer": None,
                    "metadata": cfg.metadata}

        rec = to_record(result.get("usage") or result["token_usage"], self.model, self.provider)
        metrics = rec.as_metrics_dict(answer_chars=len(result["answer"] or ""))
        per_turn = result.get("per_turn")
        if per_turn is not None:
            metrics["per_turn"] = per_turn
        return {
            "answer": result["answer"],
            "model": self.model,
            "harness": self.harness,
            "plugin_set": self.plugin_set["plugin_set"],
            "plugin_set_id": self.plugin_set["plugin_set_id"],
            "agentic": True,
            "used_system_prompt": bool(cfg.system_prompt),
            "context_chunks": [],
            "transcript": result["transcript"],
            "tool_call_count": result["tool_call_count"],
            "iterations": result["iterations"],
            "stopped_reason": result["stopped_reason"],
            "token_usage": rec.as_token_usage_dict(),
            "metrics": metrics,
            "metadata": cfg.metadata,
            "elapsed_sec": round(time.time() - t0, 2),
        }

    # ── Judging ─────────────────────────────────────────────────────────
    def judge(
        self,
        judge,
        library_name: str,
        records: List[Dict[str, Any]],
        baseline_arm: str = "baseline",
        concurrency: int = 5,
    ) -> List[Dict[str, Any]]:
        """Score each arm's answer with the given Judge; add per-arm deltas.

        Deltas are computed against *baseline_arm* when that arm is present.
        """
        def _score(rec: Dict[str, Any]) -> Dict[str, Any]:
            scores: Dict[str, Any] = {}
            gt = rec.get("ground_truth_chunk")
            for arm_name, arm in rec.get("arms", {}).items():
                if not arm or not arm.get("answer"):
                    scores[arm_name] = None
                    continue
                context = "\n".join(
                    c.get("snippet", "") for c in arm.get("context_chunks", [])
                ) or "(No documentation retrieved)"
                try:
                    scores[arm_name] = judge.score_answer(
                        library_name=library_name,
                        question=rec["question_text"],
                        answer=arm["answer"],
                        context=context,
                        ground_truth=gt,
                    )
                except Exception as exc:
                    logger.exception("Judging arm %s failed", arm_name)
                    scores[arm_name] = {"error": str(exc)}

            deltas = {}
            base = scores.get(baseline_arm)
            base_agg = base.get("aggregate") if isinstance(base, dict) else None
            if base_agg is not None:
                for arm_name, s in scores.items():
                    if arm_name != baseline_arm and isinstance(s, dict) and "aggregate" in s:
                        deltas[arm_name] = round(s["aggregate"] - base_agg, 1)

            return {
                "question_id": rec["question_id"],
                "question_text": rec["question_text"],
                "category": rec.get("category"),
                "difficulty": rec.get("difficulty"),
                "scores": scores,
                "deltas_vs_baseline": deltas,
            }

        n = len(records)
        out: Dict[int, Dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(_score, r): i for i, r in enumerate(records)}
            for f in as_completed(futures):
                idx = futures[f]
                out[idx] = f.result()
        return [out[i] for i in range(n)]

    def build_output(
        self,
        library_name: str,
        records: List[Dict[str, Any]],
        evaluations: Optional[List[Dict[str, Any]]] = None,
        baseline_arm: str = "baseline",
    ) -> Dict[str, Any]:
        """Assemble the serialisable arms-comparison artifact."""
        out: Dict[str, Any] = {
            "schema_version": "arms.v1",
            "generated_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
            "library_name": library_name,
            "model": self.model,
            "provider": self.provider,
            "harness": self.harness,
            "plugin_set": self.plugin_set["plugin_set"],
            "plugin_set_id": self.plugin_set["plugin_set_id"],
            "plugins": self.plugin_set["plugins"],
            "cell": Cell(self.model, self.harness, self.plugin_set["plugin_set"]).key,
            "arms": self.arm_names,
            "baseline_arm": baseline_arm,
            "total_questions": len(records),
            "answers": records,
            "cost_summary": self._cost_summary(records),
        }
        if evaluations is not None:
            out["evaluations"] = evaluations
            out["summary"] = self._summarize(evaluations, baseline_arm)
        return out

    def _cost_summary(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Per-arm rollup of cost, tokens, latency, TTFT, and cache-hit ratio.

        Aggregates the per-row ``metrics{}`` blocks. ``cost_usd`` is summed only
        over priced rows (``None`` rows are skipped); the cache-hit ratio guards
        against a zero prompt-token denominator. The exact ratio is provider-
        dependent (see ADR O2) — here it is read cache tokens / prompt tokens.
        """
        per_arm: Dict[str, Dict[str, Any]] = {}
        for rec in records:
            for arm_name, arm in rec.get("arms", {}).items():
                if not isinstance(arm, dict):
                    continue
                m = arm.get("metrics")
                if not isinstance(m, dict):
                    continue
                acc = per_arm.setdefault(arm_name, {
                    "n": 0, "total_llm_calls": 0,
                    "cost_usd": 0.0, "cost_known_n": 0,
                    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                    "cache_read_tokens": 0, "latency_sec": 0.0,
                    "ttft_sec_sum": 0.0, "ttft_n": 0,
                })
                acc["n"] += 1
                n_calls = m.get("n_calls", 1)
                acc["total_llm_calls"] += n_calls
                if m.get("cost_usd") is not None:
                    acc["cost_usd"] += m["cost_usd"]
                    acc["cost_known_n"] += m.get("cost_known_calls", n_calls) or 0
                for k in ("prompt_tokens", "completion_tokens", "total_tokens",
                          "cache_read_tokens"):
                    acc[k] += m.get(k, 0) or 0
                acc["latency_sec"] += m.get("latency_sec", 0.0) or 0.0
                if m.get("ttft_sec") is not None:
                    acc["ttft_sec_sum"] += m["ttft_sec"]
                    acc["ttft_n"] += 1

        out: Dict[str, Any] = {}
        for arm_name, acc in per_arm.items():
            n = acc["n"] or 1
            prompt = acc["prompt_tokens"]
            out[arm_name] = {
                "n": acc["n"],
                "total_cost_usd": (round(acc["cost_usd"], 6)
                                   if acc["cost_known_n"] else None),
                # How many rows the cost total covers — when < n, the dollar
                # figure is a partial sum (some LLM calls had no litellm pricing).
                "cost_known_n": acc["cost_known_n"],
                "total_llm_calls": acc["total_llm_calls"],
                "prompt_tokens": acc["prompt_tokens"],
                "completion_tokens": acc["completion_tokens"],
                "total_tokens": acc["total_tokens"],
                "mean_latency_sec": round(acc["latency_sec"] / n, 4),
                "mean_ttft_sec": (round(acc["ttft_sec_sum"] / acc["ttft_n"], 4)
                                  if acc["ttft_n"] else None),
                "cache_hit_ratio": (round(acc["cache_read_tokens"] / prompt, 4)
                                    if prompt else None),
            }
        return out

    def _summarize(
        self, evaluations: List[Dict[str, Any]], baseline_arm: str
    ) -> Dict[str, Any]:
        per_arm: Dict[str, List[float]] = {name: [] for name in self.arm_names}
        for ev in evaluations:
            for arm_name, s in ev.get("scores", {}).items():
                if isinstance(s, dict) and isinstance(s.get("aggregate"), (int, float)):
                    per_arm.setdefault(arm_name, []).append(float(s["aggregate"]))

        summary: Dict[str, Any] = {"per_arm": {}}
        base_avg = None
        for arm_name, vals in per_arm.items():
            avg = round(sum(vals) / len(vals), 1) if vals else None
            summary["per_arm"][arm_name] = {"avg_aggregate": avg, "n": len(vals)}
            if arm_name == baseline_arm:
                base_avg = avg
        if base_avg is not None:
            for arm_name, stats in summary["per_arm"].items():
                avg = stats["avg_aggregate"]
                stats["delta_vs_baseline"] = (
                    round(avg - base_avg, 1) if avg is not None and arm_name != baseline_arm else None
                )
        return summary

    @staticmethod
    def save(output: Dict[str, Any], path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, indent=2), encoding="utf-8")
        logger.info("Saved arms comparison to %s", path)
