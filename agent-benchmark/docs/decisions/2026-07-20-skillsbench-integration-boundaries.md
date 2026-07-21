# ADR: SkillsBench integration and responsibility boundaries

**Status:** PROPOSED

**Date:** 2026-07-20

**Scope:** Integrate the public SkillsBench dataset with `agent-benchmark` without
forking its task catalog or duplicating its execution infrastructure.

## 1. Decision summary

Use SkillsBench as a versioned **external executable-task dataset** and use
`agent-benchmark` as the **experiment-control and analysis plane**.

The integration is an adapter, not a source import:

- SkillsBench owns public task packages, skills, taxonomy, oracle/verifier
  quality, dataset releases, and its public leaderboard.
- BenchFlow is the preferred execution provider for native SkillsBench tasks.
  Existing Harbor-compatible `agent-benchmark` harnesses remain available for
  local task suites and compatible external packages.
- `agent-benchmark` owns experiment matrices, treatment/plugin comparisons,
  paired-run validation, normalized result artifacts, statistics, Intel-private
  suites, and cross-dataset scorecards.
- `agent-benchmark` references a SkillsBench release and verifies task digests;
  it does not copy the 87-task roster into this repository.
- Improvements to the public package contract or result interchange should be
  proposed upstream before introducing a divergent local format.

Forking SkillsBench is a fallback only when an essential, generally useful
change is rejected upstream and cannot be implemented in an adapter.

## 2. Why integrate instead of absorb

SkillsBench v1.1 already supplies the difficult dataset-governance layer:

- 87 active native task packages and 14 excluded packages;
- `task.md`, `environment/`, `environment/skills/`, `oracle/`, and `verifier/`;
- controlled taxonomy and task-review rules;
- paired `with-skill` / `no-skill` evaluation guidance;
- release registry entries with per-task content digests;
- oracle, trajectory, and human-review expectations.

`agent-benchmark` already supplies a different set of capabilities:

- explicit `(model, harness, plugin_set)` cells;
- baseline and N-way treatment arms;
- plugin deltas and no-cross-cell comparison guards;
- `task_runs.v1`, matrix rollups, subject scorecards, and dataset export;
- paired significance/effect-size analysis for answer-quality experiments;
- static documentation, LLM Q&A, and executable-task tracks in one project.

Copying SkillsBench tasks would create two authorities for task fixes, digests,
licenses, and verifier behavior. Replacing `agent-benchmark` with SkillsBench
would discard the broader experiment and analysis model. A narrow adapter keeps
one owner for each concern.

## 3. Layered architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│ 8. Publication and decision layer                                   │
│ agent-benchmark scorecards/reports · SkillsBench public leaderboard  │
├──────────────────────────────────────────────────────────────────────┤
│ 7. Analysis layer — agent-benchmark                                 │
│ paired deltas · CIs/tests/effect sizes · slice analysis · gates      │
├──────────────────────────────────────────────────────────────────────┤
│ 6. Normalized result layer — agent-benchmark                        │
│ task_runs artifact · provenance · trajectories/log references        │
├──────────────────────────────────────────────────────────────────────┤
│ 5. Experiment-control layer — agent-benchmark                       │
│ cells · repetitions · skill mode · plugins · pairing · retry policy  │
├──────────────────────────────────────────────────────────────────────┤
│ 4. Execution-provider layer                                         │
│ BenchFlow for native SkillsBench · Harbor/local adapters where valid │
├──────────────────────────────────────────────────────────────────────┤
│ 3. Dataset adapter and cache — agent-benchmark                       │
│ resolve release · verify digest · expose TaskRef · license inventory │
├──────────────────────────────────────────────────────────────────────┤
│ 2. Task-package contract — SkillsBench                              │
│ task.md · environment · skills · oracle · verifier                   │
├──────────────────────────────────────────────────────────────────────┤
│ 1. Dataset governance — SkillsBench                                 │
│ taxonomy · reviews · registry · releases · exclusions                │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.1 Dataset-governance layer

