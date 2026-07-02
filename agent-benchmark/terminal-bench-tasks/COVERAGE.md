# Executable task coverage (Intel oneAPI components)

This document tracks which Intel oneAPI APIs and concepts are covered by
terminal-bench-style coding tasks, and the planned gaps per component.

## Product coverage matrix (questions × tasks)

<!-- GENERATED: `python -m agent_benchmarks.coverage` (ADR Phase A coverage
contract). Awareness = a golden question set exists; Work = number of
terminal-bench tasks whose `task.toml` tags name this product. Status is the
honest effective state (`covered` needs both halves; `questions-only` and
`planned` are visible, tracked gaps — never silent). Edit `products.yaml`
`coverage_status` and add tasks/questions, not this table, then regenerate. -->

| Product | Awareness (questions) | Work (tasks) | Status |
| --- | --- | --- | --- |
| `advisor` | ⬜ | ⬜ 0 | planned |
| `dpctl` | ⬜ | ⬜ 0 | planned |
| `dpnp` | ✅ | ✅ 5 | covered |
| `gdb_intel` | ⬜ | ⬜ 0 | planned |
| `icx` | ⬜ | ⬜ 0 | planned |
| `ifort` | ⬜ | ⬜ 0 | planned |
| `inspector` | ⬜ | ⬜ 0 | planned |
| `intel_performance_skills` | ✅ | ✅ 16 | covered |
| `intelmpi` | ⬜ | ⬜ 0 | planned |
| `ipp` | ⬜ | ✅ 1 | planned |
| `numba_dpex` | ⬜ | ⬜ 0 | planned |
| `oneccl` | ⬜ | ⬜ 0 | planned |
| `onedal` | ✅ | ✅ 1 | covered |
| `onednn` | ⬜ | ⬜ 0 | planned |
| `onedpl` | ⬜ | ✅ 1 | planned |
| `onemath` | ⬜ | ⬜ 0 | planned |
| `onemkl` | ✅ | ✅ 2 | covered |
| `onetbb` | ✅ | ✅ 7 | covered |
| `openmp` | ⬜ | ⬜ 0 | planned |
| `openvino` | ⬜ | ⬜ 0 | planned |
| `optimization_guide` | ⬜ | ⬜ 0 | planned |
| `sklearnex` | ⬜ | ✅ 1 | planned |
| `vtune` | ⬜ | ⬜ 0 | planned |

## oneTBB

This matrix tracks which oneTBB APIs and concepts are covered by terminal-bench-style coding tasks.

| API / concept | Task | Status | Verifier strategy |
| --- | --- | --- | --- |
| `parallel_sort` | `onetbb-parallel-sort` | merged | Sort correctness, runtime bound, source marker checks |
| `parallel_for` + `parallel_reduce` | `onetbb-nstream` | merged | Serial checksum comparison, source marker checks |
| `blocked_range2d` stencil update | `onetbb-stencil` | merged | Serial norm comparison, source marker checks |
| `blocked_range2d` transpose | `onetbb-transpose` | merged | Serial probe-signature comparison, source marker checks |
| `parallel_reduce` | `onetbb-parallel-reduce` | implemented | Serial aggregate comparison, source marker checks |
| `parallel_scan` | `onetbb-parallel-scan` | implemented | Serial prefix signature comparison, source marker checks |
| `flow::graph` | `onetbb-flow-graph` | implemented | Deterministic graph output comparison, graph API checks |
| `task_group` | TBD | candidate | Dependency/task execution validation |
| `concurrent_hash_map` | TBD | candidate | Concurrent update correctness and source API checks |
| `task_arena` / `global_control` | TBD | candidate | Thread-limit behavior and source API checks |

## Other oneAPI components

These tasks live in the separate `terminal-bench-verify-oneapi` CI job because
they pull the Intel oneAPI apt repo, header-only oneDPL from GitHub, or pip
wheels at **build** time. The verifier still runs offline (`--network none`).

| Component | API / concept | Task | Status | Verifier strategy |
| --- | --- | --- | --- | --- |
| oneMKL | `cblas_dgemm` (BLAS) | `onemkl-dgemm` | implemented | Signature (sum of `C=A*B`) vs serial triple-loop reference; runtime bound; source markers (`cblas_dgemm`, `mkl.h`) |
| oneMKL | DFTI FFT | `onemkl-fft` | implemented | Dominant-bin + magnitude-sum vs naive DFT reference, forward/backward round-trip error; source markers |
| oneDPL | `transform_reduce` + `par_unseq` | `onedpl-transform-reduce` | implemented | Sum-of-squares signature vs serial reference; runtime bound; source markers (`oneapi/dpl`, `transform_reduce`, `execution::par`) |
| IPP | `ippsDotProd_64f` | `ipp-dotprod` | implemented | Dot-product signature vs serial reference; source markers (`ippsDotProd_64f`, `ipp.h`) |
| sklearnex | `patch_sklearn()` + KNN | `sklearnex-classification` | implemented | Accuracy within 0.02 of stock scikit-learn reference; source markers (`sklearnex`, `patch_sklearn`) |

