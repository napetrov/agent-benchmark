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

```text
class TaskDatasetAdapter(Protocol):
    def resolve(self, dataset_ref: DatasetRef) -> ResolvedDataset: ...
    def list_tasks(self, resolved: ResolvedDataset) -> list[TaskRef]: ...
    def materialize_verified(
        self, task: TaskRef, cache_dir: Path
    ) -> VerifiedTaskPackage: ...
```

`VerifiedTaskPackage` is an immutable, content-addressed handle, not a writable
path. Materialization, digest verification, and publication into the cache are
one atomic operation. Execution providers accept only this handle. The cache
uses per-digest locking and read-only snapshots so content cannot change
between verification and execution.

A `TaskRef` contains at minimum:

```json
{
  "dataset_name": "skillsbench",
  "dataset_version": "1.1",
  "task_id": "3d-scan-calc",
  "source_url": "https://github.com/benchflow-ai/skillsbench.git",
  "registry_commit": "<registry commit>",
  "task_source_commit": "<task source commit>",
  "source_path": "tasks/3d-scan-calc",
  "task_digest": "sha256:...",
  "license_expression": "Apache-2.0",
  "asset_inventory": []
}
```

Each asset-inventory entry records source, checksum, SPDX expression or terms,
redistribution status, and an explanation when status is unknown. Submodules,
LFS objects, downloaded build inputs, and external registries contribute to the
resolved identity rather than inheriting the repository license implicitly.

Adapter responsibilities:

1. Resolve an explicit dataset version; never default silently to a moving
   branch.
2. Resolve the release tag to a commit, verify the registry byte digest, and
   cache content by digest rather than task name.
3. Atomically verify every materialized task and expose only an immutable
   verified handle to execution providers.
4. Preserve upstream license, notices, and source attribution.
5. Inventory task-level external data/assets and flag unknown or incompatible
   terms.
6. Expose upstream metadata without translating away unknown fields.
7. Fail closed on digest mismatch or an unpinned transitive input.

### 3.4 Execution-provider layer

Task resolution and task execution are separate interfaces. A versioned
integration lock maps each dataset registry digest to one exact BenchFlow
version and image digest. Resolution loads that lock entry and validates that
the exact version satisfies the dataset-declared compatibility range; there is
no runtime "latest compatible" selection. The resolved version and image digest
are recorded in the run descriptor, and every arm in a pair uses that same
runner. The provider boundary is conceptually equivalent to:

```text
class TaskExecutionProvider(Protocol):
    def capabilities(self) -> ProviderCapabilities: ...
    def execute(
        self, request: ExecutionRequest, task: VerifiedTaskPackage
    ) -> ProviderResult: ...
```

The typed request includes provider and harness identity, exact versions,
timeout/cancellation, treatment view, network/tool policy, and output-schema
version. The result includes raw-schema version, evidence-backed failure
classification, and immutable artifact references.

The provider creates separate trusted-runner and untrusted-agent views. The
agent view contains task inputs and the permitted environment but never oracle
or verifier files. The trusted runner alone mounts oracle/verifier content.
Skill mode controls a declarative execution view:

```text
with-skill: declared task skills visible through the specified delivery path
no-skill:   task skills absent from every agent-visible path and discovery API
oracle:     held-out oracle sanity run, never a benchmark model result
```

The benchmark views have identical base image digest, inputs, prompt template,
tool permissions, timeout, network policy, and writable-cache state. Only the
declared skill delivery differs. Skill files, prompts, environment variables,
discovery/nudge APIs, inherited caches, and tool-mediated paths are part of the
treatment boundary. A conformance test must prove that a no-skill agent cannot
enumerate or read task skills and that neither arm can access the oracle.

The provider returns raw run metadata, verifier reward, logs, trajectories, and
artifact references. It does not compute cross-run deltas.

Existing `agent-benchmark` Harbor aliases continue to execute compatible local
or external tasks. A run records execution provider/version/image digest
separately from agent harness/version. BenchFlow and Harbor results are
different provider cells unless compatibility is demonstrated by a conformance
suite covering prompts, tools, timeout accounting, skill delivery, output
normalization, and verifier inputs.