SkillsBench remains the source of truth for public SkillsBench membership.
`tasks-extra/` is not silently added to a run: excluded or credential-dependent
packages require an explicit opt-in policy.

A dataset reference is immutable after resolution:

```yaml
dataset:
  provider: skillsbench
  name: skillsbench
  version: "1.1"
  registry_url: https://raw.githubusercontent.com/benchflow-ai/skillsbench/v1.1/registry.json
  release_ref: v1.1
  expected_registry_digest: sha256:<digest>
```

The adapter records both the user-facing release and the concrete registry/task
identities. A tag alone is not sufficient provenance.

### 3.2 Task-package layer

The adapter consumes native packages without rewriting them:

```text
tasks/<task-id>/
├── task.md
├── environment/
│   ├── Dockerfile
│   ├── skills/
│   └── bundled inputs
├── oracle/solve.sh
└── verifier/
```

`agent-benchmark` must not edit cached packages in place. Local experiments that
modify a task become a separate development dataset with a new digest and must
not be reported as official `skillsbench@<version>` results.

### 3.3 Dataset-adapter layer

Introduce a provider-neutral dataset boundary conceptually equivalent to:

```python
class TaskDatasetAdapter(Protocol):
    def resolve(self, dataset_ref: DatasetRef) -> ResolvedDataset: ...
    def list_tasks(self, resolved: ResolvedDataset) -> list[TaskRef]: ...
    def materialize(self, task: TaskRef, cache_dir: Path) -> Path: ...
    def verify(self, task: TaskRef, path: Path) -> VerificationResult: ...
```

A `TaskRef` contains at minimum:

```json
{
  "dataset_name": "skillsbench",
  "dataset_version": "1.1",
  "task_id": "3d-scan-calc",
  "source_url": "https://github.com/benchflow-ai/skillsbench.git",
  "source_commit": "<registry commit>",
  "source_path": "tasks/3d-scan-calc",
  "task_digest": "sha256:...",
  "license": "Apache-2.0"
}
```

Adapter responsibilities:

1. Resolve an explicit dataset version; never default silently to a moving
   branch.
2. Cache content by digest, not only by task name.
3. Verify every materialized task before execution.
4. Preserve upstream license, notices, and source attribution.
5. Inventory task-level external data/assets and flag unknown or incompatible
   terms.
6. Expose upstream metadata without translating away unknown fields.
7. Fail closed on digest mismatch.

### 3.4 Execution-provider layer

Task resolution and task execution are separate interfaces. The initial
SkillsBench provider invokes the BenchFlow version range declared by the
resolved dataset. It passes native package paths and explicit skill mode:

```text
with-skill: task environment + declared task skills
no-skill:   identical task/environment, no task-skill injection
oracle:     held-out oracle sanity run, never a benchmark model result
```

The provider returns raw run metadata, verifier reward, logs, trajectories, and
artifact locations. It does not compute cross-run deltas.

Existing `agent-benchmark` Harbor aliases continue to execute compatible local
or external tasks. A run must record its actual provider and provider version;
results produced by BenchFlow and Harbor are different harness cells unless
compatibility has been demonstrated.

### 3.5 Experiment-control layer

The experiment controller expands an explicit matrix. For SkillsBench the
minimum cell key is:

```text
dataset_version × task_digest × model × harness × harness_version
× skill_mode × plugin_set × generation_config × repetition
```

Example descriptor:

```yaml
suite:
  dataset: skillsbench@1.1
  tasks:
    include: [3d-scan-calc, citation-check]
  verify_digests: true

matrix:
  cells:
    - id: codex-without-skills
      model: <model-id>
      harness: benchflow:codex
      skill_mode: no-skill
      plugins: []
    - id: codex-with-skills
      model: <model-id>
      harness: benchflow:codex
      skill_mode: with-skill
      plugins: []

run:
  repetitions: 3
  order: randomized-pairs
  retry_policy: infrastructure-only
```

