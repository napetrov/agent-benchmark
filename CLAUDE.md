# Agent instructions for this repository

This repo is the "Software Packaging for Agents" umbrella. It has two halves:

- `software-packaging-for-agents/` — vision/architecture docs only (no code).
  Six tracks: author → build → measure → package → discover → serve.
- `agent-benchmark/` — the measurement engine, a self-contained Python project.
  All runnable code, tests, and CI live here.

## Working in `agent-benchmark/`

```bash
cd agent-benchmark
pip install -r requirements.txt -r requirements-test.txt
python -m pytest -q                      # run before every PR; CI runs this
python -m agent_benchmarks.config_check  # registry consistency; CI runs this
python cli.py --help                     # single CLI entry point
```

CI also runs `ruff check .`, `mypy`, and `python -m agent_benchmarks.schema_check`.
See `agent-benchmark/CONTRIBUTING.md` for the full set of checks to run before a PR.

- The Python package is `agent_benchmarks/` (note: plural), organized by
  pipeline stage (`metrics/`, `questions/`, `eval/`, `gate/`, `treatments/`, …).
  See `agent-benchmark/docs/architecture.md` for the module map.
- Key registries (top level of `agent-benchmark/`):
  - `products.yaml` — product identity + doc sources (what products exist).
  - `intents.yaml` — problem/intent domains mapped to products (what user
    problems exist). The domain→product mapping lives only here.
  - `config/products.yaml` — LLM/runtime config for the eval track only;
    identity stated there must not drift from `products.yaml`.
- Executable tasks live in `agent-benchmark/terminal-bench-tasks/` (Docker +
  oracle solution + pytest verifier). CI builds and verifies them offline.

## Conventions

- Never commit generated artifacts: `results/`, `reports/`, `baselines/current.json`,
  coverage files, logs, tarballs. Curated fixtures go under `agent-benchmark/data/`.
- Status reports and phase plans do not belong in the repo — use PR
  descriptions, issues, and `agent-benchmark/BACKLOG.md`.
- All changes to `main` go through pull requests.
- Persisted answer/eval JSON keeps legacy `with_docs`/`without_docs` keys for
  the two answer conditions — do not rename them in data files.
- Docs: `agent-benchmark/docs/README.md` is the documentation index; design
  decisions go in `agent-benchmark/docs/decisions/` as dated ADRs.