### 3.5 Experiment-control layer

The experiment controller expands an explicit matrix. A canonical `cell_id` is
the digest of all resolved outcome-relevant fields:

```text
dataset_provider/name/version × registry_digest × task_digest
× execution_provider/version/image_digest × harness/version
× model_provider/snapshot × skill_mode × skill_artifact_digest
× canonical_plugin_set_id × generation_config × prompt_template_digest
× tool/timeout/network/retry/discovery_policy_digests × repetition_seed
```

Human-readable aliases are labels only. Mutable model, plugin, skill, image, or
policy names are resolved to versions or content digests before scheduling.
Randomization order and every attempt are recorded, but attempt number is not a
new estimand.

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
      model: <model-snapshot>
      execution_provider: benchflow@<exact-version>
      harness: codex@<exact-version>
      skill_mode: no-skill
      plugins: []
    - id: codex-with-skills
      model: <model-snapshot>
      execution_provider: benchflow@<exact-version>
      harness: codex@<exact-version>
      skill_mode: with-skill
      plugins: []

run:
  repetitions: 3
  seed: <seed>
  order: randomized-pairs
  retry_policy:
    class: infrastructure-only
    max_attempts: 2
    backoff_sec: 30
```

Pairing rules:

- `skill_delta` changes only `skill_mode`.
- `plugin_delta` changes only `plugin_set`.
- `harness_delta` changes only `harness`, and is labelled observational unless
  the compatibility conformance suite passes.
- No delta is valid across dataset versions or task digests.
- Temperature, tool policy, timeout, network policy, retry policy, and skill
  discovery/nudge behavior must match inside a pair.
- Pair order is randomized from a recorded seed and interleaved to reduce
  provider-time and cache bias.

For skill analysis, define a matched block by the complete canonical key with
`skill_mode` removed; the two skill modes are arms within that block, not one
cell. `skill_artifact_digest` identifies the assigned treatment package in both
arms and does not imply that it is visible in the no-skill arm. The pairing unit
is `task_digest × repetition_seed`. Repetitions share a task and are never
analysed as independent tasks. The primary estimand is the equal-weighted mean
task effect over the fixed released task set; inference to a broader task
population is a separate exploratory estimand.

Retries are only for failures classified as infrastructure failures from
provider evidence. The policy fixes maximum attempts and backoff before the
run, retains every attempt, and reruns both arms when a pair-level outage could
affect either arm. Agent/verifier failures are never retried to obtain success.
One-arm exclusions are reported by arm and receive complete-case sensitivity
bounds; they are not silently treated as missing at random.

### 3.6 Normalized-result layer

Introduce `task_runs.v2` rather than a SkillsBench-only report or a structurally
incompatible extension of `task_runs.v1`. Provide a deterministic v1-to-v2
upgrader and retain a v1 compatibility reader. V2 readers preserve unknown
fields. Each normalized row includes at minimum:

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
    "registry_commit": "...",
    "task_source_commit": "..."
  },
  "cell": {
    "cell_id": "sha256:...",
    "model_provider": "...",
    "model_snapshot": "...",
    "execution_provider": "benchflow",
    "execution_provider_version": "...",
    "execution_image_digest": "sha256:...",
    "harness": "codex",
    "harness_version": "...",
    "skill_mode": "with-skill",
    "skill_artifact_digest": "sha256:...",
    "plugin_set_id": "sha256:...",
    "repetition_seed": "..."
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
  "artifacts": [],
  "failure": null,
  "extensions": {
    "org.benchflow.task-run/v1": {}
  }
}
```

Every artifact reference records content digest, media type, byte size, storage
URI, retention/access class, encryption state, redaction status, and
public-export eligibility. Raw upstream results remain attached or referenced
for audit. Normalization preserves the raw artifact byte-for-byte and maps
known fields without claiming semantic losslessness. Unknown provider fields
go under the fixed top-level `extensions` object. Keys use a reverse-DNS owner
plus schema name/version (`<owner>.<project>.<schema>/v<integer>`), and values
are provider-native JSON objects. Extension keys cannot shadow core fields;
duplicate keys are invalid; incompatible changes require a new versioned key.
Adapters preserve unrecognized extension entries byte-for-byte in the attached
raw artifact and structurally unchanged when reading and rewriting V2 JSON.

