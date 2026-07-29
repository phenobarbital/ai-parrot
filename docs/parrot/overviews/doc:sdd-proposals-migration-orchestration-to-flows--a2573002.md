---
type: Wiki Overview
title: 'FEAT-155 — Final Migration: Remove `bots/orchestration`, Consolidate into
  `bots/flows`'
id: doc:sdd-proposals-migration-orchestration-to-flows-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `parrot.bots.orchestration` module contains **5 Python source files with
  ~4,900 lines** of code, all of which already have canonical copies in `parrot.bots.flows`.
  The agents (`OrchestratorAgent`, `A2AOrchestratorAgent`, HR classes) were moved
  to `flows/agents/` with adjusted
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.agents
  rel: mentions
- concept: mod:parrot.bots.flows.agents.orchestrator
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
- concept: mod:parrot.handlers.crew
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

---
id: FEAT-155
title: "Final migration: remove bots/orchestration, consolidate into bots/flows"
slug: migration-orchestration-to-flows
type: feature
mode: enrichment
status: accepted
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: "2026-05-10"
  summary_oneline: "Final phase of orchestration→flows migration: remove duplicate code, update all imports"
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-155/
created: "2026-05-10"
updated: "2026-05-10"
---

# FEAT-155 — Final Migration: Remove `bots/orchestration`, Consolidate into `bots/flows`

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — user request to complete the orchestration→flows migration
> **Audit**: [`sdd/state/FEAT-155/`](../state/FEAT-155/)

---

## 0. Origin

> With the feature `flow-primitives` (FEAT-134) we started the migration from
> `orchestration` to `flows` — all artifacts like AgentCrew have been migrated.
> This spec covers the final phase: moving the `a2a_orchestrator` and
> `OrchestratorAgent` to `parrot.bots.flows.agents`, and because `AgentCrew`
> was already migrated, removing the `bots/orchestration` folder completely.

**Initial signals**:
- Verbs: "remove", "moving" → cleanup / final migration phase
- Named entities: `OrchestratorAgent`, `A2AOrchestratorAgent`, `AgentCrew`, `bots/orchestration`, `bots/flows`
- Prior specs: FEAT-134 (flow-primitives, completed), FEAT-137 (agentcrew-primitives, completed)
- Acceptance criteria provided: implicit — folder removed, all imports working

---

## 1. Synthesis Summary

The `parrot.bots.orchestration` module contains **5 Python source files with ~4,900 lines** of code, all of which already have canonical copies in `parrot.bots.flows`. The agents (`OrchestratorAgent`, `A2AOrchestratorAgent`, HR classes) were moved to `flows/agents/` with adjusted import paths. `AgentCrew` was migrated to `flows/crew/` with updated result models (`FlowResult` replacing `CrewResult`). The old `orchestration/crew.py` is a hybrid: it imports core types from `flows.core` but still uses the old `CrewResult` model, making it a divergent copy rather than a re-export. There are **2 handler files**, **15 test files** (27+ import lines), and **13 example files** (20 import lines) that still reference the old `parrot.bots.orchestration` path. One test file (`test_execution_memory_integration.py`) already has **broken imports** referencing non-existent `orchestration.storage` and `orchestration.tools` modules. The migration can be completed cleanly because `flows/__init__.py` already exports all 30+ symbols needed.

---

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `src/parrot/bots/orchestration/__init__.py` | module exports | 1-4 | Re-exports AgentCrew, OrchestratorAgent, A2AOrchestratorAgent from local modules | F001 |
| 2 | `src/parrot/bots/orchestration/crew.py` | `AgentCrew`, `_CrewAgentNode` | 1-3615 | Hybrid: full AgentCrew with old CrewResult + flows.core imports | F001, F006 |
| 3 | `src/parrot/bots/orchestration/agent.py` | `OrchestratorAgent` | 1-334 | Full duplicate of flows/agents/orchestrator.py | F001 |
| 4 | `src/parrot/bots/orchestration/a2a_orchestrator.py` | `A2AOrchestratorAgent` | 1-308 | Full duplicate of flows/agents/a2a_orchestrator.py | F001 |
| 5 | `src/parrot/bots/orchestration/hr.py` | `HRAgentFactory`, `RAGHRAgent`, `EmployeeDataAgent` | 1-434 | Full duplicate of flows/agents/hr.py | F001 |
| 6 | `src/parrot/bots/orchestration/verify.py` | standalone script | 1-203 | FSM verification script, not imported anywhere | F001 |
| 7 | `src/parrot/bots/flows/__init__.py` | 30+ exports | 1-115 | Master re-export hub — all needed symbols available | F002, F007 |
| 8 | `src/parrot/bots/flows/agents/` | agent classes | all | Canonical location for orchestrator agents | F002 |
| 9 | `src/parrot/bots/flows/crew/` | `AgentCrew`, `CrewAgentNode` | all | Canonical location for crew with new result models | F002 |
| 10 | `src/parrot/handlers/crew/handler.py` | import line | 18 | Imports AgentCrew from orchestration | F003 |
| 11 | `src/parrot/handlers/crew/execution_handler.py` | import line | 7 | Imports AgentCrew from orchestration | F003 |

