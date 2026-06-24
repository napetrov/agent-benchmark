# Exploration tasks (ExploreBench)

Each YAML file here is one **exploration-only** task for the ExploreBench track
(BACKLOG #60, see `docs/decisions/2026-06-23-exploration-quality-fastcontext.md`).
A task poses a localization question and declares the reference locations a good
explorer should cite. It scores *whether the agent can find the right evidence*
— separately from whether it can answer or solve.

## Schema

```yaml
id: short-stable-id
product: oneTBB                 # product / repo the task is about
query: "Where is X implemented?"  # the localization question
repo_root: .                    # optional; defaults to the agent-benchmark repo
references:
  - path: docs/flow_graph.md
    lines: [120, 180]           # optional inclusive [start, end] (or [n])
  - path: examples/pipeline.cpp # no `lines` → a whole-file reference
```

- `lines` is inclusive `[start, end]` (or `[n]` for a single line). Omit it for a
  whole-file reference, which scores at **file** granularity only.
- `repo_root` is the tree the explorer searches and the base for reference
  paths; it defaults to the `agent-benchmark/` repo root.

## Running

```bash
python cli.py explore list
python cli.py explore run --all --arms oracle,empty --baseline-arm empty \
  --out-json results/explore-runs/explore_runs.json \
  --out-md   reports/exploration.md
```

`oracle` cites exactly the references (a ceiling); `empty` returns nothing (a
floor); `command:<template>` runs a real CLI explorer — for example:

```bash
python cli.py explore run --all \
  --arms 'empty,command:claude -p {query_quoted}' --baseline-arm empty
```

## About this seed set

These seed tasks **dogfood the agent-benchmark repo itself**: their references
point at real files in this tree, so they are runnable and verifiable offline
and exercise an explorer on a real codebase. They use file-level references
because line numbers in an evolving repo drift; line-level scoring is covered by
unit tests and by curated/oracle tasks.

Intel/oneAPI tasks plug in with the **same schema** — set `repo_root` to the
product checkout and derive `references` from the oracle solution's edited
files/ranges (or curate doc/example locations). Per the ADR caveat, pair
citation F1 with task pass-rate and judge score; patch-derived locations
under-credit supporting evidence (tests, callers, neighbors).