Use a failure taxonomy that does not convert infrastructure faults into model
failures:

| Class | Examples | Included in task pass rate? |
| --- | --- | --- |
| `agent_failure` | timeout after valid start, invalid output | yes |
| `verifier_failure` | valid verifier rejects completed output | yes |
| `verifier_error` | trusted verifier crashes or emits an invalid result | no; block affected cell |
| `infrastructure_failure` | image pull outage, provider unavailable | no; report separately |
| `dataset_failure` | digest mismatch, broken oracle/package | no; block dataset cell |
| `configuration_failure` | unsupported model/harness/skill mode | no; fail before run |
| `unknown_failure` | insufficient evidence or conflicting signals | no; quarantine for adjudication |

Classification uses authoritative typed runner signals with this precedence:
`configuration_failure` -> `dataset_failure` -> `verifier_error` ->
`infrastructure_failure` -> `agent_failure` -> `verifier_failure`. A task
output that the verifier validly rejects remains `verifier_failure`, even if the
agent also emitted an error. Conflicting signals at the same precedence or
untyped signals become `unknown_failure`; exception text alone never overrides
a typed signal. The normalized row stores the classifier version, selected
signal, all conflicting signals, and diagnostic evidence.

Only `infrastructure_failure` is retry-eligible, and only under the bounded
pair-level retry policy. `agent_failure` and `verifier_failure` count in task
pass-rate denominators and are never retried for success. `configuration_failure`,
`dataset_failure`, `verifier_error`, and `unknown_failure` are excluded from pass
rates and block or quarantine the affected cell. This mapping and precedence
are shared by execution, retry accounting, normalization, and validation
fixtures.

### 3.7 Analysis layer

The primary endpoint is absolute reward lift from enabling task skills under
one fixed model/harness/provider configuration. For binary verifiers this is
percentage-point pass-rate lift. Define matched block `b` as the canonical
cell key with `skill_mode` removed:

```text
skill_lift(task, repetition_seed, block)
  = reward(with-skill) - reward(no-skill)
```

First average valid repetitions within each task, then macro-average tasks so
tasks with more completed attempts do not receive greater weight. The primary
report targets the fixed released task set and reports the point estimate
regardless of significance. Conditional uncertainty from generation/runtime
randomness uses a paired bootstrap of repetition seeds within each fixed task;
with only three repetitions it is descriptive and cannot support a confirmatory
claim. A pre-run power/simulation plan sets the required repetition count.
Exploratory generalization beyond the released tasks may use a task-cluster
bootstrap but is labelled as a different estimand.

A confirmatory claim that a skill helped requires positive lift, a two-sided
95% confidence interval excluding zero, the predeclared missingness gate, the
predeclared minimum effect, and the planned repetition count. The run manifest
fixes the minimum effect, repetition policy, and maximum tolerated one-arm
missingness before execution.

Reports include:

- with-skill and no-skill pass rates;
- absolute skill lift as the primary measure; any normalized lift only with a
  declared formula and zero/one-baseline behavior;
- paired confidence interval and matched-pair test appropriate for the declared
  analysis unit;
- scheduled pairs, attempts, completed arms, complete pairs, one-arm and
  two-arm failures, retries, and missingness by arm/stage/task;
- best/worst-case sensitivity bounds for excluded one-arm outcomes;
- slices by SkillsBench taxonomy, model, harness, and skill type, labelled
  exploratory with sample size unless multiplicity correction was predeclared;
- task-level wins, losses, and unchanged outcomes;
- infrastructure-failure rate separately from pass rate;
- plugin/skill interaction only when a fully paired factorial design exists;
- graded reward summaries only when score direction, range, threshold, and
  cross-task comparability are defined by the verifier contract.

McNemar's test may describe one predeclared binary summary per task; repeated
task trials must not be entered as independent observations. For the fixed-task
estimand, repeated trials use paired within-task resampling. A task-cluster
bootstrap applies only to the separately labelled task-population estimand.
Continuous-outcome tests operate on task-level paired differences and declare
their assumptions and exact effect size; paired `t`, Wilcoxon, and Cohen's d
are not interchangeable defaults.

