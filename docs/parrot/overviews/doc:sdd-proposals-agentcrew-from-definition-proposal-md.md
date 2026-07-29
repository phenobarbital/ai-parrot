---
type: Wiki Overview
title: FEAT-156 — Add AgentCrew.from_definition classmethod
id: doc:sdd-proposals-agentcrew-from-definition-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The original request, preserved verbatim:'
relates_to:
- concept: mod:parrot.agents
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.handlers.crew.models
  rel: mentions
---

---
id: FEAT-156
title: Add AgentCrew.from_definition classmethod to eliminate duplicated creation logic
slug: agentcrew-from-definition
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-11
  summary_oneline: AgentCrew requires a from_definition classmethod to create crews from CrewDefinition
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-156/
created: 2026-05-11
updated: 2026-05-11
---

# FEAT-156 — Add AgentCrew.from_definition classmethod

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — "AgentCrew requires a method from_definition to create/re-create an AgentCrew from a definition"
> **Audit**: [`sdd/state/FEAT-156/`](../state/FEAT-156/)

---

## 0. Origin

The original request, preserved verbatim:

> AgentCrew requires a method `from_definition` to create/re-create an AgentCrew
> from a definition, currently is a code in CrewHandler (HTTP for creating
> AgentCrew instances) but not a method in AgentCrew.

**Initial signals**:
- Verbs: "create/re-create" → factory method enrichment
- Named entities: AgentCrew, CrewHandler, from_definition
- Components / labels: orchestration, handlers/crew
- Acceptance criteria provided: no (implicit: method exists on AgentCrew)

---

## 1. Synthesis Summary

The `_create_crew_from_definition` logic that converts a `CrewDefinition` into a
live `AgentCrew` instance is duplicated in two places: `CrewHandler` (HTTP layer)
and `BotManager` (service layer). Both implementations are ~95% identical — they
iterate agent definitions, resolve classes, create agents, build the crew, add
shared tools, and wire flow relations. This logic belongs on `AgentCrew` itself as
a `@classmethod from_definition(cls, crew_def, *, class_resolver, tool_resolver)`
that accepts callables for resolving class names and tool names, decoupling the
factory from any specific manager. The `CrewDefinition` and related models must
also move from `parrot/handlers/crew/models.py` to `parrot/models/crew.py` since
they are already imported by the manager, orchestrator, and persistence layers.

---

## 2. Codebase Findings

