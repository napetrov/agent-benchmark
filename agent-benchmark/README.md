# agent-benchmark

> **Part of a larger project.** This is the *measurement engine* half of the
> [Software Packaging for Agents](../README.md) umbrella repo. It evaluates
> whether a given skill / MCP doc source / agent profile actually improves agent
> answers — the evidence (scorecard) that gates whether an artifact is worth
> packaging and shipping. The packaging & discovery half lives in
> [`../software-packaging-for-agents/`](../software-packaging-for-agents/).

`agent-benchmark` is a toolkit for measuring whether documentation and other agent-facing context improve model performance. It started as a technical documentation benchmark and now supports a broader evaluation pattern: compare a model or coding agent with and without a controlled context layer.

Current context layers include product documentation, local Markdown/URL sources, Context7-backed docs, curated golden question sets, skills, agent profiles, prompt packs, MCP/doc-source arms, and executable task environments.

It supports three complementary workflows:

1. **Static documentation quality checks** over Markdown/code examples: coverage, freshness, readability, example execution, gates, and regression detection.
2. **LLM-assisted context evaluation**: persona and question generation, answer generation with/without context, LLM-as-judge scoring, multi-judge panels, RAGAS meta-evaluation, treatment arms, trust gates, baselines, dashboards, and reproducibility metadata.
3. **Executable agent tasks**: Terminal-Bench/Harbor-style tasks that require an agent to edit code, compile, run, and pass correctness/performance verifiers.

The repository is currently focused on Intel library documentation quality experiments, especially oneTBB, oneDAL, and oneMKL.

## Quick start

Install dependencies:

```bash
pip install -r requirements.txt
pip install -r requirements-test.txt
```

Run the static documentation benchmark:

```bash
python cli.py run \
  --root . \
  --spec benchmarks/spec.v1.yaml \
  --out-json baselines/current.json \
  --out-md reports/current.md
```

Compare a candidate snapshot with a baseline:

```bash
python cli.py compare \
  --base data/baselines/baseline.json \
  --candidate baselines/current.json \
  --spec benchmarks/spec.v1.yaml \
  --out-json reports/compare.json \
  --out-md reports/compare.md
```

Run the test suite:

```bash
python -m pytest -q
```

For the LLM evaluation pipeline (answers, judging, dashboard), see [docs/quickstart.md](docs/quickstart.md). For benchmark invocation and comparison recipes, see [docs/benchmarking-and-comparison.md](docs/benchmarking-and-comparison.md). A high-level architecture map is in [docs/architecture.md](docs/architecture.md), and [docs/README.md](docs/README.md) is the documentation index.

## Main CLI areas

The top-level CLI is `python cli.py`. The main command groups are:

```text
run                 Run the static agent-quality benchmark
compare             Compare benchmark snapshots
report              Render JSON reports to Markdown
evaluate            Run the full evaluation pipeline
personas            Discover and approve target user personas
questions           Generate, analyze, refine, and panel-review questions
answers             Generate context-arm and baseline answers
arms                Compare context-augmentation treatments (docs/MCP/skills/profiles)
eval                Score answers, run RAGAS, or use a multi-judge panel
library             List/show registered products and intent domains (alias: product)
benchmark           Run registered library benchmarks
dashboard           Generate dashboard Markdown/JSON
```

Use `--help` on any command for detailed options, for example:

```bash
python cli.py questions --help
python cli.py eval --help
python cli.py dashboard generate --help
```

For end-to-end benchmark and comparison commands, including static snapshots,
LLM context-arm vs baseline runs, fair multi-model comparisons, treatment arms,
dashboards, and baselines, see
[docs/benchmarking-and-comparison.md](docs/benchmarking-and-comparison.md).

## Product and intent registries

Two top-level YAML registries describe what the benchmark can evaluate:

