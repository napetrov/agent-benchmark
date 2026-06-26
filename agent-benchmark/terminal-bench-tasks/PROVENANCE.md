# Provenance notes for executable tasks

## oneTBB (ParRes-inspired)

The `onetbb-nstream`, `onetbb-stencil`, and `onetbb-transpose` tasks are inspired by the Parallel Research Kernels project:

- Repository: https://github.com/ParRes/Kernels
- Upstream kernels consulted: `Cxx11/nstream-tbb.cc`, `Cxx11/stencil-tbb.cc`, and `Cxx11/transpose-tbb.cc`
- Upstream license: BSD-style Intel Corporation license in `COPYING`

The task implementations in this repository are simplified, independently written exercises for terminal-bench-style validation. They do not copy the ParRes source files verbatim and should not be reported as official ParRes or STREAM benchmark results. The purpose here is functional verification of oneTBB usage by coding agents, not system benchmarking.

## oneMKL, oneDPL, IPP, sklearnex

The `onemkl-*`, `onedpl-*`, `ipp-*`, and `sklearnex-*` tasks are original
exercises written for this repository. Their environments pull dependencies at
**build** time only; the verifier runs offline:

- oneMKL and IPP are installed from the Intel oneAPI apt repository
  (`https://apt.repos.intel.com/oneapi`).
- oneDPL is header-only and is fetched from the upstream repository
  ([uxlfoundation/oneDPL](https://github.com/uxlfoundation/oneDPL)) at a pinned
  release tag; it uses the oneTBB backend (`libtbb-dev`).
- sklearnex is installed from PyPI (`scikit-learn-intelex`) alongside
  `scikit-learn`.

The `sklearnex-classification` task is a generic, self-contained tabular
classification workflow in the spirit of common Kaggle starter notebooks
(synthetic `make_classification` data, a train/test split, and a KNN
classifier). It is not derived from or copied out of any specific Kaggle
notebook or dataset.

## intel-performance-skills tasks (linux-perf / vector-sequential)

The `intel-perf-*` tasks are original exercises written for this repository to
evaluate the `intel/intel-performance-skills` capability. They ship a small
deterministic serial reference (built in the Dockerfile) and gate on
correctness plus, where the workload is a deterministic single-thread
throughput case, a conservative speedup threshold; see
`docs/difficulty-rubric.md` for the level/difficulty/trigger tagging.

The `intel-perf-dnn-dense` task is a source-first / proactive exercise: a
single-accumulator dense-layer (fully connected) forward pass with a leaky-ReLU
activation that the agent must rewrite using parallel accumulators or SIMD. Its
design is informed by the skill's own `rules/vector-sequential.md` optimization
ladder (C parallel accumulators → SIMD intrinsics in an unrolled loop) and by a
publicly observed real-world application of the skill, the open-source
`fenrus75/turbostar2` project, where loading the skill led an agent to optimize
a dense-layer loop with parallel accumulators and then an SSE variant
(commits `646c8ac` and `080ae56`). The task source here is independently
written for offline verification and does not copy turbostar2 or the skill
example files verbatim; inputs are formula-driven (no RNG) so the result is
bit-reproducible across builds.