Pairing rules:

- `skill_delta` changes only `skill_mode`.
- `plugin_delta` changes only `plugin_set`.
- `harness_delta` changes only `harness`, and is labelled observational unless
  harness semantics are known to be equivalent.
- No delta is valid across dataset versions or task digests.
- Temperature, tool policy, timeout, network policy, retry policy, and skill
  discovery/nudge behavior must match inside a pair.
- Pairs should be interleaved or randomized to reduce provider-time and cache
  bias.

Retries are only for classified infrastructure failures. Retrying verifier or
agent failures until success would bias pass rates.

### 3.6 Normalized-result layer

Extend the executable-task artifact model rather than storing a second
SkillsBench-only report shape. Each normalized row should include:

```json
{
  "dataset": {
    "name": "skillsbench",
    "version": "1.1",
    "registry_digest": "sha256:..."
  },
  "task": {
    "id": "3d-scan-calc",
    "digest": "sha256:...",
    "source_commit": "..."
  },
  "cell": {
    "model": "...",
    "harness": "benchflow:codex",
    "harness_version": "...",
    "skill_mode": "with-skill",
    "plugin_set": "none",
    "repetition": 1
  },
  "outcome": {
    "reward": 1.0,
    "passed": true,
    "status": "completed"
  },
  "telemetry": {
    "elapsed_sec": 0.0,
    "tokens": {},
    "cost_usd": null,
    "tool_calls": null
  },
  "artifacts": {
    "trajectory": "...",
    "verifier_log": "...",
    "output_manifest": "..."
  },
  "failure": null
}
```

Raw upstream results remain attached or referenced for audit. Normalization is
lossless: unknown provider fields go into a namespaced extension block.

Use a failure taxonomy that does not convert infrastructure faults into model
failures:

| Class | Examples | Included in task pass rate? |
| --- | --- | --- |
| `agent_failure` | timeout after valid start, invalid output | yes |
| `verifier_failure` | completed output fails checks | yes |
| `infrastructure_failure` | image pull outage, provider unavailable | no; report separately |
| `dataset_failure` | digest mismatch, broken oracle/package | no; block dataset cell |
| `configuration_failure` | unsupported model/harness/skill mode | no; fail before run |

### 3.7 Analysis layer

The primary SkillsBench analysis is paired skill lift:

```text
skill_lift(task, repetition, cell)
  = reward(with-skill) - reward(no-skill)
```

Reports should include:

- with-skill and no-skill pass rates;
- absolute and normalized skill lift;
- paired confidence interval and matched-pair test appropriate for binary
  outcomes;
- run count, complete-pair count, and missing-pair reasons;
- slices by SkillsBench taxonomy, model, harness, and skill type;
- task-level wins, losses, and unchanged outcomes;
- infrastructure-failure rate separately from pass rate;
- plugin/skill interaction only when a fully paired factorial design exists;
- graded reward summaries when a verifier emits continuous reward.

For binary paired outcomes, McNemar's test or a paired bootstrap over tasks is
more appropriate than applying an unpaired proportion test. Existing paired
`t`/Wilcoxon/Cohen's-d reporting remains useful for continuous judge scores but
must not be reused mechanically for binary task outcomes.

### 3.8 Publication layer

There are two publication products with different authority:

- SkillsBench decides what qualifies for the official SkillsBench leaderboard.
- `agent-benchmark` publishes experiment reports and scorecards, clearly marked
  as official-dataset or modified/local runs.

An `agent-benchmark` report must not imply official leaderboard status merely
because it used an official task release. Submission to the upstream leaderboard
is a separate export/validation step.

## 4. Ownership and contribution matrix