- **`products.yaml`** — *what products exist*: identity, description, repo, and
  doc sources for each product (oneTBB, oneMKL, VTune, dpnp, …). Used by
  `python cli.py library …` (alias: `product`) and `python cli.py benchmark …`.
- **`intents.yaml`** — *what user problems exist*: broad scenario domains
  (data science, machine learning, performance optimization, debugging, …),
  each mapped to the products that serve it, with example user intents. A
  domain may span several products — the seed of the discovery layer's
  capability/intent graph (see
  [`../software-packaging-for-agents/discovery.md`](../software-packaging-for-agents/discovery.md)).

The domain→product mapping lives only in `intents.yaml`;
`python -m agent_benchmarks.config_check` (run in CI) fails if it references an
unregistered product, or if `config/products.yaml` drifts from `products.yaml`.
Explore the mapping with:

```bash
python cli.py library intents                       # list domains + products
python cli.py library list --domain data-science    # products for a domain
python cli.py library show vtune                    # includes the product's domains
```

## Static benchmark metrics

The default static benchmark is configured in `benchmarks/spec.v1.yaml` and currently uses four active metrics:

| Metric | Purpose |
| --- | --- |
| `coverage` | Checks Markdown structure: headings, code blocks, and body content. |
| `freshness_lite` | Scores files by modification age. |
| `readability` | Estimates text readability with a Flesch-Kincaid-style score. |
| `example_pass_rate` | Executes supported fenced code examples in isolation. |

Weights are normalized across enabled metrics. The benchmark also supports soft gates, hard gates, critical bands, and regression thresholds. Hard gates and critical bands are enforced only when `--strict` is passed.

## LLM and treatment evaluation workflow

The LLM workflow is designed to answer a practical question: does documentation, a skill, an MCP source, or an agent profile improve model answers and task outcomes?

A typical one-command benchmark flow is:

```bash
python cli.py benchmark run \
  --library onetbb \
  --model gpt-4o-mini \
  --judge-model claude-sonnet-4 \
  --judge-provider anthropic \
  --multi-run 3
```

The pipeline discovers or loads personas, generates or reuses questions, answers each question in context-arm and baseline conditions, scores both answers with an independent judge, and writes model metadata, token usage, `question_set_hash`, reports, and trust-gate signals. For compatibility, persisted answer/evaluation JSON still uses the legacy `with_docs` and `without_docs` keys for those two conditions.

For fair multi-model comparisons, generate one question set and reuse it:

```bash
python cli.py benchmark run --library onedal --output-dir results/onedal_seed
python cli.py benchmark run --library onedal --questions-from results/onedal_seed --model gpt-4o
python cli.py benchmark run --library onedal --questions-from results/onedal_seed --model claude-sonnet-4 --provider anthropic
```

Generated artifacts go under `results/`, `reports/`, or `baselines/current.json` for temporary runs; those paths are git-ignored. Curated, version-controlled fixtures live under `data/` (`data/questions/`, `data/answers/`, `data/eval/`, `data/baselines/`, `data/skills/`, `data/agent_profiles/`) — see [`data/README.md`](data/README.md).

See [docs/decisions/benchmark-methodology.md](docs/decisions/benchmark-methodology.md) for the detailed model roles, question types, difficulty levels, task workflow, and trust checks.

## Executable oneTBB tasks

The repository includes terminal-bench-style tasks under `terminal-bench-tasks/`. These tasks validate not just text answers but working code and measurable behavior. Current CI builds the task containers and verifies oracle solutions with network disabled.

Included tasks cover oneTBB, oneMKL, oneDPL, IPP, and sklearnex examples. They are the executable side of the benchmark: they can test whether docs, skills, or an agent profile actually improve an agent's ability to produce correct and performant code.

## Repository layout

