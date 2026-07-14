# Terminal-Bench Tasks for Intel oneAPI Libraries

This directory contains [Terminal-Bench](https://github.com/laude-institute/terminal-bench) /
[Harbor](https://github.com/laude-institute/harbor) tasks for evaluating LLM coding agents
on Intel oneAPI libraries (oneTBB, oneMKL, oneCCL, IPP, etc.).

## Why Terminal-Bench?

Unlike pure Q&A benchmarks, Terminal-Bench tasks require the agent to:
- Write real C++ / Python code using Intel libraries
- Compile and run it in an isolated Docker environment
- Pass automated correctness **and** performance tests

This complements the existing `eval/` Q&A benchmark with **coding-task evaluation**. The same task set can compare a base agent against an agent given extra documentation, reusable skills, a different agent profile, or another context artifact.

## Task Structure

Each task follows the [Harbor task format](https://harborframework.com/docs/tasks):

```text
terminal-bench-tasks/<task-name>/
  instruction.md          # Natural-language task description shown to the agent
  task.toml               # Config: timeouts, Docker image, metadata
  environment/
    Dockerfile            # Container with preinstalled libs
    <seed files>          # Starter code, data files, etc.
  tests/
    test.sh               # Entry point: runs pytest, writes /logs/verifier/reward.txt
    test_*.py             # Pytest test cases
  solution/
    solve.sh              # Oracle solution (sanity check, not shown to agent)
```

## Available Tasks

See [COVERAGE.md](./COVERAGE.md) for the broader oneTBB API/concept coverage matrix and planned gaps.

| Task | Library | Difficulty | What it tests |
|------|---------|------------|---------------|
| [onetbb-parallel-sort](./onetbb-parallel-sort/) | oneTBB | medium | `tbb::parallel_sort` on 10M integers; correctness + ≤5s wall time |
| [onetbb-nstream](./onetbb-nstream/) | oneTBB | medium | ParRes-inspired streaming triad with `parallel_for` + `parallel_reduce` |
| [onetbb-stencil](./onetbb-stencil/) | oneTBB | medium | ParRes-inspired 2D stencil with tiled `blocked_range2d` parallelism |
| [onetbb-transpose](./onetbb-transpose/) | oneTBB | medium | ParRes-inspired tiled matrix transpose with `blocked_range2d` |
| [onetbb-parallel-reduce](./onetbb-parallel-reduce/) | oneTBB | medium | Aggregate sum/sumsq/min/max with `parallel_reduce` |
| [onetbb-parallel-scan](./onetbb-parallel-scan/) | oneTBB | medium | Inclusive prefix sum with `parallel_scan` |
| [onetbb-flow-graph](./onetbb-flow-graph/) | oneTBB | medium | Deterministic transform pipeline with `flow::graph` and `function_node` |
| [onemkl-dgemm](./onemkl-dgemm/) | oneMKL | medium | Dense matrix multiply with `cblas_dgemm`, signature vs serial reference |
| [onemkl-fft](./onemkl-fft/) | oneMKL | medium | DFTI forward/backward FFT round-trip + spectrum vs naive DFT |
| [onedpl-transform-reduce](./onedpl-transform-reduce/) | oneDPL | medium | Parallel `transform_reduce` (`par_unseq`) on the oneTBB backend |
| [ipp-dotprod](./ipp-dotprod/) | IPP | easy | Vector dot product with `ippsDotProd_64f` vs serial reference |
| [sklearnex-classification](./sklearnex-classification/) | sklearnex | easy | KNN classifier accelerated with `patch_sklearn()`, accuracy vs stock sklearn |
| [dpnp-device-fallback](./dpnp-device-fallback/) | dpnp | medium | Portable dpnp computation with `dpctl` device selection: GPU-first attempt, graceful CPU fallback, signature vs NumPy reference |
| [dpnp-reduction-stats](./dpnp-reduction-stats/) | dpnp | easy | Per-column (`axis=0`) sum/mean/std reductions with dpnp, combined signature vs NumPy reference |
| [dpnp-migration-replace-numpy](./dpnp-migration-replace-numpy/) | dpnp | easy | Migrate a NumPy preprocessing pipeline to dpnp, preserving results with a NumPy fallback for unsupported `histogram(bins='auto')` |
| [dpnp-linalg-matmul](./dpnp-linalg-matmul/) | dpnp | medium | Matrix multiply with `dpnp.matmul` / `@`, absolute-value-sum signature vs serial NumPy reference |
| [dpnp-fft-pipeline](./dpnp-fft-pipeline/) | dpnp | medium | Power spectrum via `dpnp.fft.fft`, signature vs NumPy reference; validates power-of-2 length CLI argument |
| [intel-perf-serial-accumulator](./intel-perf-serial-accumulator/) | Intel performance skills | medium | Diagnose low-IPC serial accumulator and rewrite with independent partial accumulators |
| [intel-perf-false-sharing](./intel-perf-false-sharing/) | Intel performance skills | medium | Diagnose c2c/HITM false sharing and separate per-thread counters by cache line |
| [intel-perf-shared-counter](./intel-perf-shared-counter/) | Intel performance skills | medium | Replace a hot global atomic statistics counter with local aggregation |
| [intel-perf-missing-restrict](./intel-perf-missing-restrict/) | Intel performance skills | medium | Add a valid C `restrict` contract to remove aliasing/vectorization barriers |
| [intel-perf-hotspot-report](./intel-perf-hotspot-report/) | Intel performance skills | medium | Produce a structured hotspot report from provided perf artifacts |
| [intel-perf-crc32c](./intel-perf-crc32c/) | Intel performance skills | medium | Replace a bit-at-a-time CRC32C software loop with the SSE4.2 `crc32` instruction (CPU dispatch + portable fallback), matching the exact checksum |
| [intel-perf-cv-herd](./intel-perf-cv-herd/) | Intel performance skills | medium | Diagnose a condition-variable thundering herd (`notify_all` per job) and reduce wakeups without losing or double-processing jobs |
| [intel-perf-mutex-rwlock](./intel-perf-mutex-rwlock/) | Intel performance skills | medium | Convert a read-mostly `std::mutex` bottleneck to a reader-writer lock (`std::shared_mutex`), preserving the write path and correctness |
| [intel-perf-ttas-spinlock](./intel-perf-ttas-spinlock/) | Intel performance skills | medium | Convert a test-and-set spinlock to test-and-test-and-set to stop cache-line bouncing under contention, preserving mutual exclusion |
| [intel-perf-simd-sort](./intel-perf-simd-sort/) | Intel performance skills | hard | Replace `std::sort` on floats with a faster non-comparison/vectorized sort (stability not required), matching the sorted multiset signature |
| [intel-perf-branch-mispredict](./intel-perf-branch-mispredict/) | Intel performance skills | medium | Diagnose a ~25% branch-miss hot loop (data-dependent `if`) from perf stat and convert it to branchless/predicated summation, preserving the exact total |

> The oneTBB tasks build entirely from `ubuntu:22.04` + standard apt and are
> verified in the `terminal-bench-verify` CI job. The oneMKL / oneDPL / IPP /
> oneCCL / sklearnex / dpnp tasks pull the Intel oneAPI apt repo, header-only
> oneDPL, the `intel/oneapi-basekit` image, or pip wheels at **build** time (the
> verifier still runs offline with `--network none`) and are verified in a
> separate `terminal-bench-verify-oneapi` CI job so a heavy-image build cannot
> affect the core oneTBB job.

## Running a Task (Harbor)

```bash
pip install harbor-cli   # or: uv tool install harbor-cli

# Evaluate an agent on a single task
harbor run \
  -p terminal-bench-tasks/onetbb-parallel-sort \
  -a terminus \
  -m anthropic/claude-opus-4-6

# Use the Oracle agent to sanity-check the solution
harbor run \
  -p terminal-bench-tasks/onetbb-parallel-sort \
  -a oracle
```

## Running Harness Comparisons

`agent-benchmark` can run these tasks through named coding harnesses and write a
schema-validated `task_runs.v1` artifact:

```bash
python cli.py tasks run \
  --tasks onetbb-parallel-sort \
  --harnesses claude-code,codex \
  --baseline-harness claude-code \
  --model anthropic/claude-opus-4-6 \
  --out-json results/task-runs/onetbb-sort.json
```

Built-in aliases are the Harbor-backed `codex`, `claude-code`, and
`terminal-bench:<agent>`, plus the no-Harbor `docker-oracle`, `docker-claude`,
and `docker-claude-skill:<skill>` harnesses — the `docker-claude*` ones build,
solve, and verify against local Docker and record full LLM telemetry (cost,
tokens, cache, latency, turns). To run the without-skill vs with-skill
experiment with variance:

```bash
python cli.py tasks run \
  --tasks intel-perf-serial-accumulator,intel-perf-false-sharing \
  --harnesses docker-claude,docker-claude-skill:data/skills/intel-performance-patterns/SKILL.md \
  --baseline-harness docker-claude \
  --model us.anthropic.claude-haiku-4-5-20251001-v1:0 \
  --repeats 3 \
  --out-json results/skill-task-arms.json
```

`tasks run` writes two artifacts: the schema-validated JSON (`--out-json`) and a
Markdown report alongside it (override with `--out-md`). The report has a
headline, a difficulty rollup, the per-harness comparison, a per-task pass/cost
table, and a per-cell answer detail that contrasts the verifier verdict with the
model's own self-report (the ⚠️ cells claimed success but failed the verifier).

For analysis, export the run to a flat per-cell table (one row per cell, with
the telemetry lifted into `metric_*` columns):

```bash
python cli.py dataset export --kind task_runs \
  --input results/skill-task-arms.json \
  --out-dir results/skill-task-arms-dataset --format jsonl   # or parquet / hf
```

Operation telemetry is also collected from wrapper JSONL logs and
`AGENT_BENCHMARK_OP` stdout/stderr markers. See
[`docs/coding-harnesses.md`](../docs/coding-harnesses.md) for the full contract.

## Provenance

The ParRes-inspired tasks are simplified exercises derived from the ideas in [ParRes/Kernels](https://github.com/ParRes/Kernels), not verbatim copies of upstream source files. See [PROVENANCE.md](./PROVENANCE.md) for details and license notes.

## Docker Images

Tasks use custom Docker images built from `environment/Dockerfile`.
To build locally:

```bash
docker build -t intel-hpc-bench/onetbb-parallel-sort:latest \
  terminal-bench-tasks/onetbb-parallel-sort/environment/
docker build -t intel-hpc-bench/onetbb-nstream:latest \
  terminal-bench-tasks/onetbb-nstream/environment/

# oneAPI-component tasks pull large dependencies at build time:
docker build -t intel-hpc-bench/onemkl-dgemm:latest \
  terminal-bench-tasks/onemkl-dgemm/environment/
docker build -t intel-hpc-bench/sklearnex-classification:latest \
  terminal-bench-tasks/sklearnex-classification/environment/
```

## Adding New Tasks

1. Pick an API/concept gap from [COVERAGE.md](./COVERAGE.md).
2. Copy an existing task folder as a template.
3. Update `instruction.md`, `task.toml`, `environment/Dockerfile`, and starter sources.
4. Write tests in `tests/test_*.py` — they must write `1` or `0` to `/logs/verifier/reward.txt` via `tests/test.sh`.
5. Add a deterministic oracle solution in `solution/solve.sh`.
6. Build the Docker image and smoke-test the oracle verifier offline with `--network none`.
7. Add a row to the table above and update the coverage matrix.

## Roadmap

Done:

- [x] `onetbb-parallel-reduce` — aggregate with `tbb::parallel_reduce`
- [x] `onetbb-flow-graph` — transform pipeline with `tbb::flow::graph`
- [x] `onemkl-dgemm` — matrix multiply via `cblas_dgemm`
- [x] `onemkl-fft` — FFT round-trip via DFTI
- [x] `onedpl-transform-reduce` — parallel STL `transform_reduce`
- [x] `ipp-dotprod` — signal-processing dot product via `ippsDotProd_64f`
- [x] `sklearnex-classification` — accelerated scikit-learn workflow

Next candidates (see [COVERAGE.md](./COVERAGE.md) for the full plan + validation
strategies):

- [ ] `onemkl-rng` — reproducible random number generation via the MKL VSL/RNG API
- [ ] `onednn-gemm` or `onednn-relu` — a single oneDNN primitive vs a serial reference
- [ ] `ipp-image-resize` — image resize with `ippiResize`, verify pixel accuracy
- [ ] `ippcp-aes` — AES round-trip with IPP Cryptography
- [ ] `openmp-reduce` — OpenMP parallel reduction (offline, stock `-fopenmp`)
- [ ] `onedpl-sort` — `oneapi::dpl::sort` with a parallel policy
- [ ] `oneccl-allreduce` — multi-process allreduce with oneCCL + MPI (needs
      real-image iteration: MPI/oneCCL transport under `--network none`)

Intel performance skills tasks:

- [x] `intel-perf-serial-accumulator` — low-IPC reduction dependency with a deterministic speedup verifier
- [x] `intel-perf-false-sharing` — synthetic `perf c2c` evidence plus cache-line layout fix
- [x] `intel-perf-shared-counter` — true-sharing statistics counter replaced by local aggregation
- [x] `intel-perf-missing-restrict` — C aliasing contract and vectorization evidence
- [x] `intel-perf-hotspot-report` — report-only interpretation of static perf artifacts
- [x] `intel-perf-branch-mispredict` — data-dependent branch in a hot loop, branchless rewrite with deterministic speedup verifier
