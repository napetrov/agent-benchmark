# Benchmarking and comparison guide

This guide describes how to run the supported benchmark flows and how to compare
results. Run all commands from `agent-benchmark/`.

## Comparison modes

`agent-benchmark` has four practical comparison modes:

- **Static snapshot comparison**: compare documentation quality snapshots from
  `python cli.py run`.
- **LLM context comparison**: compare one answer model's context-arm and
  baseline answers. Persisted JSON keeps the legacy `with_docs` and
  `without_docs` keys for compatibility.
- **Multi-model comparison**: run multiple answer models on the same question
  set and compare their evaluated JSON outputs.
- **Treatment-arm comparison**: compare `baseline` against docs, MCP, skills,
  profiles, or agentic tool-use arms.

Keep only one axis variable at a time. For example, a model comparison should
reuse the same questions, doc source, judge setup, and retrieval configuration.

## Static documentation benchmark

Use the static benchmark when the question is "did this documentation snapshot
get structurally better or worse?"

```bash
python cli.py run \
  --root . \
  --spec benchmarks/spec.v1.yaml \
  --out-json baselines/current.json \
  --out-md reports/current.md
```

The JSON snapshot contains summary metrics such as coverage, freshness,
readability, and example pass rate. The Markdown report is a human-readable
view of the same run.

Compare a candidate snapshot with a saved baseline:

```bash
python cli.py compare \
  --base data/baselines/baseline.json \
  --candidate baselines/current.json \
  --spec benchmarks/spec.v1.yaml \
  --out-json reports/compare.json \
  --out-md reports/compare.md
```

The compare command computes candidate-minus-baseline deltas and, when `--spec`
is passed, applies configured regression thresholds.

Equivalent Make targets are available from the repository root:

```bash
make benchmark-run
make benchmark-compare
```

## LLM context benchmark

Use the LLM benchmark when the question is "does documentation or another
context artifact improve answers?"

For registered libraries, prefer the one-command wrapper:

```bash
python cli.py benchmark run \
  --library onetbb \
  --model gpt-4o-mini \
  --provider openai \
  --judge-model claude-sonnet-4 \
  --judge-provider anthropic \
  --output-dir results/onetbb_gpt4omini
```

The run writes:

- `results/onetbb_gpt4omini/personas/oneTBB.json`
- `results/onetbb_gpt4omini/questions/oneTBB.json`
- `results/onetbb_gpt4omini/answers/oneTBB.json`
- `results/onetbb_gpt4omini/eval/oneTBB.json`
- `results/onetbb_gpt4omini/reports/oneTBB.md`

The comparison inside one run is always:

```text
delta = context-arm score - baseline score
```

Positive delta means the context helped on that judged question. Negative delta
means either retrieval hurt the answer, the model already knew enough without
context, or the retrieved chunks were irrelevant.

For stability-sensitive claims, run the same configuration several times:

```bash
python cli.py benchmark run \
  --library onetbb \
  --model gpt-4o-mini \
  --judge-model claude-sonnet-4 \
  --judge-provider anthropic \
  --multi-run 3 \
  --output-dir results/onetbb_gpt4omini
```

Multi-run mode creates numbered run directories and prints the mean and
standard deviation of the context-arm average.

## Fair multi-model comparison

A fair model comparison must use the same questions for every model. First
create or choose a seed run:

```bash
python cli.py benchmark run \
  --library onedal \
  --model gpt-4o-mini \
  --judge-model claude-sonnet-4 \
  --judge-provider anthropic \
  --output-dir results/onedal_seed
```

Then reuse that question set for each model:

```bash
python cli.py benchmark run \
  --library onedal \
  --questions-from results/onedal_seed \
  --model gpt-4o \
  --provider openai \
  --judge-model claude-sonnet-4 \
  --judge-provider anthropic \
  --output-dir results/onedal_gpt4o

python cli.py benchmark run \
  --library onedal \
  --questions-from results/onedal_seed \
  --model anthropic/claude-sonnet-4-6 \
  --provider openrouter \
  --judge-model claude-sonnet-4 \
  --judge-provider anthropic \
  --output-dir results/onedal_sonnet46
```

Interpret model comparisons using two separate signals:

- **Absolute quality**: the context-arm average from each run.
- **Context benefit**: the average `delta` from each run.

Do not rank models by delta alone. A strong model can have a small delta because
its baseline score is already high.

Generate a cross-run dashboard when you have multiple eval files:

```bash
python cli.py dashboard generate \
  --results-dir results \
  --output-dir reports
```

The dashboard reads evaluation artifacts and writes `reports/DASHBOARD.md` and
`reports/dashboard.json`.

## Standalone pipeline commands

Use the lower-level commands when you need explicit control over each artifact:

