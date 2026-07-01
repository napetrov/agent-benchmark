# Architecture assessment: evaluating MCP docs, skills, and agent persona prompts

**Status:** Largely implemented. The treatment-arm framework, all three
scenarios (injection + agentic), and the in-process agent tool-calling loop have
landed (`agent_benchmarks/treatments/`, the `mcp:` doc source,
`agent_benchmarks/eval/{arm_runner,agent_runner}.py`, and `python cli.py arms
run`). Only faithful skill *script execution* on the terminal-bench track
remains (rest of Phase 4) — see §8 and BACKLOG #56. The how-to lives in
[../evaluating-treatments.md](../evaluating-treatments.md).

**Date:** 2026-05-29

---

## 1. Goal

Today the benchmark answers one question: *does retrieved documentation improve
model answers?* We now want to evaluate three additional kinds of
context-augmentation artifact and measure the marginal value of each:

1. **MCP doc** — documentation delivered through a real MCP server (tool-call
   protocol), not just an HTTP/file fetch.
2. **Skills** — packaged agent skills (`SKILL.md` + frontmatter + optional
   bundled scripts/resources) made available to the answering agent.
3. **Agent persona prompts** — system/persona prompts that shape how the
   answering agent behaves.

This document assesses how far the current architecture gets us, where it
blocks, and the smallest set of changes that makes all three first-class.

---

## 2. What the current architecture actually measures

The LLM track is a **two-arm A/B test** with a single, hard-coded treatment:

- **Treatment** = documentation chunks, *retrieved* via an `MCPClient` and
  *prepended* to the answer prompt.
- **Arms** = exactly two: `with_docs` and `without_docs`
  (`agent_benchmarks/eval/answerer.py:196` `_generate_answer_pair`).
- **Outcome** = an LLM-as-judge score over five text dimensions
  (`config/products.yaml:66`), reduced to a `delta = with − without`.

The seams that already generalize well:

| Seam | Where | Notes |
|---|---|---|
| Retrieval source | `mcp/factory.py` `create_doc_source_client` | The one pluggable dispatch point (`context7` / `local:` / `url:`). |
| Retrieval contract | `mcp/__init__.py` `MCPClient` ABC | `resolve_library_id` + `get_library_docs` + `check_connection`. |
| Answer generation | `eval/answerer.py` | Single-shot completion; doc text injected into one prompt template. |
| Scoring | `eval/judge.py`, `eval/panel.py`, `eval/ragas_eval.py` | Judges an answer string; treatment-agnostic in principle. |
| Outcome validation | `terminal-bench-tasks/` | Docker + oracle + pytest — the only place *behavior*, not text, is checked. |

The seams that **do not** generalize and will block the new cases:

1. **The treatment is binary and hard-coded.** `with_docs` / `without_docs`
   keys are threaded through `answerer.py`, `judge.py`, `report/`, and
   `dashboard/`. There is no concept of "arm N" or "treatment registry."
2. **`MCPClient` is mis-named.** It is a *doc-retrieval* interface, not the MCP
   wire protocol. `Context7Client` talks HTTP; per
   [2026-02-14-context7-http-vs-mcp.md](2026-02-14-context7-http-vs-mcp.md) the
   repo deliberately does **not** speak MCP stdio/SSE today.
3. **Prompts are fixed.** `ANSWER_PROMPT_WITH_DOCS` / `WITHOUT_DOCS`
   (`answerer.py:19-39`) bake in the system framing, so the answering agent's
   persona cannot be varied.
4. **There is no "agent."** The answerer is a single completion call with no
   tool-use loop. Skills and real-MCP usage are inherently agentic (the model
   *decides* to call a tool / trigger a skill and may run scripts).
5. **Naming collision.** "Persona" already means a *synthetic user who asks
   questions* (`personas/generator.py`). The new "agent persona prompt" is a
   *property of the answerer*, not the asker. We must disambiguate to avoid
   confusion in code and reports.

---

## 3. The three cases, mapped onto the architecture

All three are the same shape: **a treatment that modifies the agent's setup
before it answers.** The differences are *what* they modify and *how* their
value becomes observable.

| Case | What it modifies | Fits current Q&A judging? | Needs agent loop? |
|---|---|---|---|
| MCP doc | Injected context (retrieved via MCP tools) | Yes (closest to today) | Optional (agent can choose to call) |
| Skills | Instructions + available tools/scripts | Weakly | Yes, to show real value |
| Agent persona prompt | System prompt | Yes (cheap) | No |

### 3.1 MCP doc — smallest gap

This is the natural next step from the existing `--doc-source`. Add a real
MCP-protocol client (stdio / SSE / streamable-HTTP) that:

