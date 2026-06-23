# Contributing

Thanks for your interest in improving agent-benchmark. This guide covers the
mechanics; for architecture and design context start with
[docs/architecture.md](docs/architecture.md).

## License of contributions

By submitting a contribution you agree that it is licensed under the
[Apache License 2.0](../LICENSE), the same license as the project.

## Development setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"        # editable install + dev tooling
```

The package exposes a console entry point:

```bash
agent-benchmark --help           # equivalent to `python -m agent_benchmarks`
```

Optional feature sets are available as extras: `ocr` (Docling ingestion),
`mcp`, and `embeddings`. Install what you need, e.g. `pip install -e ".[dev,ocr]"`.

## Before you open a PR

Run the same checks CI runs:

```bash
ruff check .                              # lint
mypy                                      # type check (config in pyproject.toml)
python -m agent_benchmarks.schema_check benchmarks/spec.v1.yaml   # validate the benchmark spec
python -m agent_benchmarks.config_check   # registry drift check
pytest                                    # tests
```

Guidelines:

- **Keep changes focused.** One logical change per PR; it makes review and
  bisecting easier.
- **Add tests** for behavioral changes. The suite lives in `tests/` and runs
  fully offline (LLM/network calls are mocked).
- **Update docs** in the same PR when you change behavior. Stale docs are
  treated as bugs — see the docs-drift checklist below.
- **Don't commit ad-hoc run output.** Generated artifacts belong under
  `reports/`/`results/` (git-ignored). Only commit curated fixtures that are
  part of a reproducible benchmark.

## Adding things

- A new static metric: [docs/contributing-metric.md](docs/contributing-metric.md)
- A new doc source: [docs/adding-doc-source.md](docs/adding-doc-source.md)
- A terminal-bench task: [docs/contributing-terminal-bench-task.md](docs/contributing-terminal-bench-task.md)

## Docs-drift checklist

When your change touches user-facing behavior, confirm:

- [ ] Quickstart / README commands still match the CLI.
- [ ] Any new flag or artifact field is documented.
- [ ] Code examples in docs still run.
- [ ] Links resolve.

## Subsystem ownership

The repo spans three loosely-coupled subsystems; see
[CODEOWNERS](../.github/CODEOWNERS) for review routing:

- **static benchmark** — `agent_benchmarks/runner`, `metrics`, `ingest`, `gate`
- **LLM eval** — `agent_benchmarks/eval`, `questions`, `personas`, `treatments`
- **terminal-bench tasks** — `terminal-bench-tasks/`