```bash
python cli.py answers generate \
  --product oneTBB \
  --questions data/questions/onetbb_golden.json \
  --output results/onetbb_golden/answers/oneTBB.json \
  --model gpt-4o-mini \
  --provider openai \
  --debug-retrieval

python cli.py eval score \
  --product oneTBB \
  --answers results/onetbb_golden/answers/oneTBB.json \
  --output results/onetbb_golden/eval/oneTBB.json \
  --judge-model claude-sonnet-4 \
  --judge-provider anthropic

python cli.py report eval \
  --product oneTBB \
  --eval results/onetbb_golden/eval/oneTBB.json \
  --out results/onetbb_golden/reports/oneTBB_full.md
```

Use `report generate` instead of `report eval` when you also want the questions
file included in the report generator:

```bash
python cli.py report generate \
  --product oneTBB \
  --eval results/onetbb_golden/eval/oneTBB.json \
  --questions data/questions/onetbb_golden.json \
  --output results/onetbb_golden/reports/oneTBB.md \
  --format markdown
```

## Treatment-arm comparison

Use treatment arms when comparing context artifacts rather than models:

```bash
python cli.py arms run \
  --product oneTBB \
  --questions data/questions/onetbb_golden.json \
  --arms "baseline,docs,skill:data/skills/onetbb-quickstart" \
  --judge \
  --out-json results/arms/onetbb_skill.json \
  --out-md results/arms/onetbb_skill.md
```

The `baseline` arm is the control. Every other arm is compared against it. Keep
the answer model and judge fixed when comparing arms.

## Multi-model comparison

Use `report model-compare` to compare judged treatment-arm JSON files from
multiple models.

The intended input is one judged arms JSON file per model for regular questions
and/or golden questions. The report extracts the `baseline_arm` score as the
baseline and the treatment arm as the context arm, then computes:

- overall context-arm, baseline, and delta per run,
- resource usage metrics (cost, tokens, latency, cache hit ratio) from the
  baseline arm when available,
- statistical significance of context-arm minus baseline (paired t-test,
  Wilcoxon, Cohen\u2019s d_z) when scipy is installed,
- difficulty breakdown on common question IDs,
- head-to-head winners on common question IDs,
- ranking by absolute context-arm score and by delta.

**All summary, significance, difficulty, and head-to-head metrics use only the
common question set** (intersection of question IDs across all runs).

```bash
python cli.py report model-compare \
  --regular-runs results/arms/dpnp_regular_sonnet46.json results/arms/dpnp_regular_opus48.json \
  --golden-runs  results/arms/dpnp_golden_sonnet46.json  results/arms/dpnp_golden_opus48.json \
  --run-ids sonnet46,opus48 \
  --out results/dpnp_compare.md
```

Regular and golden options may be used independently:

```bash
# Regular questions only
python cli.py report model-compare \
  --regular-runs results/arms/dpnp_regular_sonnet46.json results/arms/dpnp_regular_opus48.json \
  --run-ids sonnet46,opus48 \
  --out results/dpnp_regular_compare.md

# Golden questions only
python cli.py report model-compare \
  --golden-runs results/arms/dpnp_golden_sonnet46.json results/arms/dpnp_golden_opus48.json \
  --run-ids sonnet46,opus48 \
  --out results/dpnp_golden_compare.md
```

When a run contains more than one non-baseline arm, specify which one to score:

```bash
python cli.py report model-compare \
  --regular-runs run_a.json run_b.json \
  --run-ids a,b \
  --treatment-arm with-skill \
  --out compare.md
```

The report includes a **Resource Usage** section when cost and telemetry data
are available in the input JSON files. This section shows baseline-arm metrics
for cost-per-run (in USD), token counts (prompt, completion, total), average
latency per question, and cache hit ratio. Use this section to compare
cost-effectiveness and performance characteristics across models. When a metric
is unavailable for a particular run, the table displays a placeholder (—) rather
than zero.


Consistency is validated before the report is written:

- Different `baseline_arm` values across runs in the same group abort with an
  error.
- Diverging `question_set_hash` values (when present) produce a warning on
  stderr.
- Runs that share the same model and provider produce a warning (likely
  duplicate rather than a real comparison).

For programmatic use, import from the package directly:

```python
from agent_benchmarks.report.model_compare import (
    check_run_consistency,
    generate_combined_report,
    load_run,
)
```

## Baselines

Save meaningful eval outputs as named baselines:

```bash
python cli.py baseline save \
  --from-eval results/onetbb_gpt4omini/eval/oneTBB.json \
  --name onetbb-gpt4omini-docs
```

Compare a future eval against a saved baseline:

```bash
python cli.py baseline compare \
  --baseline onetbb-gpt4omini-docs \
  --eval results/onetbb_candidate/eval/oneTBB.json
```

Use baselines for release-to-release tracking. Use `--questions-from` for
model-to-model fairness.

## What to commit

Commit curated fixtures under `data/` when they define a reproducible benchmark:

- `data/questions/*.json`
- `data/answers/*.json`
- `data/eval/*.json`
- `data/baselines/*.json`
- `data/skills/*/SKILL.md`
- `data/agent_profiles/*.md`

Keep generated experiment outputs under `results/`, `reports/`, or
`baselines/current.json`; those are working artifacts and should normally stay
git-ignored.