> All entries grounded in `sdd/state/FEAT-156/findings/`.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/bots/orchestration/crew.py` | `AgentCrew` | 148-267 | Target class — no factory methods | F001 |
| 2 | `packages/ai-parrot/src/parrot/handlers/crew/handler.py` | `_create_crew_from_definition` | 76-158 | HTTP-layer factory (duplicate 1) | F002 |
| 3 | `packages/ai-parrot/src/parrot/handlers/crew/handler.py` | `_get_agents_by_ids` | 160-177 | Helper duplicated in both sites | F002 |
| 4 | `packages/ai-parrot/src/parrot/manager/manager.py` | `_create_crew_from_definition` | 2050-2144 | Service-layer factory (duplicate 2) | F003 |
| 5 | `packages/ai-parrot/src/parrot/manager/manager.py` | `_get_agents_by_ids` | 2146-2167 | Helper duplicate | F003 |
| 6 | `packages/ai-parrot/src/parrot/handlers/crew/models.py` | `CrewDefinition` | 66-118 | Definition model (misplaced in handler layer) | F004 |
| 7 | `packages/ai-parrot/src/parrot/handlers/crew/models.py` | `AgentDefinition` | 31-54 | Agent sub-definition | F004 |
| 8 | `packages/ai-parrot/src/parrot/handlers/crew/models.py` | `FlowRelation` | 56-64 | Flow edge definition | F004 |
| 9 | `packages/ai-parrot/src/parrot/handlers/crew/models.py` | `ExecutionMode` | 14-19 | Enum (sequential/parallel/flow/loop) | F004 |

### 2.2 Constraints Discovered

- **`self.agents` is a Dict[str, ...]**, not a List. The constructor accepts a List
  but internally converts to a dict keyed by agent name via `add_agent()`.
  *Implication*: `from_definition` must use `add_agent()` or replicate the keying.
  *Evidence*: F001

- **Class resolution requires external service.** `get_bot_class(name)` uses dynamic
  imports across `parrot.bots` and `parrot.agents`. This cannot be baked into
  AgentCrew — it needs a resolver callable.
  *Evidence*: F002, F003

- **Tool resolution is inconsistent.** CrewHandler resolves shared tools via
  `bot_manager.get_tool()`. BotManager's version is a stub that logs but doesn't
  actually add tools. The `from_definition` method must accept a `tool_resolver`
  callable, with a default no-op fallback.
  *Evidence*: F002, F003

- **Agent tools are passed as names.** `agent_def.tools` is `List[str]` — just names,
  not resolved tool instances. The agent constructor receives these strings.
  *Implication*: agent-level tool resolution is the agent's responsibility, not the
  crew's. Only shared tools need external resolution.
  *Evidence*: F004

- **Models imported outside handler layer.** `CrewDefinition` is imported by
  `manager.py`, `autonomous/orchestrator.py`, and `redis_persistence.py` — it is
  not HTTP-specific despite living under `handlers/crew/`.
  *Evidence*: F004

### 2.3 Recent History (Relevant)

No recent commits touching the creation logic. The `AgentCrew` class and
`CrewHandler` have been stable — no active refactors in progress.

---

## 3. Probable Scope

### What's New

- **`AgentCrew.from_definition()`** — `@classmethod` factory that accepts a
  `CrewDefinition` and resolver callables, returns a fully configured `AgentCrew`.

- **`parrot/models/crew.py`** — New module for `CrewDefinition`, `AgentDefinition`,
  `FlowRelation`, `ExecutionMode` (relocated from `handlers/crew/models.py`).

### What Changes

- **`handlers/crew/handler.py`::`_create_crew_from_definition`** — replaced with
  a call to `AgentCrew.from_definition(crew_def, class_resolver=self.bot_manager.get_bot_class, tool_resolver=self.bot_manager.get_tool)`.
  *Evidence*: F002

- **`manager/manager.py`::`_create_crew_from_definition`** — same replacement.
  *Evidence*: F003

- **`handlers/crew/models.py`** — `CrewDefinition`, `AgentDefinition`,
  `FlowRelation`, `ExecutionMode` move out; re-exports left for backward compat.
  *Evidence*: F004

- **Import paths** across `autonomous/orchestrator.py`, `redis_persistence.py` —
  update to new location or use re-exports.
  *Evidence*: F004

### What's Untouched (Non-Goals)

- **AgentCrew execution logic** — `run_sequential()`, `run_parallel()`, `run_flow()`,
  `run_loop()` remain unchanged.
- **CrewExecutionHandler** — execution endpoint is separate from CRUD handler.
- **Job management models** — `CrewJob`, `CrewQueryRequest`, response models stay
  in `handlers/crew/models.py` (they are genuinely HTTP-specific).
- **`to_definition()` serialization** — desirable but not in scope for this proposal.
  Can be a follow-up.

### Patterns to Follow

- **Resolver-as-callable.** Use `Callable[[str], Optional[Type]]` for class_resolver
  and `Callable[[str], Optional[AbstractTool]]` for tool_resolver. This follows
  Python's dependency injection via callables (no framework needed).
  *Evidence*: F002, F003

- **FlowLoader pattern.** `parrot/bots/flow/loader.py` uses `@classmethod from_dict`,
  `from_json`, `load_from_file` — a validated pattern in this codebase. However,
  `from_definition` on AgentCrew differs: it returns a live orchestrator, not a
  data model.
  *Evidence*: F001

### Integration Risks

- **Import cycle risk**: Moving models to `parrot/models/crew.py` could create a
  cycle if `crew.py` imports from `parrot/models/` and `parrot/models/` imports from
  `parrot/bots/`. *Mitigation*: models should be pure data — no imports from
  `parrot/bots/` needed.

- **Backward compatibility**: External code importing from `parrot.handlers.crew.models`
  breaks if models move without re-exports. *Mitigation*: keep re-exports in the old
  location.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `_create_crew_from_definition` is duplicated in handler and manager | F002, F003 | high | Direct read of both implementations confirms ~95% overlap |
| C2 | AgentCrew has zero factory/classmethods | F001 | high | Full class read, grep for @classmethod returned nothing |
| C3 | `CrewDefinition` models live in handler layer but are used project-wide | F004 | high | grep confirmed 4+ importers outside handlers |
| C4 | `self.agents` is a Dict keyed by name, not a List | F001 | high | Direct read of __init__ and type annotation |
| C5 | Class resolution requires dynamic import via `get_bot_class` | F002, F003 | high | Both implementations delegate to this method |
| C6 | BotManager's shared tool resolution is a stub | F003 | high | Direct read shows placeholder comment at line 2107 |
| C7 | No import cycle risk for model relocation | — | medium | Inferred from model-only imports; not verified with full dependency graph |

Distribution: **5** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

None — no Q&A phase needed; all critical questions answered by codebase research.

### Unresolved (defer to spec / implementation)

- [ ] **Should `from_definition` be async?** — *Owner*: tbd
  *Blocks claims*: —
  *Plausible answers*: a) sync — agent construction is sync, only tool resolution
  might need async · b) async — future-proofs for async tool registries
  *Recommendation*: Start with a sync `@classmethod`. If tool resolution becomes
  async, add `async_from_definition` later.

- [ ] **Should `to_definition()` be included in scope?** — *Owner*: tbd
  *Blocks claims*: —
  *Plausible answers*: a) yes, for round-trip serialization · b) no, follow-up
  *Recommendation*: Defer to a follow-up to keep this focused.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-156`** — *Rationale*: localization is high-confidence (C1-C6),
scope is well-bounded (one classmethod + model relocation), and no architectural
fork needs exploring. The spec should define the method signature, resolver
protocol, and migration plan for imports.

### Alternatives

- **`/sdd-brainstorm FEAT-156`** — unnecessary; the solution shape is clear
  (factory classmethod with injected resolvers). No competing architectures.
- **`/sdd-task FEAT-156`** — viable if you want to skip the spec and go straight
  to implementation. The scope is small enough for 2-3 tasks.
- **Manual review** — not needed; research was complete (no truncation).

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-156/state.json` |
| Source (raw) | `sdd/state/FEAT-156/source.md` |
| Findings (digests) | `sdd/state/FEAT-156/findings/F001-*.md` through `F005-*.md` |

**Budget consumed**:
- Files read: 8 / 40
- Grep calls: 7 / 25
- Git calls: 0 / 10
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (request describes a
missing capability to add, not a bug to investigate).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal` |
| Operator | Claude (FEAT-156 research session) |
| Date | 2026-05-11 |
