---
id: FEAT-464
title: Matrix Swarm Sample — Multi-Provider Agent Swarm Demo
slug: matrix-swarm-sample
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-08-26
  summary_oneline: "Create a sample Agent swarm with Matrix Swarm feature, including Matrix homeserver via docker-compose"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-464/
created: 2026-08-26
updated: 2026-08-26
---

# FEAT-464 — Matrix Swarm Sample: Multi-Provider Agent Swarm Demo

> **Mode**: enrichment
> **Confidence**: high
> **Source**: inline — user request
> **Audit**: [`sdd/state/FEAT-464/`](../state/FEAT-464/)

---

## 0. Origin

> Create a sample Agent swarm with Matrix Swarm feature, include launch the
> Matrix homeserver using docker-compose.

**Initial signals**:
- Verbs: "create", "include", "launch" → new deliverable
- Named entities: "Agent swarm", "Matrix Swarm", "Matrix homeserver", "docker-compose"
- Dependency: requires FEAT-463 (matrix-agents-swarm) core modules
- Acceptance criteria provided: no (implicit — "a runnable sample")

---

## 1. Synthesis Summary

FEAT-463 (matrix-agents-swarm) already provides all infrastructure: a full
docker-compose dev stack (Synapse + Postgres + Element Web + bridges), a
6-step bootstrap script, example YAML configs (`swarm_crew.yaml`), and a
runner script (`swarm_example.py`). However, the existing example **cannot
run end-to-end** — `swarm_example.py::_setup_bots()` only logs a warning
("No real agents configured") instead of creating real Agent instances.

FEAT-464 fills this last-mile gap: a complete, standalone sample under
`examples/matrix_swarm/` with **4 agents each using a different LLM
provider** (OpenAI, Anthropic, Google Gemini, Nvidia NIM) — showcasing
AI-Parrot's vendor-agnostic architecture. The sample includes real agent
definitions with system prompts and tools, a demo runner, a step-by-step
README, and a Makefile for one-command launch.

---

## 2. Codebase Findings

> All entries grounded in `sdd/state/FEAT-464/findings/`. No fabricated paths.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `examples/matrix_crew/swarm_example.py` | `_setup_bots` | 115-140 | **Gap** — stub agent registration, no real agents | F003 |
| 2 | `examples/matrix_crew/swarm_crew.yaml` | — | all | Complete swarm config: 4 agents, 2 channels, tunnels | F005 |
| 3 | `docker-compose.matrix.yml` | — | all | Full dev stack: Synapse+Postgres+Element+bridges | F002 |
| 4 | `scripts/matrix/bootstrap.sh` | — | all | 6-step automated setup, `--dry-run` + `--bridges` | F004 |
| 5 | `examples/matrix_crew/MATRIX_CREW_GUIDE.md` | — | all | Comprehensive guide (needs swarm quickstart addendum) | F003 |
| 6 | `sdd/tasks/index/matrix-agents-swarm.json` | — | all | FEAT-463: 10 tasks (2478-2487), all in-progress | F001 |
| 7 | `packages/ai-parrot/src/parrot/clients/factory.py` | `LLMFactory` | 161+ | Factory: `"provider:model"` → client instance | — |
| 8 | `packages/ai-parrot/src/parrot/clients/gpt.py` | `OpenAIClient` | 80 | OpenAI provider | — |
| 9 | `packages/ai-parrot/src/parrot/clients/claude.py` | `AnthropicClient` | 67 | Anthropic provider | — |
| 10 | `packages/ai-parrot/src/parrot/clients/google/client.py` | `GoogleGenAIClient` | 95 | Google GenAI provider | — |
| 11 | `packages/ai-parrot/src/parrot/clients/nvidia.py` | `NvidiaClient` | 207 | Nvidia NIM provider | — |

### 2.2 Constraints Discovered

- **LLM string format**: `LLMFactory.create("provider:model")` — e.g.
  `"openai:gpt-4o"`, `"anthropic:claude-sonnet-4-20250514"`,
  `"google:gemini-2.5-flash"`, `"nvidia:meta/llama-3.3-70b-instruct"`.
  *Evidence*: factory.py:161-210

- **FEAT-463 dependency**: all 10 core tasks (TASK-2478–2487) are status
  `in-progress`. The sample imports `MatrixCrewTransport`,
  `MatrixCrewConfig`, `AgentSwarmToolkit` from
  `parrot.integrations.matrix.crew` — these must exist before the sample
  can actually run. *Evidence*: F001

- **chatbot_id contract**: `swarm_crew.yaml` defines 4 agents with
  chatbot_ids: `web-researcher`, `financial-analyst`, `report-writer`,
  `synthesis-agent`. The demo script must register Agent instances in
  BotManager under these exact ids. *Evidence*: F005

- **AGPL-3.0 container isolation**: Synapse, Element Web, and mautrix
  bridges are AGPL-3.0 and run as Docker containers only — never imported
  by MIT-licensed ai-parrot Python code. *Evidence*: F002

- **Environment variables**: The compose stack + crew config require:
  `MATRIX_AS_TOKEN`, `MATRIX_HS_TOKEN`, `MATRIX_GENERAL_ROOM_ID` (from
  bootstrap output), plus per-provider API keys: `OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` / `GOOGLE_APPLICATION_CREDENTIALS`,
  `NVIDIA_API_KEY`. *Evidence*: F002, F005