For graded wins/losses, predeclare an unchanged tolerance. Pass thresholds come
from the verifier, never from observed results. A plugin/skill interaction uses
the difference of differences across all four matched arms and is reported only
when all four share seed, task, policies, and missingness rules.

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

- Treat task packages, Dockerfiles, skills, scripts, dependencies, build inputs,
  oracle code, and verifier code as untrusted third-party code.
- Build and run in disposable rootless sandboxes with dropped Linux
  capabilities, `no-new-privileges`, read-only host and cache mounts, bounded
  CPU/memory/PIDs/disk/time, and no Docker socket or privileged device access.
- Deny network by default during build and run. Any allowlist is declared per
  task, resolved before execution, logged, and identical inside a pair. Builds
  use pinned base-image digests and locked dependencies; generated images are
  scanned and recorded by digest before execution.
- Run with a minimal allowlisted environment and short-lived scoped secrets
  only when a task explicitly requires them. Never expose ambient Intel, cloud,
  source-control, model-provider, SSH-agent, or host credentials.
- `no-skill` removes the treatment from all agent-visible channels while
  preserving the declared base environment and policies. Negative conformance
  tests cover filesystem, prompts, discovery APIs, environment variables,
  caches, and tool-mediated access.
- Keep oracle and verifier material in a trusted-runner-only mount or service.
  The evaluated agent cannot infer their paths, read them directly, or receive
  verifier diagnostics during the attempt. Oracle preflight uses a separately
  labelled trusted execution mode.
- Verify the release tag's resolved commit, registry bytes, task bytes,
  container images, dependencies, submodules/LFS objects, and downloaded assets
  against pinned digests. Cache publication is atomic; cache entries are
  immutable and reverified at execution handoff.
- Preserve the SkillsBench Apache-2.0 license, copyright, attribution, and any
  upstream `NOTICE` material in cached or vendored copies. Generate an SPDX
  expression and per-asset inventory rather than assigning repository-level
  Apache-2.0 to every bundled asset.
- Unknown, non-redistributable, or incompatible asset terms block public cache
  distribution and public artifact export. Internal execution requires a
  recorded policy decision and access classification.
- Store artifacts with digest, owner, access class, encryption, retention, and
  deletion policy. Private Intel registries, caches, encryption keys, object
  namespaces, and IAM are separate from public SkillsBench resources.
- Public export is allowlist-based, not merely scrub-based. Automated secret,
  PII, path, provider-ID, and proprietary-code scanning precedes human approval;
  derived reports inherit the most restrictive source classification. Raw
  public URLs are emitted only for artifacts explicitly marked exportable.

## 7. Proposed implementation phases

### Phase 0 — upstream alignment

1. Open a SkillsBench design discussion describing the adapter and ownership
   boundary.
2. Ask which result fields are stable and which submission path qualifies for
   the official leaderboard.
3. Propose portable fields: dataset/task digest, actual runner version, skill
   mode, failure classification, trajectory/verifier references, and graded
   reward.

**Exit:** an upstream issue records the proposed boundary and an explicit
response, or a time-boxed no-response/rejection decision records assumptions,
owner, review date, and adapter-only fallback. Phase 0 does not block the local
read-only prototype, but official-eligibility claims remain disabled.

### Phase 1 — read-only dataset adapter

1. Add `DatasetRef`, `ResolvedDataset`, `TaskRef`, and adapter interfaces.
2. Implement SkillsBench registry resolution and digest-verified cache.
3. Add list/inspect/preflight commands; no model execution yet.
4. Generate a license/provenance inventory.

**Exit:** all expected active v1.1 registry entries resolve from a fresh cache;
each release tag resolves to a recorded commit; registry, task, transitive
input, image, and asset digests verify; unknown/unpinned inputs fail closed; the
license inventory is complete or explicitly blocks redistribution.

### Phase 2 — execution and normalization

1. Resolve the dataset-supported BenchFlow range to one exact runner version
   and image digest; pin both for the run.