All paths relative to `packages/ai-parrot/`.

### 2.2 Constraints Discovered

- **`orchestration/crew.py` is NOT a re-export.** It's a 3615-line hybrid file that imports core types from `flows.core` but defines its own `AgentCrew` class using old `CrewResult`/`AgentExecutionInfo` models. The canonical `flows/crew/crew.py` (3564 lines) uses the new `FlowResult`/`NodeExecutionInfo` models. These are **divergent implementations**.
  *Implication*: Consumers importing from `orchestration.crew` get the old result model behavior. Switching them to `flows.crew` changes the result type from `CrewResult` to `FlowResult`. Need to verify `CrewResult` backward compat or update consumers.
  *Evidence*: F006

- **`_CrewAgentNode` vs `CrewAgentNode`.** The old crew uses `_CrewAgentNode` (private name), the new one uses `CrewAgentNode` (public). Test `test_agentnode_execute.py` imports `_CrewAgentNode` directly.
  *Implication*: This test needs updating to use the new public name.
  *Evidence*: F004, F006

- **Handler layer is production code.** The 2 handler files in `parrot/handlers/crew/` are production REST endpoints, not just tests/examples. Their import update must be verified with tests.
  *Evidence*: F003

- **Already-broken test.** `test_execution_memory_integration.py` imports from `orchestration.storage` and `orchestration.tools` — modules that don't exist. This test is already broken.
  *Implication*: Fix this test while migrating everything else.
  *Evidence*: F008

- **Examples reference `AgentsFlow` from `orchestration`.** Several decision workflow examples import `AgentsFlow` from `parrot.bots.orchestration`, but the current `orchestration/__init__.py` doesn't export it. `AgentsFlow` lives in `parrot.bots.flow` (singular). These examples are already broken or rely on stale bytecache.
  *Evidence*: F005

- **`bots/__init__.py` does NOT re-export orchestration.** The `parrot.bots` package only exports `AbstractBot`, `BaseBot`, `BasicBot`, `Agent`, `BasicAgent`, `Chatbot`, `WebSearchAgent`. No orchestration symbols.
  *Implication*: No changes needed to `bots/__init__.py`.
  *Evidence*: F002

### 2.3 Recent History (Relevant)

| Feature | FEAT-ID | When | Status | Impact |
|---------|---------|------|--------|--------|
| flow-primitives | FEAT-134 | 2026-04-29 | completed | Created `flows/core/` with shared primitives |
| agentcrew-primitives | FEAT-137 | 2026-04-30 | completed | Migrated AgentCrew to `flows/crew/`, moved agents to `flows/agents/` |

Both prior specs are complete. The current `orchestration/` directory is a leftover from the migration — canonical code lives in `flows/`.

---

## 3. Probable Scope

### What's New

Nothing new — this is purely a cleanup/removal spec.

### What Changes

- **`orchestration/__init__.py`** → **deleted** (or converted to thin re-export stub with deprecation warning during transition). *Evidence*: F001, F007
- **`orchestration/crew.py`** (3615 lines) → **deleted**. The canonical `flows/crew/crew.py` replaces it. *Evidence*: F001, F006
- **`orchestration/agent.py`** (334 lines) → **deleted**. Canonical: `flows/agents/orchestrator.py`. *Evidence*: F001
- **`orchestration/a2a_orchestrator.py`** (308 lines) → **deleted**. Canonical: `flows/agents/a2a_orchestrator.py`. *Evidence*: F001
- **`orchestration/hr.py`** (434 lines) → **deleted**. Canonical: `flows/agents/hr.py`. *Evidence*: F001
- **`orchestration/verify.py`** (203 lines) → **deleted**. Standalone script, not imported. *Evidence*: F001
- **`orchestration/README.md`** → **deleted** or moved to `flows/`. *Evidence*: F001
- **`handlers/crew/handler.py:18`** → update import to `from parrot.bots.flows.crew import AgentCrew`. *Evidence*: F003
- **`handlers/crew/execution_handler.py:7`** → same import update. *Evidence*: F003
- **15 test files** → update imports from `orchestration` to `flows`. *Evidence*: F004
- **13 example files** → update imports from `orchestration` to `flows`. *Evidence*: F005
- **`test_execution_memory_integration.py`** → fix broken imports (storage/tools paths). *Evidence*: F008

### What's Untouched (Non-Goals)

- **`parrot.bots.flow` (singular)** — the AgentsFlow/FSM engine. That module is separate and NOT part of this migration. It has its own lifecycle.
- **`parrot.bots.flows.core/`** — no changes needed, already canonical.
- **`parrot.bots.flows.crew/`** — no changes needed, already canonical.
- **`parrot.bots.flows.agents/`** — no changes needed, already canonical.
- **`parrot.models.crew`** — `CrewResult` and `AgentExecutionInfo` models remain in place. Whether to deprecate them in favor of `FlowResult`/`NodeExecutionInfo` is a separate decision.
- **`parrot.handlers.crew/` handler logic** — only the import lines change, not the handler behavior.
- **`parrot.bots.__init__`** — does not export orchestration, no change needed.

