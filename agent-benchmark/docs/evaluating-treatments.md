# Evaluating treatments (docs, MCP, skills, agent profiles)

The original LLM benchmark answers one question — *do retrieved docs improve
answers?* — by comparing two arms, `with_docs` and `without_docs`. The
**treatment-arm** framework generalizes that to an N-way comparison so you can
measure the marginal value of any context-augmentation artifact:

| Arm spec | Scenario | What it changes |
|---|---|---|
| `baseline` | control | nothing (the old `without_docs`) |
| `docs` / `docs:<doc-source>` | documentation injection | injects retrieved doc chunks (the old `with_docs`) |
| `mcp:<ref>` | MCP doc server | retrieves docs through a real MCP server |
| `profile:<path>` | agent persona prompt | swaps the answering agent's system prompt |
| `skill:<path>` | agent skill | injects a `SKILL.md` as context |
| `agent[:source]` | **agentic** doc use | gives the model a doc-search tool; it decides when to call it |
| `skill-agent:<path>` | **agentic** skill use | offers the skill via progressive disclosure |
| `<spec1>+<spec2>[+...]` | **combined** treatment | merges multiple treatments into one arm (e.g., `docs+skill:path`) |

The last two run through a tool-calling loop
([`eval/agent_runner.py`](../agent_benchmarks/eval/agent_runner.py)): the model
*decides* whether to query docs or load a skill, and the report records how often
it actually did (the faithful test of whether a doc source or skill is *usable by
an agent*, not just whether its text is relevant). The rest are single-shot.

Each arm is a [`Treatment`](../agent_benchmarks/treatments/base.py) that produces
an `AgentConfig` (system prompt + injected context) per question. The answers
are scored by the same LLM-as-judge used elsewhere, and the report shows each
arm's average score and its delta vs the baseline arm.

Runtime plugins are a separate run dimension, not arms. They modify every arm
inside the same `(model, harness, plugin_set)` cell, and the JSON/Markdown
outputs stamp `harness`, `plugin_set`, `plugin_set_id`, and concrete plugin
metadata. The initial supported plugin is `plugin:caveman[:lite|full|ultra]`,
which adds a brevity system instruction before answer generation.

Plugin effects are computed from paired runs, not from one artifact in
isolation. Run the same product, questions, arms, model, provider, and harness
once with no plugin and once with the plugin enabled, then compare the two
`arms.v1` artifacts:

```bash
python cli.py arms plugin-delta \
  --baseline-json results/arms/oneTBB-none.json \
  --plugin-json results/arms/oneTBB-caveman.json \
  --out-json results/arms/oneTBB-caveman-delta.json
```

The command writes a `plugin_delta.v1` artifact plus a Markdown report with
judge-score deltas, token/cost deltas, and answer-length deltas. It refuses
confounded comparisons where model, provider, harness, arms, baseline arm, or
question count differ.

> **Naming:** an *agent profile* (`profile:`) is the answering agent's system
> prompt. It is **not** a `persona` — in this repo a persona is a synthetic
> *user* who asks questions (`agent_benchmarks/personas`).

## Quick start

```bash
python cli.py arms run \
  --product oneTBB \
  --questions data/questions/onetbb_golden.json \
  --arms "baseline,docs,profile:data/agent_profiles/concise_expert.md,skill:data/skills/onetbb-quickstart" \
  --judge \
  --out-json results/arms/oneTBB.json \
  --out-md results/arms/oneTBB.md
```

Without `--judge` the command only generates answers (cheap, no judge calls).
Outputs default to `results/arms/<product>.{json,md}` (ignored by git).

Example Caveman plugin cell:

```bash
python cli.py arms run \
  --product oneTBB \
  --questions data/questions/onetbb_golden.json \
  --arms "baseline,docs,skill:data/skills/onetbb-quickstart" \
  --harness openclaw-agent \
  --judge \
  --out-json results/arms/oneTBB-none.json

python cli.py arms run \
  --product oneTBB \
  --questions data/questions/onetbb_golden.json \
  --arms "baseline,docs,skill:data/skills/onetbb-quickstart" \
  --plugins "plugin:caveman" \
  --harness openclaw-agent \
  --judge \
  --out-json results/arms/oneTBB-caveman.json

python cli.py arms plugin-delta \
  --baseline-json results/arms/oneTBB-none.json \
  --plugin-json results/arms/oneTBB-caveman.json \
  --out-json results/arms/oneTBB-caveman-delta.json
```

## Arm specs in detail

- **`docs:<doc-source>`** — `<doc-source>` is anything
  [`create_doc_source_client`](../agent_benchmarks/mcp/factory.py) accepts:
  `context7` (default), `local:<path>`, `url:<url>`, or `mcp:<ref>`. Bare
  `docs` uses Context7.
- **`mcp:<ref>`** — retrieve through a real MCP server. `<ref>` is
  `<transport>=<target>[;opt=val...]`:
  - `mcp:cmd=npx -y @upstash/context7-mcp` (stdio)
  - `mcp:http=https://mcp.context7.com/mcp;tool=get-library-docs` (streamable HTTP)
  - `mcp:sse=https://example.com/sse;id=uxlfoundation/oneTBB` (SSE)

  Options: `tool=` (docs tool name), `resolve=` (resolve tool), `id=` (fixed
  library id). Requires the optional `mcp` SDK: `pip install mcp`.