2. Implement the typed provider contract and trusted-runner/agent-view split.
3. Run oracle preflight on a representative subset spanning package patterns.
4. Run one model/harness with explicit `with-skill` and `no-skill` arms.
5. Implement `task_runs.v2`, a v1-to-v2 upgrader, and a v1 compatibility reader
   while retaining immutable raw provider artifacts.
6. Add evidence-backed failure classification, bounded pair-level retries, and
   artifact access/export controls.

**Exit:** repeated local runs produce complete, auditable pairs; no-skill and
oracle negative-access tests pass; execution uses only verified immutable task
handles; v1/v2 fixtures round-trip under the documented compatibility policy.

### Phase 3 — paired analysis

1. Predeclare the fixed-benchmark estimand, primary endpoint, minimum effect,
   missingness gate, randomization seed, and multiplicity policy.
2. Add task-macro skill lift, fixed-task paired uncertainty, separately labelled
   task-population intervals, appropriate binary/graded analyses, and
   exploratory taxonomy slices.
3. Reject invalid cross-version, cross-digest, policy, or provider/harness
   deltas unless the compatibility conformance suite passes.
4. Surface arm-specific missingness, every retry, infrastructure failures, and
   complete-case sensitivity bounds.
5. Integrate executable results into subject scorecards.

**Exit:** synthetic and fault-injected fixtures validate clustering, weighting,
missingness bounds, and retry accounting; a report applies the predeclared rule
to support, reject, or mark inconclusive a skill-help claim under one fixed
model/harness/provider configuration.

### Phase 4 — upstream interchange

1. Contribute the smallest generally useful result-schema/export change.
2. Validate export/import round trips against upstream examples.
3. Submit eligible runs only through the upstream-approved path.
4. Upstream public task/verifier fixes; keep Intel-private suites separate.

**Exit:** no manual spreadsheet conversion is needed between the projects.

## 8. Validation gates

The integration is not complete until these gates pass:

- **Provenance:** release tag/commit, registry digest, task and transitive-input
  digests, exact runner/image, model snapshot, harness, skill artifact,
  canonical plugin set, policy digests, and repetition seed are present.
- **Package integrity:** concurrent materialization cannot expose partial
  content; mutation after verification is detected; providers reject raw paths
  and accept only immutable verified handles.
- **Supply chain:** base images and dependencies are pinned/scanned; network and
  credential policies are deny-by-default and evidenced in run metadata.
- **Oracle:** representative official tasks pass trusted oracle preflight;
  evaluated agents cannot read oracle/verifier files or diagnostics.
- **Treatment isolation:** no-skill agents cannot discover skills through files,
  prompts, APIs, environment, caches, or tools; all non-treatment fields match.
- **Pairing:** canonical block construction rejects a changed held-constant
  field, mutable alias, cross-digest pair, or unapproved provider/harness pair.
- **Failure accounting:** injected infrastructure, agent, verifier, ambiguous,
  and one-arm failures follow deterministic precedence, retry, reporting, and
  sensitivity rules.
- **Schema compatibility:** v1 fixtures upgrade deterministically to v2; v1
  readers remain supported as declared; unknown v2 fields survive a round trip.
- **Artifact controls:** raw artifacts have integrity and access metadata;
  secret/PII/proprietary fixtures are blocked from public export.
- **Statistics:** synthetic clustered pairs produce expected task-macro lift,
  confidence intervals, missingness bounds, and factorial interaction.
- **License:** every task and external asset has source, checksum, SPDX/terms,
  redistribution status, and required attribution/NOTICE records.

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
2. When registry and release documentation differ, which source defines the
   supported BenchFlow compatibility range? `agent-benchmark` will still resolve
   that range to one exact version and image digest per run.
3. Which verifier contracts define cross-task comparability for partial rewards?
   Until defined, graded rewards remain task-level or within a common scale.
4. Which trajectory fields may be redistributed under model-provider and task
   asset terms? Local export remains deny-by-default until answered.
5. Can one official run be accepted when orchestrated externally but executed
   through the upstream-approved BenchFlow provider? Until answered, reports
   are labelled unofficial and official submission is disabled.

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