- connects to an arbitrary MCP server from config (command/url + auth),
- discovers tools, and
- calls a designated doc-retrieval tool, mapping its result into the existing
  `get_library_docs` chunk shape.

It slots straight into `MCPClient` + `factory.py` (e.g.
`mcp:<server-ref>`). The interesting *new* measurement is two sub-arms:
**injected** (we call the tool and prepend the result, like today) vs
**agentic** (the model is given the MCP tool and decides whether/how to call
it). The latter requires the agent loop (§4.3) and is what actually tests
whether an MCP doc server is *usable by an agent*, not just whether its text is
relevant.

### 3.2 Skills — biggest conceptual gap

A skill is not retrievable chunks; it is **instructions plus capability**: a
`SKILL.md` (name + description in frontmatter, body loaded on trigger) and
often bundled scripts/resources the agent is expected to run. Two evaluation
modes:

- **Context-injection mode (cheap, partial):** treat the `SKILL.md` body as the
  injected context for a relevant question. Fits the current answerer with a
  new provider, but under-measures skills whose value is in *running code*.
- **Agentic mode (faithful):** expose the skill to an agent that can read its
  description, decide to use it, and execute its scripts in a sandbox; score
  the *outcome*. This belongs on the **terminal-bench track** — a skill is
  validated by whether the task passes its verifier, mirroring how skills are
  actually consumed.

### 3.3 Agent persona prompt — cheapest gap

A persona prompt is just a swappable **system prompt** for the answerer. The
only blocker is that the prompt is currently a constant. Parameterize it and a
persona prompt becomes one more treatment arm. Care needed only on naming
(call it `agent_profile` / `system_profile`, never `persona`).

---

## 4. Proposed generalization

### 4.1 From "doc source" to "treatment arms"

Replace the binary `with_docs/without_docs` with a list of named **arms**, each
a composition of up to four levers. A `ContextProvider` (treatment) protocol:

```python
class Treatment(Protocol):
    name: str                      # arm id, e.g. "mcp_doc", "skill:foo", "baseline"
    def prepare(self, task) -> AgentConfig: ...

@dataclass
class AgentConfig:
    system_prompt: str | None      # agent persona prompt
    injected_context: list[Chunk]  # retrieved docs / skill body
    tools: list[ToolSpec]          # MCP tools, skill scripts
    skills: list[SkillSpec]        # skills offered to the agent
```

The existing doc-injection behavior becomes one `Treatment` implementation;
`baseline` (no levers) is another. The matrix of arms is declared in config,
not hard-coded in `answerer.py`.

### 4.2 Two outcome layers, pick per treatment

- **Q&A judging** (existing `eval/`): for arms whose value shows up in a single
  answer — MCP-doc-injection, persona prompts, skill-as-context.
- **Task outcome** (existing `terminal-bench-tasks/`): for arms whose value is
  behavioral — agentic MCP use, skills that run code, personas that change
  multi-step strategy. The `task.toml` already carries an `[agent]` block; add
  a per-arm `[treatment]` block and report pass-rate deltas across arms.

Skills and real-MCP should be measured on **both** where possible, with the
task track treated as the authoritative signal.

### 4.3 The missing piece: a minimal agent loop

Two of three cases need the model to *use* a capability, not just read text.
This requires an agent runner (LiteLLM tool-calling loop already feasible via
`llm.py`) that: offers tools/skills, executes tool calls / skill scripts in a
sandbox, and returns the transcript for judging or hands off to the
terminal-bench verifier. This is the single largest new component and the main
build-vs-reuse decision (see §7).

---

## 5. Concrete changes by module

| Module | Change |
|---|---|
| `mcp/` | Add a true MCP-protocol client (stdio/SSE/HTTP) + tool discovery; rename the ABC's intent (doc-retrieval vs transport) or split it. Extend `factory.py` with `mcp:<ref>` and `skill:<ref>`. |
| `eval/answerer.py` | Generalize `_generate_answer_pair` from 2 fixed arms to N arms; parameterize the system prompt; thread `AgentConfig`. |
| `eval/` (new) | `agent_runner.py` — tool-calling/skill-execution loop for agentic arms. |
| `eval/judge.py`, `panel.py`, `report/`, `dashboard/` | Replace `with/without` assumptions with arm-keyed maps; deltas become per-arm-vs-baseline. |
| `config/products.yaml` | Add a `treatments:`/`arms:` section (which levers, which MCP server, which skills, which agent profile). |
| `cli.py` | `--doc-source` stays for back-compat; add `--arms`/`--treatment`. |
| `terminal-bench-tasks/` | Per-arm `[treatment]` block in `task.toml`; verifier reports outcome per arm. |
| New top-level dirs | `skills/` (SKILL.md fixtures) and `agent_profiles/` (persona prompt fixtures), parallel to `questions/`, `answers/`. |

