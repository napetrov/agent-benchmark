# Coding Harnesses And Task Runs

Executable task runs measure whether an agent can do the work, not only answer
questions about an API. The `tasks run` command runs Harbor/terminal-bench task
directories through named harnesses, records operation telemetry, and compares
pass rate against a baseline harness.

## Supported Harnesses

- `codex` — runs Harbor with agent id `codex`.
- `claude-code` — runs Harbor with agent id `claude-code`.
- `terminal-bench:<agent>` — runs any Harbor agent id, for example
  `terminal-bench:terminus`.
- `command:<template>` or `--command-template` — runs a custom command template
  for local wrappers and CI fakes.

The built-in Codex and Claude Code harnesses intentionally use Harbor because
the repository's executable tasks already follow the Harbor/terminal-bench
contract. The adapter command is:

```bash
harbor run -p <task-path> -a <agent> -m <model> --jobs-dir <run-dir>
```

Harbor writes job/trial results under the jobs directory. If a local Harbor
version uses different flags, pass `--command-template` and keep the same output
contract.

## Run Examples

List known harnesses:

```bash
python cli.py tasks harnesses
```

Run one task through Codex and compare it to Claude Code:

```bash
python cli.py tasks run \
  --tasks onetbb-parallel-reduce \
  --harnesses claude-code,codex \
  --baseline-harness claude-code \
  --model anthropic/claude-opus-4-6 \
  --out-json results/task-runs/onetbb-reduce.json
```

If `--baseline-harness` is not listed in `--harnesses`, the CLI adds it to the
run matrix and prints that it will also run the baseline harness.

Run all tasks through a custom wrapper:

```bash
python cli.py tasks run \
  --all \
  --harnesses command \
  --command-template "my-agent --task {task_path} --model {model} --out {output_dir}" \
  --model my-model
```

Use `--dry-run` to validate matrix expansion and artifact shape without invoking
external agents.

## Output Artifact

`tasks run` writes a `task_runs.v1` JSON artifact. Important fields:

- `results[]`: one row per `(task, harness, model)` cell.
- `results[].passed`: verifier pass/fail. If a reward file is present,
  `1.0` means pass and `0.0` means fail. If no reward is found, adapter exit code
  is used as the fallback.
- `results[].metrics.operation_count`: number of tracked harness operations.
- `results[].metrics.operations_by_type`: counts for operation classes such as
  `harness`, `loop`, `tool`, and `subagent`.
- `summary.per_harness`: pass rate, elapsed time, and operation totals.
- `summary.comparisons`: deltas against `--baseline-harness`.

The artifact is schema-validated on write, like question/answer/eval/arms
artifacts.

## Operation Telemetry

Every run records the top-level harness invocation. Wrappers and adapters can add
structured operation telemetry in two ways:

1. Append JSON lines to the path in `AGENT_BENCHMARK_OPERATIONS_FILE`.
2. Print a line prefixed with `AGENT_BENCHMARK_OP` followed by a JSON object.

Example:

```text
AGENT_BENCHMARK_OP {"type":"tool","name":"edit","elapsed_sec":0.12}
AGENT_BENCHMARK_OP {"type":"subagent","name":"reviewer","status":"ok"}
AGENT_BENCHMARK_OP {"type":"loop","name":"turn","elapsed_sec":3.4}
```

Unstructured stdout/stderr lines mentioning `tool`, `subagent`, or `loop` are
also counted as low-fidelity telemetry, but structured events are preferred.

## Fair Comparisons

Use one task suite, one model, and fixed task revisions when comparing harnesses.
The baseline harness is not a treatment arm; it is the reference cell for
pass-rate deltas. For example, compare `codex` to `claude-code` only when both
ran the same task set under the same model and task commit.

The Q&A `arms run` path remains separate. It measures context artifacts with an
LLM judge. The `tasks run` path measures executable work with verifier pass rate.
