"""Pipeline orchestrator for end-to-end documentation evaluation."""

import hashlib
import logging
import json
from typing import List, Dict, Any, Optional
from pathlib import Path

from agent_benchmarks.mcp.factory import create_doc_source_client

logger = logging.getLogger(__name__)


def compute_question_set_hash(questions: List[Dict[str, Any]]) -> str:
    """Return 12-char SHA-256 prefix over sorted question texts + ids."""
    fingerprints = sorted(
        f"{q.get('id', '')}:{q.get('question', q.get('question_text', q.get('text', '')))}"
        for q in questions
    )
    raw = "\n".join(fingerprints).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


class EvaluationPipeline:
    """
    Orchestrate full documentation evaluation pipeline.
    
    Steps:
    1. Discover personas
    2. Generate questions (from personas + optional custom)
    3. Merge and deduplicate questions with source tracking
    4. Generate context-arm and baseline answers
    5. Evaluate answers (LLM-as-judge)
    6. Generate report
    """
    
    def __init__(
        self,
        product: str,
        output_dir: Path,
        repo: Optional[str] = None,
        description: Optional[str] = None,
        custom_questions_path: Optional[Path] = None,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        judge_model: str = "gpt-4o-mini",
        judge_provider: str = "openai",
        personas_count: int = 5,
        questions_per_topic: int = 2,
        top_k: int = 5,
        rerank_threshold: float = 0.3,
        debug_retrieval: bool = False,
        doc_source: str = "context7",
        context7_id: Optional[str] = None,
        max_tokens_per_question: int = 4000,
        force_regen: bool = False,
        questions_from: Optional[Path] = None,
    ):
        """
        Initialize pipeline.

        Args:
            product: Product name (e.g., "oneDNN")
            output_dir: Base directory for outputs
            repo: GitHub repo (e.g., "oneapi-src/oneDNN").  Optional — when
                omitted, ``description`` must be provided so the LLM can
                generate personas without GitHub data.
            description: Plain-text description of the product.  Used as the
                sole signal for persona generation when ``repo`` is not given.
                Also useful to supplement GitHub data.
            custom_questions_path: Optional path to manual questions JSON
            model: LLM model for generation/answering
            provider: Provider for generation/answering
            judge_model: LLM model for evaluation
            judge_provider: Provider for evaluation
            personas_count: Target number of personas
            questions_per_topic: Questions per topic per persona
            top_k: Docs to retrieve before reranking
            rerank_threshold: Min relevance score
            debug_retrieval: Include retrieval metadata
            doc_source: Documentation source descriptor — 'context7' (default),
                'local:<path>', or 'url:<url>'
            context7_id: Explicit Context7 library ID (e.g., 'intel/mkl-dnn').
                Overrides the auto-resolved ID when doc_source is 'context7'.
        """
        if not repo and not description:
            raise ValueError(
                "Either 'repo' or 'description' must be provided. "
                "Supply 'repo' for GitHub-based persona discovery, or "
                "'description' for products without a public repository."
            )

        self.product = product
        self.repo = repo
        self.description = description
        self.output_dir = Path(output_dir)

        # Auto-discover golden questions for this product if not explicitly provided.
        # Convention: data/questions/<slug>_golden.json next to the project root (two levels
        # up from this file: agent_benchmarks/orchestrator/pipeline.py → agent_benchmarks/ → project root).
        # `product` may be a display name with spaces (e.g. "Intel Performance Skills"),
        # but golden files are named with the registry key slug
        # (intel_performance_skills_golden.json), so normalize spaces/hyphens to underscores.
        _project_root = Path(__file__).resolve().parent.parent.parent
        _questions_dir = _project_root / "data" / "questions"
        _slug = product.lower().replace(" ", "_").replace("-", "_")
        _candidates = [
            _questions_dir / f"{_slug}_golden.json",
            _questions_dir / f"{product.lower()}_golden.json",  # legacy/literal form
        ]
        _auto_golden = next((c for c in _candidates if c.exists()), _candidates[0])
        if custom_questions_path:
            _custom_path = Path(custom_questions_path)
            if not _custom_path.exists():
                raise FileNotFoundError(
                    f"--custom-questions path does not exist: {_custom_path}"
                )
            self.custom_questions_path = _custom_path
        elif _auto_golden.exists():
            self.custom_questions_path = _auto_golden
            logger.info(f"Auto-including golden questions: {_auto_golden}")
        else:
            self.custom_questions_path = None

        self.model = model
        self.provider = provider
        self.judge_model = judge_model
        self.judge_provider = judge_provider

        self.personas_count = personas_count
        self.questions_per_topic = questions_per_topic
        self.top_k = top_k
        self.rerank_threshold = rerank_threshold
        self.debug_retrieval = debug_retrieval
        self.doc_source = doc_source
        self.context7_id = context7_id
        self.max_tokens_per_question = max_tokens_per_question
        self.force_regen = force_regen

        # External questions source (skip generation, load from this path/dir)
        if questions_from is not None:
            qf = Path(questions_from)
            # Accept either a directory (auto-find <product>.json) or a file path
            if qf.is_dir():
                qf = qf / "questions" / f"{product}.json"
            if not qf.exists():
                raise FileNotFoundError(
                    f"--questions-from: questions file not found: {qf}"
                )
            self.external_questions_path: Optional[Path] = qf
            logger.info(f"Will reuse questions from: {qf}")
        else:
            self.external_questions_path = None

        # Output paths
        self.personas_path = self.output_dir / "personas" / f"{product}.json"
        self.questions_path = self.output_dir / "questions" / f"{product}.json"
        self.answers_path = self.output_dir / "answers" / f"{product}.json"
        self.eval_path = self.output_dir / "eval" / f"{product}.json"
        self.report_path = self.output_dir / "reports" / f"{product}.md"
        
        # Create output dirs
        for path in [self.personas_path, self.questions_path, self.answers_path, self.eval_path, self.report_path]:
            path.parent.mkdir(parents=True, exist_ok=True)
    
    def run(self, concurrency: int = 5) -> Dict[str, Any]:
        """
        Run full pipeline.
        
        Returns:
            Summary dict with results and paths
        """
        logger.info(f"Starting evaluation pipeline for {self.product}")
        
        results = {
            "product": self.product,
            "repo": self.repo,
            "steps": {}
        }
        
        # Step 1: Discover personas (cached if already exists)
        logger.info("Step 1/6: Discovering personas...")
        if (not self.force_regen) and self.personas_path.exists():
            personas = json.loads(self.personas_path.read_text())
            print(f"✓ Loaded {len(personas.get('personas', []))} personas (cached)")
        else:
            personas = self._discover_personas()
            print(f"✓ Discovered {len(personas.get('personas', []))} personas")
        results["steps"]["personas"] = {
            "count": len(personas.get("personas", [])),
            "path": str(self.personas_path)
        }

        # Step 2+3: Generate & merge questions (external / cached / fresh)
        if self.external_questions_path is not None:
            # Reuse question set from another run — skip generation entirely
            logger.info(f"Step 2-3/6: Loading external questions from {self.external_questions_path}...")
            raw = json.loads(self.external_questions_path.read_text())
            merged_questions = raw.get("questions", raw) if isinstance(raw, dict) else raw
            # Copy to local questions_path so downstream steps find it normally
            self.questions_path.parent.mkdir(parents=True, exist_ok=True)
            self.questions_path.write_text(json.dumps(merged_questions, indent=2))
            print(f"✓ Loaded {len(merged_questions)} questions (from --questions-from, skipping generation)")
            results["steps"]["questions_generated"] = {
                "count": len(merged_questions),
                "external_source": str(self.external_questions_path),
            }
            results["steps"]["questions_merged"] = {
                "total": len(merged_questions),
                "external_source": str(self.external_questions_path),
                "path": str(self.questions_path),
            }
        elif (not self.force_regen) and self.questions_path.exists():
            logger.info("Step 2-3/6: Loading cached questions (skipping generation)...")
            cached = json.loads(self.questions_path.read_text())
            merged_questions = cached.get("questions", cached) if isinstance(cached, dict) else cached
            print(f"✓ Loaded {len(merged_questions)} questions (cached — skipping generation)")
            results["steps"]["questions_generated"] = {"count": len(merged_questions), "cached": True}
            results["steps"]["questions_merged"] = {"total": len(merged_questions), "cached": True,
                                                     "path": str(self.questions_path)}
        else:
            logger.info("Step 2/6: Generating questions...")
            generated_questions = self._generate_questions(personas)
            results["steps"]["questions_generated"] = {
                "count": len(generated_questions),
                "path": "temp"
            }
            print(f"✓ Generated {len(generated_questions)} questions from personas")

            # Step 3: Merge with custom questions + deduplicate
            logger.info("Step 3/6: Merging and deduplicating questions...")
            merged_questions = self._merge_questions(generated_questions)
            results["steps"]["questions_merged"] = {
                "total": len(merged_questions),
                "generated": sum(1 for q in merged_questions if q.get("source_type") == "generated"),
                "manual": sum(1 for q in merged_questions if q.get("source_type") == "manual"),
                "path": str(self.questions_path)
            }
            print(f"✓ Merged to {len(merged_questions)} unique questions "
                  f"({results['steps']['questions_merged']['generated']} generated, "
                  f"{results['steps']['questions_merged']['manual']} manual)")
        
        # Compute and record question_set_hash for reproducibility
        question_set_hash = compute_question_set_hash(merged_questions)
        results["question_set_hash"] = question_set_hash
        print(f"  question_set_hash: {question_set_hash}")

        # Step 4: Generate answers
        logger.info("Step 4/6: Generating context-arm and baseline answers...")
        answers = self._generate_answers(merged_questions, concurrency=concurrency,
                                         question_set_hash=question_set_hash)
        results["steps"]["answers"] = {
            "count": len(answers),
            "path": str(self.answers_path)
        }
        print(f"✓ Generated answers for {len(answers)} questions")
        
        # Step 5: Evaluate answers
        logger.info("Step 5/6: Evaluating answers...")
        evaluations = self._evaluate_answers(answers, concurrency=concurrency,
                                              question_set_hash=question_set_hash)
        results["steps"]["evaluation"] = {
            "count": len(evaluations),
            "path": str(self.eval_path)
        }
        
        # Compute summary stats
        with_scores = [e["with_docs"]["aggregate"] for e in evaluations if e.get("with_docs")]
        without_scores = [e["without_docs"]["aggregate"] for e in evaluations if e.get("without_docs")]
        deltas = [e["delta"] for e in evaluations if e.get("delta") is not None]
        
        if with_scores and without_scores and deltas:
            results["steps"]["evaluation"]["summary"] = {
                "with_avg": round(sum(with_scores) / len(with_scores), 1),
                "without_avg": round(sum(without_scores) / len(without_scores), 1),
                "delta_avg": round(sum(deltas) / len(deltas), 1)
            }
            print(f"✓ Evaluated {len(evaluations)} answers: "
                  f"context={results['steps']['evaluation']['summary']['with_avg']}, "
                  f"baseline={results['steps']['evaluation']['summary']['without_avg']}, "
                  f"delta={results['steps']['evaluation']['summary']['delta_avg']:+.1f}")
        else:
            print(f"✓ Evaluated {len(evaluations)} answers (summary unavailable)")
        
        # Step 6: Generate report
        logger.info("Step 6/6: Generating report...")
        self._generate_report(evaluations, merged_questions)
        results["steps"]["report"] = {
            "path": str(self.report_path)
        }
        print(f"✓ Generated report: {self.report_path}")
        
        results["status"] = "success"
        return results
    
    def _discover_personas(self) -> Dict[str, Any]:
        """Discover personas — from GitHub repo or from a plain description."""
        import os
        from agent_benchmarks.personas import PersonaAnalyzer, PersonaGenerator

        generator = PersonaGenerator(model=self.model, provider=self.provider)

        if self.repo:
            # --- GitHub-based discovery ---
            github_token = os.getenv("GITHUB_TOKEN")
            analyzer = PersonaAnalyzer(github_token=github_token)
            logger.info(f"Analysing repository: {self.repo}")
            analysis = analyzer.analyze_repository(self.repo)
        else:
            # --- Description-only discovery (no GitHub repo) ---
            logger.info(
                f"No repo provided — generating personas from description for '{self.product}'"
            )
            analysis = PersonaAnalyzer.create_minimal_analysis(
                library_name=self.product,
                description=self.description or "",
            )

        personas = generator.generate_personas(
            library_name=self.product,
            analysis=analysis,
            target_count=self.personas_count
        )
        
        # Save personas
        generator.save_personas(personas, self.personas_path)
        
        return personas
    
    def _generate_questions(self, personas: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate questions from personas."""
        from agent_benchmarks.questions import RagasSeedExtractor, QuestionGenerator

        # Extract topics
        mcp_client = create_doc_source_client(self.doc_source)
        library_id = self.context7_id or mcp_client.resolve_library_id(self.product)
        
        extractor = RagasSeedExtractor(mcp_client=mcp_client, cache_dir=Path(".cache/topics"))
        topics = extractor.extract_topics(
            library_id=library_id,
            library_name=self.product,
            max_topics=20
        )
        
        # Generate questions — hybrid mode if doc_url available
        generator = QuestionGenerator(model=self.model, provider=self.provider)
        doc_url = self.doc_source if self.doc_source.startswith("url:") else None
        if doc_url:
            doc_url = doc_url[4:]  # strip "url:" prefix

        if doc_url:
            # Cap at a sane default; questions_per_topic * topics * personas can be huge
            target_total = min(
                self.questions_per_topic * len(topics) * len(personas["personas"]),
                100,  # hard cap — adjust via CLI if needed
            )
            questions = generator.generate_hybrid(
                library_name=self.product,
                personas=personas["personas"],
                topics=topics,
                doc_url=doc_url,
                total_questions=target_total,
                chunk_ratio=0.4,
                questions_per_topic=self.questions_per_topic,
            )
        else:
            questions = generator.generate_questions(
                library_name=self.product,
                personas=personas["personas"],
                topics=topics,
                questions_per_topic=self.questions_per_topic,
            )

        # Add source tracking
        for q in questions:
            q["source_type"] = "generated"
        
        return questions
    
    def _merge_questions(self, generated_questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge generated + custom questions, deduplicate, save."""
        from agent_benchmarks.questions import QuestionValidator
        
        all_questions = generated_questions.copy()
        
        # Load custom questions if provided
        if self.custom_questions_path and self.custom_questions_path.exists():
            custom_data = json.loads(self.custom_questions_path.read_text())
            
            # Handle both dict format {"questions": [...]} and direct list format
            if isinstance(custom_data, dict):
                custom_questions = custom_data.get("questions")
                if custom_questions is None:
                    raise ValueError(
                        f"Custom questions file must have 'questions' key or be a list. "
                        f"Got dict with keys: {list(custom_data.keys())}"
                    )
            elif isinstance(custom_data, list):
                custom_questions = custom_data
            else:
                raise ValueError(
                    f"Custom questions must be a dict with 'questions' key or a list. "
                    f"Got: {type(custom_data).__name__}"
                )
            
            # Validate it's a list
            if not isinstance(custom_questions, list):
                raise ValueError(
                    f"Expected list of questions, got {type(custom_questions).__name__}"
                )
            
            # Add source tracking
            for q in custom_questions:
                q["source_type"] = "manual"
                if "persona_id" not in q:
                    q["persona_id"] = "manual"
            
            all_questions.extend(custom_questions)
            logger.info(f"Loaded {len(custom_questions)} custom questions")
        
        # Deduplicate
        validator = QuestionValidator(similarity_threshold=0.85)
        unique_questions, _ = validator._deduplicate(all_questions)
        
        # Save merged questions
        output = {
            "product": self.product,
            "total_questions": len(unique_questions),
            "sources": {
                "generated": sum(1 for q in unique_questions if q.get("source_type") == "generated"),
                "manual": sum(1 for q in unique_questions if q.get("source_type") == "manual")
            },
            "questions": unique_questions
        }
        
        self.questions_path.write_text(json.dumps(output, indent=2))
        
        return unique_questions
    
    def _generate_answers(self, questions: List[Dict[str, Any]], concurrency: int = 5,
                          question_set_hash: Optional[str] = None) -> List[Dict[str, Any]]:
        """Generate context-arm and baseline answers."""
        from agent_benchmarks.eval import Answerer

        # Setup documentation source client
        mcp_client = create_doc_source_client(self.doc_source)
        library_id = self.context7_id or mcp_client.resolve_library_id(self.product)
        
        # Generate answers
        answerer = Answerer(
            mcp_client=mcp_client,
            model=self.model,
            provider=self.provider,
            top_k=self.top_k,
            rerank_threshold=self.rerank_threshold,
            debug_retrieval=self.debug_retrieval
        )
        
        answers = answerer.generate_answers(
            library_name=self.product,
            library_id=library_id,
            questions=questions,
            max_tokens_per_question=self.max_tokens_per_question,
            concurrency=concurrency,
        )
        
        # Save answers
        answerer.save_answers(answers, self.answers_path, question_set_hash=question_set_hash)
        
        return answers
    
    def _evaluate_answers(self, answers: List[Dict[str, Any]], concurrency: int = 5,
                          question_set_hash: Optional[str] = None) -> List[Dict[str, Any]]:
        """Evaluate answers using LLM-as-judge."""
        from agent_benchmarks.eval import Judge
        
        # Use in-memory answers from the previous step (avoid stale disk read)
        if isinstance(answers, dict):
            answers_list = answers.get("answers", answers)
        elif answers:
            answers_list = answers
        else:
            # Fallback: read from disk if not provided
            answers_data = json.loads(self.answers_path.read_text())
            answers_list = answers_data.get("answers", answers_data)
        
        # Evaluate
        judge = Judge(
            model=self.judge_model,
            provider=self.judge_provider,
            run_metadata={
                "question_model": self.model,
                "question_provider": self.provider,
                "answer_model": self.model,
                "answer_provider": self.provider,
                "judge_model": self.judge_model,
                "judge_provider": self.judge_provider,
                "question_set_hash": question_set_hash,
                "evaluator_independence_warning": (
                    str(self.model).strip().lower() == str(self.judge_model).strip().lower()
                    and str(self.provider).strip().lower() == str(self.judge_provider).strip().lower()
                ),
            },
        )
        
        evaluations = judge.evaluate_answers(self.product, answers_list, concurrency=concurrency)
        
        # Save evaluations
        judge.save_evaluations(evaluations, self.eval_path)
        
        return evaluations
    
    def _generate_report(
        self,
        evaluations: List[Dict[str, Any]],
        questions: List[Dict[str, Any]]
    ) -> str:
        """Generate comprehensive report."""
        from agent_benchmarks.report import ReportGenerator
        
        # Load data
        eval_data = json.loads(self.eval_path.read_text())
        questions_data = {
            "product": self.product,
            "questions": questions
        }
        
        # Generate report
        generator = ReportGenerator()
        report = generator.generate_report(
            eval_data=eval_data,
            questions_data=questions_data,
            output_format="markdown"
        )
        
        # Save report
        self.report_path.write_text(report)
        
        return report