Note the **naming discipline**: introduce `agent_profile` for the answerer's
system prompt and reserve `persona` for the existing synthetic-user concept.

---

## 6. Evaluation-methodology caveats

- **Q&A judging will under-measure skills and personas.** Their value is often
  procedural (which steps, which tool, fewer mistakes), invisible in a
  one-shot answer. Lean on the task track for these; treat single-answer deltas
  as a weak proxy.
- **Confounders multiply with arms.** Comparisons must hold the asker model,
  question set (`question_set_hash` already exists, `pipeline.py:15`), and judge
  fixed across arms — only the treatment varies.
- **Agentic arms are nondeterministic and costlier.** Tool loops add latency,
  token cost, and variance; budget for repeated trials and seed/temperature
  control.
- **Faithful skill eval needs sandboxed execution.** Running skill scripts is a
  security surface — reuse the terminal-bench Docker isolation
  (`allow_internet = false`), do not exec in-process.

---

## 7. Risks and open decisions

1. **Agent loop: build vs adopt.** Reuse the terminal-bench/Harbor harness for
   agentic arms rather than a second bespoke runner? (Recommended.)
2. **Scope of "MCP doc".** Just add an MCP transport for retrieval (small), or
   the full agentic "does the agent use the MCP server well" eval (large)?
3. **Refactor blast radius.** Generalizing `with/without` touches answerer,
   judge, panel, report, dashboard, and committed fixtures under `answers/`,
   `eval/`, `baselines/`. Needs a migration shim so existing two-arm fixtures
   still load.
4. **Naming.** Lock `agent_profile` vs `persona` before writing code.

---

## 8. Suggested phasing

- **Phase 1 — DONE.** Agent persona prompts. `system` support in `llm.py`,
  `agent_profiles/` fixtures + loader, `AgentProfileTreatment`, N-arm report.
- **Phase 2 — DONE (injection).** MCP doc — real MCP-protocol retrieval client
  (`mcp/mcp_protocol.py`) behind `factory.py` as `mcp:<ref>`, injected sub-arm.
  The `mcp` SDK is an optional dependency. Agentic MCP use is still Phase 3.
- **Phase 3 — DONE (in-process).** Tool-calling agent loop
  (`eval/agent_runner.py`) with read-only tools: `agent[:source]` (doc search)
  and `skill-agent:<path>` (progressive disclosure). The report records tool-use
  rate. Sandboxed *script* execution stays on the terminal-bench track (§4.3,
  Phase 4).
- **Phase 4 — PARTIAL.** Skills: `skills/` fixtures + `SKILL.md` loader, the
  skill-as-context arm (`SkillTreatment`), and the agentic skill-view arm
  (`SkillAgentTreatment`) are done. `ViewSkillTool` now supports multi-file
  skills: when sibling `.md` files exist, the tool offers a `file` parameter
  allowing progressive disclosure (the model can load `SKILL.md` navigation first,
  then load specific topic files). Faithful skill *script execution* on the
  terminal-bench track remains.

Each phase is independently shippable and leaves the existing two-arm
doc-validation flow working.

## 9. What landed in the first implementation pass

- `agent_benchmarks/treatments/` — `Treatment`/`AgentConfig` abstraction and the
  `baseline` / `docs` / `mcp_doc` / `profile` / `skill` arms + factory.
- `agent_benchmarks/eval/arm_runner.py` — N-arm answer generation and judging,
  reusing the existing `Judge` (via a new public `Judge.score_answer`).
- `agent_benchmarks/eval/agent_runner.py` — bounded tool-calling loop;
  `treatments/tools.py` (`DocQueryTool`, `ViewSkillTool`) and the
  `MCPAgentTreatment` / `SkillAgentTreatment` arms; `chat_completion` in `llm.py`.
- `agent_benchmarks/mcp/mcp_protocol.py` + `mcp:` in the doc-source factory.
- `agent_benchmarks/skills/` and `agent_benchmarks/agent_profiles/` loaders, plus
  `parse_frontmatter` in `utils.py`.
- `agent_benchmarks/report/arms_report.py` and `python cli.py arms run`.
- Seed fixtures: `agent_profiles/concise_expert.md`,
  `skills/onetbb-quickstart/SKILL.md`. The existing two-arm `with_docs`/
  `without_docs` pipeline is untouched.
