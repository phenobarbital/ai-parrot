---
type: Wiki Overview
title: FEAT-157 — Add on_complete and on_error lifecycle hooks to AgentCrew
id: doc:sdd-proposals-agentcrew-hooks-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AgentCrew currently has no crew-level lifecycle hooks — only per-agent callbacks
---

---
id: FEAT-157
title: Add on_complete and on_error lifecycle hooks to AgentCrew
slug: agentcrew-hooks
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-11
  summary_oneline: Add on_complete and on_error hooks to AgentCrew for post-execution callbacks
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-157/
created: 2026-05-11
updated: 2026-05-11
---

# FEAT-157 — Add on_complete and on_error lifecycle hooks to AgentCrew

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — user request
> **Audit**: [`sdd/state/FEAT-157/`](../state/FEAT-157/)

---

## 0. Origin

> Add "on_complete" hooks to AgentCrew, a list of registered functions can be
> called when an AgentCrew finished, a potential "on_error" can be added as well.

**Initial signals**:
- Verbs: "add", "called when finished" → new feature (enrichment mode)
- Named entities: AgentCrew, on_complete, on_error
- Components: `parrot/bots/orchestration/crew.py`
- Acceptance criteria provided: no (implicit from description)

---

## 1. Synthesis Summary

AgentCrew currently has no crew-level lifecycle hooks — only per-agent callbacks
(`on_agent_complete` in `run_flow()`) and per-node pre/post actions. All four
execution modes (`run_sequential`, `run_loop`, `run_parallel`, `run_flow`)
share an identical tail pattern: build `CrewResult`, optionally synthesize, persist,
and return. This proposal adds two hook lists — `on_complete` and `on_error` —
registered on the AgentCrew instance and invoked via a shared `_fire_hooks()`
method inserted into this common tail. The implementation reuses the existing
`ActionCallback` type and the async-aware invocation pattern from `Node.run_post_actions`.

---

## 2. Codebase Findings