| Concern | Primary owner | `agent-benchmark` responsibility | Upstream contribution trigger |
| --- | --- | --- | --- |
| Public task roster | SkillsBench | consume pinned release | new generally useful public task |
| Task taxonomy | SkillsBench | preserve and slice by it | missing reusable category/field |
| Oracle/verifier correctness | SkillsBench | preflight and report failures | public task defect or improved verifier |
| Task packaging | SkillsBench/BenchFlow contract | adapter only | generally useful format change |
| Sandbox execution | BenchFlow; Harbor for compatible paths | provider adapters and provenance | runner bug or portable result field |
| Experiment matrix | `agent-benchmark` | own | only propose portable interchange fields |
| Treatment/plugin deltas | `agent-benchmark` | own | upstream if leaderboard needs them |
| Statistical analysis | `agent-benchmark` | own | contribute generic paired-result export |
| Official leaderboard | SkillsBench | export eligible runs | schema/submission improvements |
| Intel-private tasks/data | Intel/`agent-benchmark` | own and isolate | never upstream confidential material |
| License/provenance audit | shared | enforce at import and report time | upstream metadata gaps |

## 5. Public, private, and fork modes

### Public integration mode — default

Consume official SkillsBench releases, submit generally useful fixes upstream,
and keep only adapter/config/result code locally.

### Private extension mode

Use the same package contract for Intel-confidential tasks in a separate,
access-controlled dataset registry. Do not place private tasks, trajectories,
prompts, or outputs in the public SkillsBench cache or result export.

### Vendor/fork mode — exception

A fork is justified only when all are true:

1. the capability is required, not merely convenient;
2. it cannot be implemented losslessly in the adapter;
3. an upstream design discussion has been attempted;
4. upstream rejects or cannot schedule the change;
5. we can maintain rebases, security fixes, attribution, and divergence tests.

The fork retains Apache-2.0 attribution and a machine-readable record of
upstream commit, local patches, and synchronization status.

## 6. Security, licensing, and data handling

- Treat task packages, Dockerfiles, skills, scripts, and verifier code as
  untrusted third-party code.
- Build and run in isolated sandboxes with least privilege, bounded CPU/memory,
  explicit network policy, and no ambient Intel credentials.
- `no-skill` must remove only the treatment under test; it must not change the
  base image, input files, timeout, or tool permissions.
- Keep oracle content hidden from the evaluated agent.
- Preserve the SkillsBench Apache-2.0 license and notices in cached or vendored
  copies.
- Audit licenses and terms for bundled third-party datasets, models, fonts,
  media, and other task assets; the repository-level license does not
  automatically cure incompatible upstream asset terms.
- Scrub trajectories and artifacts before public export; they may contain
  secrets, personal data, provider identifiers, or proprietary code.

## 7. Proposed implementation phases

### Phase 0 — upstream alignment

1. Open a SkillsBench design discussion describing the adapter and ownership
   boundary.
2. Ask which result fields are stable and which submission path qualifies for
   the official leaderboard.
3. Propose portable fields: dataset/task digest, actual runner version, skill
   mode, failure classification, trajectory/verifier references, and graded
   reward.

**Exit:** written agreement on the first interchange boundary, or documented
reason to proceed adapter-only.

### Phase 1 — read-only dataset adapter

1. Add `DatasetRef`, `ResolvedDataset`, `TaskRef`, and adapter interfaces.
2. Implement SkillsBench registry resolution and digest-verified cache.
3. Add list/inspect/preflight commands; no model execution yet.
4. Generate a license/provenance inventory.

**Exit:** the 87 active v1.1 tasks resolve reproducibly and digest mismatches
fail closed.

### Phase 2 — execution and normalization

1. Add a BenchFlow execution provider pinned to the dataset-supported version.
2. Run oracle preflight on a small representative subset.
3. Run one model/harness with explicit `with-skill` and `no-skill` cells.
4. Normalize outputs into an additive successor to `task_runs.v1` while
   retaining raw provider artifacts.
5. Add failure classification and retry guards.

**Exit:** repeated local runs produce complete, auditable pairs.

### Phase 3 — paired analysis

1. Add skill-lift aggregation, confidence intervals, paired binary tests, and
   taxonomy slices.