> A `oneccl-allreduce` task (multi-rank sum allreduce over MPI vs analytic
> `N*(N+1)/2`) was prototyped but pulled from the first batch: the oneCCL/Intel
> MPI transport needs iteration on a real image under `--network none`, which
> couldn't be done in the authoring sandbox. It is tracked as a candidate below.

## Intel performance skills

These tasks evaluate `intel/intel-performance-skills` as an agent capability:
the agent must interpret profile-like evidence, choose the right performance
pattern, apply a safe fix or produce a report, and pass deterministic verifier
checks. They intentionally avoid privileged `perf` in the first wave; static
profile artifacts are shipped in the task environment.

| Problem / concept | Task | Level | Status | Verifier strategy |
| --- | --- | --- | --- | --- |
| Serial accumulator / low IPC | `intel-perf-serial-accumulator` | diagnosis | implemented | Dot-product equality vs serial reference; speedup threshold; source marker for multiple partial accumulators |
| False sharing / HITM | `intel-perf-false-sharing` | diagnosis | implemented | Final counter total; speedup vs false-sharing baseline; source marker for cache-line separation |
| Shared statistics counter / true sharing | `intel-perf-shared-counter` | diagnosis | implemented | Exact total and checksum; speedup vs global atomic baseline; source marker for local aggregation |
| Missing C `restrict` / alias preamble | `intel-perf-missing-restrict` | diagnosis | implemented | Checksum equality; `restrict` source marker; compiler vectorization evidence |
| Hotspot report from perf artifacts | `intel-perf-hotspot-report` | end_to_end | implemented | Markdown structure checks; serial-accumulator and false-sharing observations; rejects fake fix claims |
| TAS spinlock cache-line bouncing | `intel-perf-ttas-spinlock` | diagnosis | implemented | Mutual exclusion (exact total at several thread counts); termination under high contention (no livelock); source marker for read-spin-before-exchange (TTAS) |
| Read-mostly mutex serializes readers | `intel-perf-mutex-rwlock` | diagnosis | implemented | Array checksum equals mutex reference (write path correct); termination under read load; source marker for `shared_mutex`/`shared_lock` |
| Condition-variable thundering herd | `intel-perf-cv-herd` | diagnosis | implemented | Exact job count + checksum at several worker counts; termination (no deadlock/lost wakeup); per-job path uses `notify_one`, not broadcast |
| Data-dependent branch / branch misprediction | `intel-perf-branch-mispredict` | diagnosis | implemented | Total equality vs branchy baseline; faster than the mispredicting baseline; source marker for a branchless/predicated summation (rejects the `if (...) total += ...` hot-loop branch) |
| Single-accumulator CRC32C | `intel-perf-crc32c` | diagnosis | implemented | CRC equality vs reference + known vector; >=4x throughput (measured ~14x); source marker for hardware CRC intrinsic + dispatch + scalar fallback |
| `std::sort` on primitives (stable not required) | `intel-perf-simd-sort` | diagnosis | implemented | Sortedness + same multiset signature vs reference; >=1.8x speedup (measured ~4x); rejects `std::sort` on the hot path |
| Dense-layer forward pass / serial reduction (source-first, proactive) | `intel-perf-dnn-dense` | end_to_end | implemented | Checksum equality vs serial reference within fp tolerance; >=1.8x speedup (measured ~4.5x); leaky-ReLU preserved; source marker for SIMD intrinsics or multiple partial accumulators |
| TTAS spinlock release-time CAS storm | `intel-perf-spinlock-backoff` | diagnosis | implemented | Mutual exclusion (exact total at several thread counts); termination under high contention (no livelock / uncapped backoff); source markers for read-spin + capped exponential backoff + pause/relax body |
| Lock-independent work inside critical section | `intel-perf-read-before-lock` | diagnosis | implemented | Result unchanged across thread counts; termination under high contention; source marker that the lock-independent computation is hoisted before lock acquisition (shared update still locked) |
| `make_shared` control block false-shared with payload | `intel-perf-false-sharing-shared-ptr` | diagnosis | implemented | Total unchanged across thread counts; termination within time limit; source marker that the contended object is not `make_shared` (control block separated / payload cache-line-aligned) |
| Redundant per-literal column materialization (memory-bound query) | `intel-perf-redundant-column` | end_to_end | implemented | Checksum equality vs serial reference; >=1.8x speedup (rewrite removes ~89/90 memory passes); source marker for `SUM(c)+k*COUNT(c)` closed form |