### 2.3 Recent History

- 2026-08-25: FEAT-463 brainstorm + spec approved, 10 tasks generated
- 2026-08-26: FEAT-464 ID reserved, docker-compose.matrix.yml and
  bootstrap.sh already committed on dev

---

## 3. Hypothesis / Scope

### Hypothesis

The sample needs:

1. **`examples/matrix_swarm/agents.yaml`** — 4 agent definitions with
   different LLM providers, system prompts, and tool configs
2. **`examples/matrix_swarm/swarm_demo.py`** — runnable demo that
   instantiates real Agent instances from the YAML, registers them in
   BotManager, and starts MatrixCrewTransport
3. **`examples/matrix_swarm/swarm_config.yaml`** — swarm crew config
   (adapted from `swarm_crew.yaml` to work self-contained)
4. **`examples/matrix_swarm/README.md`** — step-by-step quickstart from
   zero to running swarm (prerequisites → bootstrap → run → interact)
5. **`examples/matrix_swarm/Makefile`** — convenience targets: `setup`,
   `start`, `stop`, `logs`, `demo`
6. **`examples/matrix_swarm/.env.example`** — all required env vars

**Confidence**: high — all infrastructure exists, only agent definitions and
glue code are missing.

### Agent Allocation (Multi-Provider Showcase)

| Agent | chatbot_id | Provider | Model | Role |
|-------|-----------|----------|-------|------|
| Researcher | `web-researcher` | **OpenAI** | `gpt-4o` | Web search, document analysis |
| Analyst | `financial-analyst` | **Anthropic** | `claude-sonnet-4-20250514` | SQL, financial analysis |
| Writer | `report-writer` | **Google** | `gemini-2.5-flash` | Report writing, editing |
| Summarizer | `synthesis-agent` | **Nvidia NIM** | `meta/llama-3.3-70b-instruct` | Synthesis, scoring |

This allocation demonstrates that agents in the same swarm can use
completely different LLM backends — the hallmark of AI-Parrot's
vendor-agnostic `AbstractClient` architecture.

### In Scope

- `examples/matrix_swarm/` — complete standalone sample directory
- Agent definitions with system prompts, tools, and per-provider LLM config
- Runnable demo script using `MatrixCrewTransport.from_yaml()`
- Step-by-step README (prerequisites → bootstrap → env → run → interact)
- Makefile with convenience targets
- `.env.example` with all required environment variables

### Out of Scope

- Core swarm Python modules (FEAT-463)
- `docker-compose.matrix.yml` modifications (already complete)
- `scripts/matrix/bootstrap.sh` modifications (already complete)
- Bridge configuration (FEAT-463 TASK-2486)
- MATRIX_CREW_GUIDE.md updates (FEAT-463 TASK-2487)

---

## 4. Confidence Map

| Claim | Confidence | Evidence |
|-------|-----------|----------|
| Docker dev stack is complete and ready to use | ✓ **high** | F002, F004 |
| `swarm_crew.yaml` config is complete for 4-agent swarm | ✓ **high** | F005 |
| `swarm_example.py` needs real agent registration to be runnable | ✓ **high** | F003 |
| FEAT-463 core modules not yet implemented (all tasks in-progress) | ✓ **high** | F001 |
| Standalone sample with README will make the feature accessible | ✓ **high** | F003, F006 |
| 4 providers (OpenAI/Anthropic/Google/Nvidia) all supported by factory | ✓ **high** | factory.py |
| `agents.yaml` can define agents for BotManager loading | ◐ **medium** | F005 |

---

## 5. Open Questions

### Resolved

- [x] **U1**: Should the sample create a new directory or extend `examples/matrix_crew/`?
  **Answer**: New `examples/matrix_swarm/` — standalone directory for clean separation.

- [x] **U2**: Which LLM providers should the sample use?
  **Answer**: 4 agents with different clients — OpenAI (researcher), Anthropic
  (analyst), Google Gemini (writer), Nvidia NIM (summarizer). Showcases
  vendor-agnostic architecture.

### Remaining

*None — all unknowns resolved.*

---

## 6. Recommended Next Step

→ **`/sdd-spec FEAT-464`**

**Rationale**: high-confidence localization with clear scope. The sample has
well-defined boundaries (examples directory, real agent setup, README) and a
clear dependency on FEAT-463. Ready for spec + task decomposition. Estimated
3-4 tasks: agents.yaml + demo script, swarm_config.yaml, README + Makefile,
tests.

**Alternatives**:
- `/sdd-task FEAT-464` — if the fix is trivial (it's not — 6 files, 4 providers)
- `/sdd-brainstorm FEAT-464` — unnecessary, architecture is clear
- Manual review — only if FEAT-463 timeline is uncertain

---

## 7. Research Audit

| Metric | Value |
|--------|-------|
| Wiki queries | 4 (free, no budget) |
| Wiki page reads | 7 (free, no budget) |
| Files read | 10 |
| Grep calls | 4 |
| Git calls | 0 |
| Depth reached | 1 |
| Findings persisted | 6 (F001–F006) |
| State directory | `sdd/state/FEAT-464/` |
| Budget profile | default (40 files / 25 grep / 10 git) |
| Truncated | no |