2. Reject invalid cross-version, cross-digest, or cross-harness deltas.
3. Surface missing pairs and infrastructure failures.
4. Integrate executable results into subject scorecards.

**Exit:** a report can support or reject a claim that a skill helped under one
fixed model/harness configuration.

### Phase 4 — upstream interchange

1. Contribute the smallest generally useful result-schema/export change.
2. Validate export/import round trips against upstream examples.
3. Submit eligible runs only through the upstream-approved path.
4. Upstream public task/verifier fixes; keep Intel-private suites separate.

**Exit:** no manual spreadsheet conversion is needed between the projects.

## 8. Validation gates

The integration is not complete until these gates pass:

- **Provenance:** dataset version, registry digest, task digest, source commit,
  runner version, model, harness, skill mode, and plugin set are present.
- **Package integrity:** modified cache content is detected before execution.
- **Oracle:** selected official tasks pass oracle preflight in the chosen
  provider.
- **Isolation:** evaluated agents cannot read oracle files or host credentials.
- **Pairing:** changing any held-constant field invalidates the skill delta.
- **Failure accounting:** injected infrastructure failures are excluded and
  reported, not scored as model failures.
- **Round trip:** normalized rows retain links to raw trajectory, verifier log,
  and outputs.
- **Statistics:** synthetic paired outcomes produce expected lift, confidence
  interval, and matched-pair test results.
- **License:** every cached task has source and license inventory records.

## 9. Upstream contribution sequence

Prefer small contributions that benefit both ecosystems:

1. Open a design discussion; do not lead with a large code dump.
2. Add or document a stable machine-readable result export.
3. Add explicit dataset/task digest and actual runner-version fields.
4. Add failure classification and graded-reward semantics without breaking
   binary rewards.
5. Contribute public Intel performance tasks only when their inputs, licenses,
   and expected outputs are fully publishable.

Authorship, review, and task-quality policy remain SkillsBench decisions.
`agent-benchmark` should not attempt to redefine them downstream.

## 10. Non-goals

- Mirroring all SkillsBench tasks into `terminal-bench-tasks/`.
- Replacing BenchFlow or the SkillsBench leaderboard.
- Claiming Harbor and BenchFlow runs are equivalent by default.
- Publishing Intel-confidential tasks or trajectories.
- Treating skill injection as a plugin delta; `skill_mode` and `plugin_set` are
  separate factors.
- Using an LLM judge when a deterministic outcome verifier is authoritative.

## 11. Open questions

1. Which SkillsBench result schema and submission API are considered stable for
   v1.1 consumers?
2. Should `task_runs.v1` be extended additively or replaced by `task_runs.v2`
   for dataset and artifact provenance?
3. Which exact BenchFlow version is resolved from each registry entry when the
   registry and release documentation differ?
4. How should partial verifier rewards be aggregated across tasks with
   different reward granularity?
5. Which trajectory fields may be redistributed under model-provider and task
   asset terms?
6. Can one official run be accepted when orchestrated externally but executed
   through the upstream-approved BenchFlow provider?

## 12. Source basis

This decision was checked against SkillsBench tag `v1.1` (`b63b7b2`) and its
`README.md`, `CONTRIBUTING.md`, `MAINTAINER.md`, `registry.json`, and
`docs/dataset-versioning.md`. The repository declares Apache-2.0. The v1.1
release contains 87 active task directories and 14 `tasks-extra` directories.

Local integration points were checked against:

- `agent_benchmarks/harnesses/` and `commands/tasks.py`;
- `agent_benchmarks/schemas/task_runs.v1.json`;
- `agent_benchmarks/eval/cells.py` and `eval/plugin_delta.py`;
- `agent_benchmarks/subjects/scorecard.py`;
- [Coding Harnesses And Task Runs](../coding-harnesses.md);
- [Plugin and harness-aware benchmark dimensions](2026-06-11-plugin-and-harness-aware-benchmarks.md).