### Patterns to Follow

- The `flows/agents/orchestrator.py` header documents the move: `"Moved from parrot.bots.orchestration.agent to parrot.bots.flows.agents.orchestrator (FEAT-143)."` Follow this convention for traceability. *Evidence*: F002
- `flows/__init__.py` is the canonical public API surface — all downstream should import from `parrot.bots.flows` or its sub-packages. *Evidence*: F007

### Integration Risks

- **Result model divergence.** `orchestration/crew.py` uses `CrewResult`; `flows/crew/crew.py` uses `FlowResult`. If handlers or tests assert specific result types, the switch could break assertions.
  *Mitigation*: Check if `FlowResult` is backward-compatible with `CrewResult` (likely yes — FEAT-137 addressed this). Run crew regression tests after migration.
  *Evidence*: F006

- **Private symbol `_CrewAgentNode`.** One test imports this private name. The flows version exposes `CrewAgentNode` (public).
  *Mitigation*: Update the test to use the new name.
  *Evidence*: F004

- **Stale bytecache in `parrot/bots/orchestration/__pycache__/`.** The installed (symlinked) `parrot/` directory has `.pyc` files from the old modules. After removing source files, stale bytecache could cause phantom imports.
  *Mitigation*: Delete `__pycache__` directories in the installed `parrot/bots/orchestration/` path as part of cleanup.
  *Evidence*: F001

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | All orchestration source files have canonical copies in flows/ | F001, F002 | high | Direct file comparison confirms duplicates |
| C2 | `orchestration/crew.py` is a divergent hybrid, not a re-export | F006 | high | Diff shows different result models |
| C3 | `flows/__init__.py` exports all symbols needed by consumers | F007 | high | Read of __init__.py confirms 30+ exports including all orchestration classes |
| C4 | 2 handler files need import updates | F003 | high | Direct grep |
| C5 | 15 test files need import updates | F004 | high | Direct grep, 27+ import lines |
| C6 | 13 example files need import updates | F005 | high | Direct grep, 20 import lines |
| C7 | `test_execution_memory_integration.py` is already broken | F008 | high | Imports from non-existent modules |
| C8 | `bots/__init__.py` doesn't need changes | F002 | high | Direct read confirms no orchestration re-exports |
| C9 | Result model switch (CrewResult→FlowResult) is safe | F006 | medium | FEAT-137 designed for compat, but needs test verification |
| C10 | No external consumers depend on `parrot.bots.orchestration` | — | medium | Inferred — ai-parrot is a framework, external users may import this path |

Distribution: **8** high, **2** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Are the agent classes already moved to flows/agents/?** — *Resolved*: Yes, confirmed by F002. `orchestrator.py`, `a2a_orchestrator.py`, and `hr.py` all exist in `flows/agents/` with adjusted import paths.
  *Resolves claims*: C1

- [x] **Is AgentCrew already in flows/crew/?** — *Resolved*: Yes, confirmed by F002 and F006. `flows/crew/crew.py` is the canonical version using new result models.
  *Resolves claims*: C1, C2

- [x] **Does flows/__init__.py export everything consumers need?** — *Resolved*: Yes, 30+ symbols exported including all agent classes, crew classes, core types, and tools.
  *Resolves claims*: C3

- [x] **Should `orchestration/__init__.py` be kept as a thin deprecation stub?** — *Resolved*: Delete entirely. All in-tree imports will be updated; external consumers read the changelog.
  *Resolves claims*: C10

- [x] **Should `CrewResult` backward-compat aliases be added to `FlowResult`?** — *Resolved*: Already handled in FEAT-137. Trust that the agentcrew-primitives migration ensured FlowResult is backward-compatible.
  *Resolves claims*: C9

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-155`** — *Rationale*: localization is high-confidence (C1-C8), scope is well-bounded (delete files + update imports), and the code is verified to be duplicated. The spec should decompose into ~4 tasks: (1) update handler imports, (2) update test imports + fix broken test, (3) update example imports, (4) delete `orchestration/` directory + clean bytecache.

### Alternatives

- **`/sdd-task FEAT-155`** — if you want to skip the spec and go straight to task decomposition. The scope is mechanical enough that a spec may be unnecessary.
- **`/sdd-brainstorm FEAT-155`** — not recommended. This is a cleanup task with a single obvious approach, not a design fork.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-155/state.json` |
| Source (raw) | `sdd/state/FEAT-155/source.md` |
| Research plan | (inline — no separate plan file for this enrichment) |
| Findings (digests) | `sdd/state/FEAT-155/findings/F001-*.md` through `F008-*.md` |

**Budget consumed**:
- Files read: 18 / 40
- Grep calls: 12 / 25
- Git calls: 2 / 10
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (source describes a feature migration, not a bug investigation).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Operator | Claude (Opus 4.6) |
| Prior specs | FEAT-134 flow-primitives (completed), FEAT-137 agentcrew-primitives (completed) |
| Continuation of | FEAT-134/FEAT-137 migration chain |