> All entries grounded in research findings at `sdd/state/FEAT-157/findings/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | `AgentCrew.__init__` | 187-287 | Constructor — add hook lists | F001 |
| 2 | `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | `AgentCrew.run_sequential` | 1332-1378 | Tail pattern — invoke hooks | F002 |
| 3 | `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | `AgentCrew.run_loop` | 1782-1835 | Tail pattern — invoke hooks | F002 |
| 4 | `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | `AgentCrew.run_parallel` | 2100-2148 | Tail pattern — invoke hooks | F002 |
| 5 | `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | `AgentCrew.run_flow` | 2339-2383 | Tail pattern — invoke hooks | F002 |
| 6 | `packages/ai-parrot/src/parrot/bots/flows/core/types.py` | `ActionCallback` | 27 | Existing type alias to reuse | F003 |
| 7 | `packages/ai-parrot/src/parrot/models/crew.py` | `CrewResult` | 60-97 | Hook argument object | F004 |

### 2.2 Constraints Discovered

- **Sync+Async support required.** The existing `Node.run_post_actions` pattern
  uses `asyncio.iscoroutine()` to handle both sync and async callables.
  *Implication*: hooks must do the same.
  *Evidence*: F003

- **Hook errors must not prevent result return.** `AbstractBot._trigger_event`
  wraps each callback in `try/except` (abstract.py:828-834) to prevent one
  failing listener from crashing the whole event cycle.
  *Implication*: `_fire_hooks()` must catch and log exceptions per-hook.
  *Evidence*: F003

- **CrewResult.status determines which hooks fire.** Three statuses exist:
  `completed`, `partial`, `failed`. `on_complete` should fire for `completed`
  and `partial` (usable results exist). `on_error` should fire for `failed`
  (all agents failed). For `partial`, **both** lists fire.
  *Evidence*: F004

- **Existing `on_agent_complete` is per-agent, flow-only.** It fires per agent
  inside `_execute_parallel_agents()`. Crew-level hooks are orthogonal and should
  not interfere with or replace this existing mechanism.
  *Evidence*: F002, F003

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `c3eff31b` | today | @dev | sdd: start FEAT-156 — agentcrew-from-definition | `crew.py`, tasks |
| FEAT-147 | recent | @dev | Result persistence (PersistenceMixin) | `crew.py` |

> FEAT-156 (from_definition) is in-progress and adds a class method to build
> AgentCrew from CrewDefinition. Hook registration should be compatible but is
> orthogonal — hooks are runtime callables, not serializable definition data.

---

## 3. Probable Scope

### What's New

- **`AgentCrew._on_complete_hooks: List[Callable]`** — list of callbacks invoked
  when crew execution finishes with status `completed` or `partial`
- **`AgentCrew._on_error_hooks: List[Callable]`** — list of callbacks invoked
  when crew execution finishes with status `failed` (or `partial`)
- **`AgentCrew.on_complete(callback)`** — registration method
- **`AgentCrew.on_error(callback)`** — registration method
- **`AgentCrew._fire_hooks(result: CrewResult)`** — private dispatch method
  invoked from all four execution modes

### What Changes

- **`AgentCrew.__init__`** — initialize `_on_complete_hooks` and `_on_error_hooks`
  as empty lists. *Evidence*: F001
- **`run_sequential` tail** (lines ~1366-1378) — add `await self._fire_hooks(result)`.
  *Evidence*: F002
- **`run_loop` tail** (lines ~1823-1835) — add `await self._fire_hooks(result)`.
  *Evidence*: F002
- **`run_parallel` tail** (lines ~2136-2148) — add `await self._fire_hooks(result)`.
  *Evidence*: F002
- **`run_flow` tail** (lines ~2371-2383) — add `await self._fire_hooks(result)`.
  *Evidence*: F002

### What's Untouched (Non-Goals)

- **Per-agent `on_agent_complete` callback** — flow-only, stays as-is
- **Node pre/post action hooks** — per-node granularity, untouched
- **AbstractBot event listener system** — operates at agent level, not crew
- **CrewDefinition / from_definition** — hooks are runtime, not serialized
- **CrewResult model** — no changes needed; hooks receive it as-is

### Patterns to Follow

- **`Node.run_post_actions` pattern** (flows/core/node.py:121-135) — iterate
  list, call each, handle async via `asyncio.iscoroutine()`, log errors. *Evidence*: F003
- **`AbstractBot._trigger_event` error handling** (abstract.py:828-834) —
  try/except per callback, `self.logger.error()` on failure. *Evidence*: F003

### Integration Risks

- **Hook ordering is list-order**: callbacks fire in registration order. If a
  user registers a hook that depends on a prior hook's side effects, ordering
  matters. *Mitigation*: document that hooks fire in registration order.
- **Long-running hooks delay return**: hooks run before `return result`.
  *Mitigation*: document that hooks should be lightweight; for heavy work,
  use `asyncio.create_task()` inside the hook. Consider an optional
  `fire_and_forget` parameter on registration in a future iteration.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | All four execution modes share identical tail pattern (build result → synthesize → persist → return) | F002 | high | Directly read all four methods |
| C2 | No crew-level lifecycle hooks exist today | F001, F003 | high | Grep + read confirmation |
| C3 | ActionCallback type handles sync+async callables | F003 | high | Type definition reads `Callable[..., Union[None, Awaitable[None]]]` |
| C4 | Hook errors must not block result return | F003 | high | Consistent with existing try/except pattern in AbstractBot |
| C5 | on_complete should fire for 'completed' and 'partial' statuses | F004 | high | 'partial' still has usable results |
| C6 | CrewResult is the right argument for hooks | F004 | high | Contains all execution state (output, errors, status, metadata) |
| C7 | FEAT-156 from_definition is orthogonal | F005 | high | Hooks are runtime callables; definitions are serialized configs |

Distribution: **7** high, **0** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

*None — all questions answered by codebase research.*

### Unresolved (defer to spec / implementation)

*None.*

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-157`** — *Rationale*: localization is high-confidence across
all seven claims, scope is well-bounded (one file + tests), and there are no
architectural forks to explore. The implementation follows established patterns
already in the codebase.

### Alternatives

- **`/sdd-brainstorm FEAT-157`** — if you want to explore event-bus vs callback-list
  approaches, or discuss advanced features like hook priorities, filter predicates,
  or fire-and-forget semantics.
- **`/sdd-task FEAT-157`** — if you accept this proposal as-is and want to go
  directly to task decomposition (reasonable given the clear scope).

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-157/state.json` |
| Source (raw) | `sdd/state/FEAT-157/source.md` |
| Findings (digests) | `sdd/state/FEAT-157/findings/F001-*.md` through `F005-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-157/synthesis.json` |

**Budget consumed**:
- Files read: 12 / 40
- Grep calls: 5 / 25
- Git calls: 0 / 10
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (verb "add" + new
capability request, no bug or regression signals).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Operator | Claude Code |