- **`profile:<path>`** — a Markdown file; the body (frontmatter stripped) is the
  system prompt. See [`data/agent_profiles/concise_expert.md`](../data/agent_profiles/concise_expert.md).
- **`skill:<path>`** — a `SKILL.md` file or its directory, following the Agent
  Skills convention (frontmatter `name`/`description` + Markdown body). See
  [`data/skills/onetbb-quickstart/SKILL.md`](../data/skills/onetbb-quickstart/SKILL.md).
- **`agent[:<doc-source>]`** — agentic doc use. The model is given a
  `search_documentation` tool over `<doc-source>` (default `context7`) and
  chooses when and what to query. Tune the loop with `--max-iterations`.
- **`skill-agent:<path>`** — agentic skill use. The model sees only the skill's
  name + one-line description and calls a `view_skill_*` tool to load the full
  instructions on demand (progressive disclosure).
- **`<spec1>+<spec2>`** — combined treatment. Merges multiple treatments into a
  single arm by concatenating their contexts. Example: `docs+skill:data/skills/dpnp-quickstart`
  retrieves docs AND injects the skill, allowing measurement of synergistic effects.
  The `+` operator works between any treatment types except `baseline`.

Example comparing injection vs agentic use of the same MCP server:

```bash
python cli.py arms run --product oneTBB --questions data/questions/onetbb_golden.json \
  --arms "baseline,mcp:http=https://mcp.context7.com/mcp,agent:mcp:http=https://mcp.context7.com/mcp" \
  --judge --max-iterations 6
```

Example testing combined treatments (docs + skill together):

```bash
# 4-way comparison: baseline, docs-only, skill-only, and docs+skill combined
python cli.py arms run --product dpnp --questions data/questions/dpnp.json \
  --arms "baseline,docs,skill:data/skills/dpnp-quickstart,docs+skill:data/skills/dpnp-quickstart" \
  --context7-id "intelpython_github_io_dpnp" \
  --judge

# Or just baseline vs combined (to test synergy hypothesis)
python cli.py arms run --product dpnp --questions data/questions/dpnp.json \
  --arms "baseline,docs+skill:data/skills/dpnp-quickstart" \
  --context7-id "intelpython_github_io_dpnp" \
  --judge
```

The combined treatment concatenates contexts from all sub-treatments. Use this to
test whether treatments provide synergistic benefit (positive interaction effect)
or interfere with each other (negative interaction effect). Calculate interaction
as: `(docs+skill)_delta - docs_delta - skill_delta`. Positive = synergy, negative
= interference, zero = independent effects.

**More combined treatment examples:**

```bash
# Docs + profile (expert persona with comprehensive reference)
python cli.py arms run --product dpnp --questions data/questions/dpnp.json \
  --arms "baseline,docs+profile:data/agent_profiles/concise_expert.md" \
  --context7-id "intelpython_github_io_dpnp" \
  --judge

# Triple combination (docs + profile + skill)
python cli.py arms run --product dpnp --questions data/questions/dpnp.json \
  --arms "baseline,docs+profile:data/agent_profiles/expert.md+skill:data/skills/dpnp-quickstart" \
  --context7-id "intelpython_github_io_dpnp" \
  --judge

# Test if multiple skills complement each other
python cli.py arms run --product dpnp --questions data/questions/dpnp.json \
  --arms "baseline,skill:data/skills/dpnp-quickstart,skill:data/skills/dpnp-perf,skill:data/skills/dpnp-quickstart+skill:data/skills/dpnp-perf" \
  --judge
```

## Authoring fixtures

**Agent profile** (`agent_profiles/<id>.md`):

```markdown
---
id: concise_expert
name: Concise Expert
description: Terse, code-first senior engineer.
---
You are a senior systems engineer. Lead with code, be terse, …
```

**Skill** (`skills/<name>/SKILL.md`):

```markdown
---
name: my-skill
description: One line that tells the agent when to use this skill.
---
# Instructions
…
```

## Scope and caveats

- **Three levels of fidelity for skills/MCP.** (1) `skill:` / `mcp:` inject
  content directly — cheapest, but a model can't *choose* not to use it.
  (2) `skill-agent:` / `agent:` let the model decide via the tool-calling loop —
  faithful to how skills/MCP are consumed, but still read-only and in-process.
  (3) Running a skill's bundled *scripts* needs real sandboxing and belongs on
  the executable [terminal-bench track](contributing-terminal-bench-task.md)
  (tracked in BACKLOG #56) — the in-process loop deliberately exposes only
  read-only tools.
- **Single-answer judging under-measures skills and persona prompts**, whose
  value is often procedural. Treat the deltas as a proxy; use the task track for
  behavioral signal.
- **Fair comparisons** hold the answer model, question set, and judge fixed
  across arms — only the treatment varies.
- **Combined treatments concatenate contexts** in order: docs first, then profiles,
  then skills. This ordering is consistent but may increase prompt token usage
  significantly. Test combined treatments on a small question set first to estimate
  cost impact before running full evaluations.
- **Interaction effects may not be additive.** `(docs+skill)_delta` may differ from
  `docs_delta + skill_delta` due to context interference, redundancy, or synergy.
  Always measure the combined treatment directly rather than assuming linear effects.