> Verifier-strategy note: the concurrency tasks (`ttas-spinlock`, `mutex-rwlock`,
> `cv-herd`) gate on **correctness + structural source markers + termination**
> rather than a wall-clock speedup threshold. Spinlock/lock fairness is highly
> machine- and contention-dependent (measured TAS-vs-TTAS wall-clock ratio swung
> 0.26–1.39 on a 224-core host pinned to 4 CPUs), so a tight speedup gate would
> be flaky in CI. The deterministic single-thread throughput tasks (`crc32c`,
> `simd-sort`) keep a conservative speedup gate well below the measured margin.

### Candidate tasks per component

| Component | Candidate task | Validation idea |
| --- | --- | --- |
| oneMKL | `onemkl-rng` | RNG stream with a fixed seed → exact reproducible sum/mean vs an independently computed reference |
| oneMKL | `onemkl-lapack` | Solve `Ax=b` with `LAPACKE_dgesv`, verify residual `‖Ax-b‖` is tiny |
| oneMKL | `onemkl-sparse` | Sparse mat-vec (`mkl_sparse_d_mv`) vs dense reference signature |
| oneDPL | `onedpl-sort` | `oneapi::dpl::sort` with a parallel policy; verify sortedness + multiset equality |
| oneDPL | `onedpl-scan` | `inclusive_scan` prefix signature vs serial reference |
| oneDNN | `onednn-relu` / `onednn-gemm` | Single primitive output vs a serial reference array, exact within fp tolerance |
| IPP | `ipp-image-resize` | `ippiResize` on a deterministic raster; verify pixel checksum vs a serial bilinear reference |
| IPP-CP | `ippcp-aes` | AES-128 encrypt→decrypt round-trip recovers plaintext; KAT vector match |
| oneCCL | `oneccl-allreduce` / `oneccl-allgather` / `oneccl-reduce` | Per-rank contributions vs analytic gathered/reduced result; needs MPI/oneCCL transport working under `--network none` (Intel MPI `shm` fabric, `CCL_ATL_TRANSPORT=mpi`) |
| sklearnex | `sklearnex-kmeans` / `sklearnex-pca` | Cluster inertia / explained-variance within tolerance of stock sklearn |
| OpenMP | `openmp-reduce` | `#pragma omp parallel for reduction` checksum vs serial (offline, stock `-fopenmp`) |
| oneDNN | `onednn-conv` | Small convolution vs a serial reference output tensor signature |

## dpnp

This matrix tracks which dpnp APIs and concepts are covered by terminal-bench-style coding tasks.

| API / concept | Task | Status | Verifier strategy |
| --- | --- | --- | --- |
| Drop-in `import dpnp as np`, `asnumpy()` fallback | `dpnp-migration-replace-numpy` | proposed | NumPy reference signature comparison, AST import check |
| `sum/mean/std` with `axis=0` | `dpnp-reduction-stats` | proposed | NumPy reference signature comparison, AST reduction check |
| `dpnp.matmul` / `@` operator, oneMKL backend | `dpnp-linalg-matmul` | proposed | NumPy reference signature comparison, AST matmul check |
| `dpnp.fft.fft`, power spectrum | `dpnp-fft-pipeline` | proposed | NumPy reference signature comparison, AST fft check |
| `dpctl` device introspection, GPU→CPU fallback | `dpnp-device-fallback` | proposed | NumPy reference signature comparison, dpctl import + GPU attempt check |

## Notes for new tasks

Prefer deterministic, small workloads that can be verified offline in CI. Each
task should have a serial reference or an independently computed expected result
so verifiers reject keyword-only implementations. Runtime thresholds should be
conservative enough to avoid flaky CI while still detecting obviously
inefficient or non-terminating solutions.

Validation patterns used across components:

1. **Serial reference signature** — ship a small serial program (built in the
   Dockerfile) that computes a deterministic scalar/array signature; the
   verifier runs both and compares within a tolerance. Used by every numeric
   task here.
2. **Analytic expected value** — when a serial reference is awkward (e.g.
   collectives), derive the answer in closed form (a `oneccl-allreduce` task
   would compare against `N*(N+1)/2`).
3. **Round-trip invariants** — forward/backward transforms (FFT) or
   encrypt/decrypt (crypto) must recover the input within tolerance.
4. **Drop-in reference** — for accelerator libraries (sklearnex), compare
   against the stock library it accelerates and require the result to match
   closely.
5. **Source API markers** — grep the agent's source for the required API
   symbols/headers so a hard-coded or keyword-only answer is rejected.

For components whose dependencies are large or only available via the Intel
oneAPI apt repo, add the task to the `terminal-bench-verify-oneapi` CI job and
build/verify/cleanup one image at a time to respect the runner disk budget.
