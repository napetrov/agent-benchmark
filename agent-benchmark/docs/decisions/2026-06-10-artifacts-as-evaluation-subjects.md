# ADR: Artifacts as first-class evaluation subjects

**Status:** ACCEPTED — IN PROGRESS (Phase D, PR #101/#102 stack). One of five
decisions under the
[evaluation-beyond-MCP-docs umbrella](2026-06-10-evaluation-beyond-mcp-docs.md)
(BACKLOG #59). Landed: a `subjects/` descriptor + loader
(`agent_benchmarks/subjects/`), `cli.py subjects {list,show,run}` wrapping the
awareness `arm_runner` matrix cells, `report/subject_report.py`, the versioned
`subject_scorecard.v1` schema, and a faithful executable-task adapter for work
suites via `--work-harnesses` (writing `task_runs.v1` and embedding the work
artifact/summary in the scorecard — the object #58d/#58i serialize and sign).
Builds on the treatment-arm framework
([2026-05-29](2026-05-29-evaluating-mcp-skills-personas.md);
`agent_benchmarks/treatments/`, `eval/arm_runner.py`, `cli.py arms run`) and feeds
the packaging scorecard (#58d/#58i).

**Date:** 2026-06-10

**Phase:** D in the umbrella rollout (land after coverage, model × harness, and
plugin-aware cells).

---

## 1. Context

In the current design the **product** is the subject of an experiment and a
skill / agent profile / MCP server is a *lever* (an "arm") toggled on top of one
product's question set. `cli.py arms run --product oneTBB --arms
"baseline,skill:…,profile:…"` reports, per product, how each arm moves the judge
score. The artifact only ever appears as a *column* in one product's report.

That framing fights the direction of umbrella #58, whose deliverable is a
**summonable Intel expert** assembled from artifacts that *ship*: a profile, some
skills, an MCP source, a setup guide. To decide whether such an artifact is worth
shipping we need to answer a question the current reports cannot:

> *Across the portfolio of products, questions, and tasks where this skill (or
> profile, or bundle) is supposed to help, does it actually help — and by how
> much, under which conditions?*

There is no object in the system today that represents "an artifact plus the
suite it is measured against plus the resulting evidence." The arm machinery
produces the right *measurements*; it just aggregates them along the wrong axis
(per product) and throws away the artifact-centric view.

## 2. Decision

Introduce a first-class **evaluation subject**: a declarative descriptor naming
the artifact under test, the suite it is measured against, the baseline to delta
against, and the matrix of conditions to sweep. A new loader expands a subject
into the arms the framework already knows, runs them via the existing
`arm_runner` (and, for the work half, the terminal-bench harness adapter from the
[model × harness ADR](2026-06-10-model-harness-dimension.md)), and **aggregates
per subject** into a versioned **scorecard**.

The product-centric `arms run` stays as the low-level entry point. Subjects are a
thin, opinionated layer on top — they do not replace arms, they *orient* them
around the shippable artifact.

## 3. Detailed design

### 3.1 The subject descriptor

```yaml
# subjects/onetbb-quickstart.yaml   (illustrative — schema, not final field names)
subject:
  id: onetbb-quickstart
  kind: skill                       # skill | profile | mcp | doc-source | bundle
  ref: data/skills/onetbb-quickstart
  # bundle only:
  # members:
  #   - {kind: profile, ref: data/agent_profiles/concise_expert.md}
  #   - {kind: skill,   ref: data/skills/onetbb-quickstart}
  #   - {kind: mcp,     ref: "mcp:http=https://mcp.context7.com/mcp"}

suite:
  products: [oneTBB]
  questions: [data/questions/onetbb_golden.json]   # awareness half
  tasks: ["terminal-bench-tasks/onetbb-*"]         # work half (optional but encouraged)

baseline: baseline                  # arm id to delta against (default: the no-lever control)

matrix:                             # see the model × harness ADR; omitted ⇒ one default cell
  models: ["<model-a>"]
  harnesses: [single-shot, agent]
```

### 3.2 Subject kinds → arms

Each `kind` maps to arm specs the framework already supports, so the subject
loader adds *no new answering machinery*:

| `kind` | Treatment arm(s) generated | Notes |
|---|---|---|
| `skill` | `skill:<ref>` and, when a task suite is present, `skill-agent:<ref>` | progressive-disclosure variant is the faithful one |
| `profile` | `profile:<ref>` | single-shot system-prompt swap |
| `mcp` | `mcp:<ref>` and `agent:mcp:<ref>` | injection vs agentic use |
| `doc-source` | `docs:<ref>` | local/url/context7 |
| `bundle` | one composite arm whose `AgentConfig` merges all members | this *is* the `AgentConfig` a package serializes (#58a) |

A `bundle` is the important new shape: it is several artifacts shipped together,
i.e. exactly the in-memory `AgentConfig` (`treatments/base.py`) that the
packaging manifest serializes. Evaluating a bundle = evaluating the package
pre-ship.

### 3.3 New code, by module

| Module | Change |
|---|---|
| `agent_benchmarks/subjects/` (new) | `loader.py` (parse + validate the descriptor, glob `products`/`tasks`, resolve `kind`→arms), `models.py` (`Subject`, `Suite`, `Scorecard` dataclasses). |
| `agent_benchmarks/eval/arm_runner.py` | unchanged interface; called once per `(suite-cell, matrix-cell)` by the subject runner. |
| `agent_benchmarks/report/subject_report.py` (new) | renders a per-subject scorecard (Markdown + JSON) keyed by `(model, harness, plugin_set)`, awareness delta and work pass-rate delta side by side. |
| `agent_benchmarks/cli` (`commands/`) | `subjects run` / `subjects show` / `subjects list`; `arms run` untouched. |
| `agent_benchmarks/artifacts.py` | add a versioned `Scorecard` artifact schema (`schema_version`) reusing `question_set_hash` and `runner/manifest.py` provenance. |
| `subjects/` (new top-level dir) | committed subject descriptors, parallel to `data/skills/`, `data/agent_profiles/`. |

### 3.4 The scorecard artifact

The output object — the whole point of the ADR. One per subject, carrying enough
provenance to be reproducible and, later, signable (#58i):

```jsonc
{
  "schema_version": "1.0",
  "subject": {"id": "onetbb-quickstart", "kind": "skill", "ref_digest": "sha256:…"},
  "suite": {"products": ["oneTBB"], "question_set_hash": "…", "task_ids": ["onetbb-…"]},
  "baseline": "baseline",
  "cells": [
    {
      "model": "<model-a>", "harness": "agent",
      "awareness": {"baseline": 3.8, "treated": 4.2, "delta": 0.4, "ci95": [0.1, 0.7]},
      "work":      {"baseline_pass_rate": 0.50, "treated_pass_rate": 0.70, "delta": 0.20},
      "tool_use_rate": 0.83
    }
  ],
  "run_manifest": {"…": "models, versions, seeds, timestamps"}
}
```

`report/subject_report.py` renders this; #58d embeds it into the package
manifest as the gating credential; #58i adds the signature.

The fields are **illustrative**, not a frozen schema. In particular the `ci95`
interval presupposes the bootstrap-CI question still open in the
[model × harness ADR](2026-06-10-model-harness-dimension.md) O4 — whether deltas
carry confidence intervals by default is decided there, not here.

### 3.5 Relationship to the packaging manifest (#58)

A `bundle` subject and a `package.yaml` manifest describe nearly the same set of
artifacts. The intended division of labor (open question O1 below): **the subject
is the evaluation view, the package embeds the resulting scorecard.** A package
references a subject id; building a package runs (or looks up) that subject's
scorecard and stamps it in. This keeps the eval layer free of distribution
concerns (per-runtime exporters, discovery metadata) while giving the package a
real, dated credential rather than a self-asserted one.

## 4. Alternatives considered

1. **Keep everything product-centric; just add an aggregation script over arm
   reports.** Rejected: the artifact view would be a derived report with no
   stable identity, no provenance, and nothing for #58 to serialize. The
   scorecard needs to be a first-class, versioned artifact, not a pivot table.
2. **Make the subject the *only* entry point and retire `arms run`.** Rejected:
   `arms run` is the right low-level tool for ad-hoc, single-product
   exploration; forcing every experiment through a descriptor file adds friction
   and churns existing docs/fixtures. Subjects layer on top.
3. **Fold subjects directly into `package.yaml` (no separate descriptor).**
   Rejected for now: couples measurement to distribution and would drag exporter
   /discovery fields into the eval path. Revisit if the two schemas converge in
   practice (O1).

## 5. Consequences

- **Positive:** the project gains the object it actually wants to ship — a
  dated, reproducible, per-artifact credential — without new answering
  machinery. Bundles make whole-package pre-ship evaluation a first-class run.
- **Positive:** reporting finally answers "is this artifact worth it?" directly,
  across a portfolio, instead of forcing readers to mentally pivot per-product
  arm tables.
- **Negative / cost:** another descriptor format and CLI surface to learn and
  keep in sync with the arm specs it expands to. Mitigated by making `kind`→arm
  mapping the *only* place that knowledge lives.
- **Negative:** subject + suite + matrix is a multiplicative run; a careless
  subject can be very expensive. The matrix default is a single cell (see the
  model × harness ADR) and task cells are opt-in.

## 6. Open questions

- **O1 — Subject vs package overlap.** Is `subjects/` the pre-package form, or a
  separate eval-only descriptor a package references? (Leaning: eval view;
  package embeds the scorecard.)
- **O2 — Scorecard identity.** Digest the artifact `ref` content (so a scorecard
  is invalidated when the skill text changes) vs pin a git rev? (Leaning:
  content digest + git rev both recorded.)
- **O3 — Aggregation across products.** When a suite spans several products, is
  the headline number a simple mean of per-product deltas, or weighted by
  question/task count? (Leaning: report per-product and a documented weighted
  roll-up; never a single opaque scalar.)
- **O4 — Where committed subjects live.** Top-level `subjects/` vs
  `data/subjects/`. (Leaning: top-level, since a subject references tasks outside
  `data/`.)