```text
cli.py                   Single entry point for all CLI commands
benchmarks/              Static benchmark spec and schema
config/                  LLM/runtime configuration for the eval track
products.yaml            Product registry: identity + doc sources per product
intents.yaml             Intent registry: problem/task domains mapped to products
agent_benchmarks/        Main Python package
  agent_profiles/        Agent persona prompt loader
  dashboard/             Dashboard aggregation/rendering
  eval/                  Answer generation, judges, panels, RAGAS, arm runner
  gate/                  Soft/hard gates and regression classification
  ingest/                Markdown loading and chunking
  mcp/                   Documentation source clients (incl. MCP protocol)
  metrics/               Static documentation metrics
  orchestrator/          Pipeline orchestration
  personas/              Persona generation/analysis (synthetic users)
  questions/             Question generation, validation, refinement
  report/                JSON/Markdown report generation
  runner/                Benchmark orchestration
  skills/                SKILL.md loader
  treatments/            Treatment-arm abstraction (docs/MCP/skills/profiles)
data/                    Curated, version-controlled benchmark fixtures (see data/README.md)
  questions/             Golden + sample question sets
  answers/               Sample reference answer pairs
  eval/                  Sample reference judge scores
  baselines/             Static docs-benchmark baseline snapshot
  skills/                Agent skill (SKILL.md) fixtures
  agent_profiles/        Agent persona (system) prompt fixtures
docs/                    Documentation
  README.md              Documentation index
  quickstart.md          End-to-end LLM evaluation pipeline
  architecture.md        Module map and data flow
  adding-doc-source.md   Local/URL/custom doc sources
  contributing-metric.md How to add a static documentation metric
  contributing-terminal-bench-task.md
                         How to add an executable task
  decisions/             Historical design reviews and investigations
terminal-bench-tasks/    Executable task definitions and verifiers
  README.md              Task format reference and task table
  COVERAGE.md            API/concept coverage matrix
  PROVENANCE.md          Upstream sources and licensing notes
tests/                   Pytest suite
```

## CI

GitHub Actions runs two workflows on pull requests.

`ci.yml` — fast code checks:

1. `lint` — `ruff check .`.
2. `mypy` — type check.
3. `schema` — validates `benchmarks/spec.v1.yaml` (`schema_check`) and checks
   registry drift (`config_check`).
4. `test` — pytest with coverage across Python 3.10–3.13.
5. `package-smoke` — builds and installs the package, then runs the console
   (`agent-benchmark`) and module (`python -m agent_benchmarks`) entry points.

`agent-quality.yml` — heavier, task/benchmark checks:

6. `terminal-bench-verify` / `terminal-bench-verify-oneapi` — build the task
   containers listed in the workflow and verify their oracle solutions offline
   (`--network none`). The list is an explicit allow-list in
   `agent-quality.yml`, not every directory under `terminal-bench-tasks/`, so a
   new task is only covered once it is added there.
7. `benchmark` — runs the static agent-quality benchmark and uploads artifacts.

Manual workflow dispatch on `agent-quality.yml` supports strict mode for
blocking quality gates.

## Repository hygiene

Do not commit generated logs, coverage databases, tarballs, local caches, or one-off experiment outputs. Keep generated benchmark artifacts either ignored locally or explicitly curated as fixtures. Use pull requests for all changes to `main`.

Status reports, phase plans, and other development-history notes do not belong in the repository — work-in-progress should live in PR descriptions, issues, and `BACKLOG.md`.

## Contributing

- Run `python -m pytest -q` before opening a PR.
- See [docs/contributing-metric.md](docs/contributing-metric.md) and
  [docs/contributing-terminal-bench-task.md](docs/contributing-terminal-bench-task.md)
  for the two main extension flows.
- Keep generated artifacts under `reports/` or `results/` (both ignored).
  Only commit curated fixtures that are part of a reproducible benchmark.

## License

Licensed under the [Apache License, Version 2.0](../LICENSE). See [NOTICE](../NOTICE)
for attribution. Contributions are accepted under the same license — see
[CONTRIBUTING.md](CONTRIBUTING.md). To report a security issue, see
[SECURITY.md](SECURITY.md).
