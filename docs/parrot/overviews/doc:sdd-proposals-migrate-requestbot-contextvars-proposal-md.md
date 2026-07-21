---
type: Wiki Overview
title: FEAT-175 — Migrate RequestBot to ContextVar-based RequestContext Propagation
id: doc:sdd-proposals-migrate-requestbot-contextvars-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original request, preserved verbatim. The full source is at
---

---
id: FEAT-175
title: Migrate RequestBot proxy wrapper to ContextVar-based RequestContext propagation
slug: migrate-requestbot-contextvars
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-15
  summary_oneline: Replace RequestBot dynamic proxy with ContextVar for per-task RequestContext isolation
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-175/
created: 2026-05-15
updated: 2026-05-15
---

# FEAT-175 — Migrate RequestBot to ContextVar-based RequestContext Propagation

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` — user-provided architectural proposal
> **Audit**: [`sdd/state/FEAT-175/`](../state/FEAT-175/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at
`sdd/state/FEAT-175/source.md`.

> Current AbstractBot is wrapped with a RequestBot, idea is migrating to a
> ContextVar. This is exactly what contextvars.ContextVar exists for, and it's
> how aiohttp, FastAPI/Starlette, and SQLAlchemy async sessions solve the
> identical problem. You get per-task isolation for free, you don't need an
> external wrapper, and a single long-lived bot instance can serve many
> concurrent requests safely.
>
> The pattern: stash the active RequestContext in a module-level ContextVar,
> expose a scoped async context manager on the bot that sets/resets the token,
> and have ask() fall back to reading the var when no ctx= was passed explicitly.

**Initial signals** (extracted, not interpreted):
- Verbs: "migrate", "replace", "stash", "expose", "fall back"
- Named entities: RequestBot, RequestContext, ContextVar, AbstractBot, AgentTalk
- Components: `parrot/utils/helpers.py`, `parrot/bots/abstract.py`, `parrot/handlers/agent.py`
- Acceptance criteria provided: yes — 4 implementation steps with code sketches

---

## 1. Synthesis Summary

The current request-scoping mechanism uses `RequestBot`, a `__getattr__`-based
dynamic proxy that wraps every method call on an `AbstractBot` delegate to inject
a `RequestContext` into kwargs. This works but has costs: wrapper closures are created
on every attribute access, type hints and docstrings are lost, `isinstance()` requires
a virtual-subclass hack, and the pattern is unusual enough to confuse contributors.
The codebase already uses `contextvars.ContextVar` in four places for the same
per-async-task isolation pattern [F008]. The proposal replaces the proxy with a
module-level `_current_ctx` ContextVar, a `session()` context manager on AbstractBot
that sets/resets the token (and absorbs PBAC + semaphore from `retrieval()`), and a
one-line fallback in each entry point (`ask`, `ask_stream`, `conversation`, `invoke`).
`RequestBot` is removed entirely per user decision.

---

## 2. Codebase Findings

> All entries in this section are grounded in the research findings persisted
> at `sdd/state/FEAT-175/findings/`. Each cites the finding ID(s) that justify
> its inclusion. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `parrot/utils/helpers.py` | `RequestContext` | 5-41 | Request-scoped data container; stays as-is | F002 |
| 2 | `parrot/utils/helpers.py` | `RequestBot` | 43-78 | Dynamic proxy to **remove** | F001 |
| 3 | `parrot/bots/abstract.py` | `retrieval()` | 3103-3205 | Creates RequestBot + PBAC + semaphore; to be **replaced by session()** | F003 |
| 4 | `parrot/bots/abstract.py` | `ask()` | 3474-3493 | Abstract entry point; add ContextVar fallback | F004 |
| 5 | `parrot/bots/abstract.py` | `ask_stream()` | 3521-3538 | Abstract entry point; add ContextVar fallback | F004 |
| 6 | `parrot/bots/abstract.py` | `conversation()` | 2943-2962 | Abstract entry point; add ContextVar fallback | F004 |
| 7 | `parrot/bots/abstract.py` | `invoke()` | 3218-3228 | Abstract entry point; add ContextVar fallback | F004 |
| 8 | `parrot/bots/abstract.py` | `AbstractBot.register(RequestBot)` | 3755-3759 | Virtual subclass hack; **remove** | F011 |
| 9 | `parrot/bots/base.py` | `ask()` | 653-699 | Concrete impl; forwards ctx to `_build_kb_context()` | F005 |
| 10 | `parrot/bots/base.py` | `ask_stream()` | 1157-1175 | Concrete impl; forwards ctx | F005 |
| 11 | `parrot/handlers/agent.py` | `AgentTalk.post()` | 1504-1563 | Primary consumer; switch from `retrieval()` to `session()` | F006 |
| 12 | `parrot/stores/kb/*.py` | `search(ctx=)` | various | KB consumers of ctx; no change needed | F009 |
| 13 | `parrot/tools/abstract.py` | `execute()` | 375-421 | Tools gain `current_context()` access (new capability) | F010 |
| 14 | `parrot/integrations/` | Slack, Telegram, Teams, WhatsApp | various | Can optionally adopt `session()` | F007 |
| 15 | `handlers/web_hitl.py`, `clients/nvidia.py`, `telegram/context.py`, `tools/dataset_manager/` | Existing ContextVar instances | various | 4 precedents for the pattern | F008 |

### 2.2 Constraints Discovered

- **PBAC enforcement is in retrieval().** `retrieval()` (lines 3141-3197) enforces
  policy-based access control before yielding the bot. The new `session()` method
  must absorb this responsibility entirely, since `retrieval()` is being replaced.
  *Evidence*: F003

- **Concurrency semaphore is in retrieval().** `retrieval()` yields under
  `self._semaphore` (line 3200) to limit concurrent requests per bot instance.
  `session()` must own the semaphore.
  *Evidence*: F003

- **RequestContext lifecycle is no-op.** `__aenter__` returns self, `__aexit__` is
  a pass. The `async with ctx:` in the proposed `session()` is safe — it simply
  enters and exits immediately.
  *Evidence*: F002

- **ctx flows to KBs via _build_kb_context().** `_build_kb_context()` passes ctx to
  `kb.should_activate()` and `kb.search()`. This chain works regardless of whether
  ctx came from RequestBot injection or ContextVar fallback — no changes needed.
  *Evidence*: F005, F009

- **ctx does NOT flow to LLM client, memory, or prompt pipeline.** These subsystems
  receive extracted `user_id`/`session_id` but not the RequestContext object. This
  means the ContextVar migration has no impact on them.
  *Evidence*: F005

- **Integration handlers bypass retrieval() entirely.** Slack, Telegram, Teams,
  WhatsApp call `agent.ask()` directly without ctx. With the ContextVar fallback,
  they'll simply get `ctx = None` — same behavior as today.
  *Evidence*: F007

### 2.3 Recent History (Relevant)

The research did not surface recent commits modifying RequestBot, retrieval(), or
RequestContext. These are stable, long-lived abstractions. This is good — it means
the migration won't conflict with in-flight changes.

---

## 3. Probable Scope

### What's New

- **`_current_ctx` ContextVar** in `parrot/utils/helpers.py` — module-level
  `ContextVar[Optional[RequestContext]]` with `default=None`
- **`current_context()` accessor** in `parrot/utils/helpers.py` — convenience
  function returning `_current_ctx.get()`
- **`AbstractBot.session()` async context manager** — binds RequestContext to the
  ContextVar for the block's lifetime, absorbs PBAC enforcement and semaphore
  from `retrieval()`

### What Changes

- **`parrot/utils/helpers.py`::RequestBot** — class removed entirely. *Evidence*: F001
- **`parrot/bots/abstract.py`::retrieval()** — removed, replaced by `session()`. *Evidence*: F003
- **`parrot/bots/abstract.py`::AbstractBot.register(RequestBot)** — removed (virtual subclass no longer needed). *Evidence*: F011
- **`parrot/bots/abstract.py`::ask()** — add `if ctx is None: ctx = _current_ctx.get()` fallback. *Evidence*: F004
- **`parrot/bots/abstract.py`::ask_stream()** — same fallback. *Evidence*: F004
- **`parrot/bots/abstract.py`::conversation()** — same fallback. *Evidence*: F004
- **`parrot/bots/abstract.py`::invoke()** — same fallback. *Evidence*: F004
- **`parrot/handlers/agent.py`::AgentTalk.post()** — replace `agent.retrieval(...)` with `agent.session(...)`. *Evidence*: F006
- **`parrot/bots/abstract.py`::imports** — remove `RequestBot` import, add ContextVar import. *Evidence*: F001

### What's Untouched (Non-Goals)

- **RequestContext class itself** — stays as-is, just gains a ContextVar wrapper
- **Knowledge base interfaces** — `search(ctx=)` signature unchanged; KBs keep receiving ctx explicitly
- **Memory classes** — don't use ctx today, won't start
- **LLM client layer** — no ctx involvement
- **Integration handlers** — optional future adoption; not in this scope
- **Prompt pipeline middleware** — unaffected

### Patterns to Follow

- **Existing ContextVar pattern** — `handlers/web_hitl.py:current_web_session` shows the
  exact module-level ContextVar + accessor + set/reset pattern. Follow it.
  *Evidence*: F008

- **Existing `@asynccontextmanager` pattern** — `retrieval()` already uses this decorator.
  `session()` should follow the same structure.
  *Evidence*: F003

- **dataset_manager `_pctx_var`** — shows ContextVar for per-call isolation on a shared
  tool instance, the closest analogue to per-request isolation on a shared bot.
  *Evidence*: F008

### Integration Risks

- **PBAC logic duplication/loss**: if PBAC code is not correctly ported from `retrieval()`
  to `session()`, access control breaks. Mitigation: copy the PBAC block verbatim into
  `session()` and add tests.
  *Evidence*: F003

- **Semaphore omission**: if `session()` forgets the semaphore, bot concurrency is
  unbounded. Mitigation: port the `async with self._semaphore:` block.
  *Evidence*: F003

- **Tools calling `current_context()` before session is entered**: if a tool is invoked
  outside a `session()` block, `current_context()` returns None. This is safe (same as
  today), but tools must handle None.
  *Evidence*: F010

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `_current_ctx` ContextVar provides per-task isolation | F008 | high | Python semantics guarantee + 4 codebase precedents |
| C2 | `session()` context manager avoids races on shared bot instances | F002, F003 | high | ContextVar copy-on-task-spawn is guaranteed by asyncio |
| C3 | Explicit `ctx=` parameter still wins over ambient context | F004 | high | Trivial fallback logic: `if ctx is None: ctx = _current_ctx.get()` |
| C4 | Existing call sites won't break | F001, F005 | high | ctx injection via RequestBot is replaced by ContextVar fallback; same observable behavior |
| C5 | PBAC enforcement can be moved into session() without loss | F003 | high | PBAC code is self-contained within retrieval(); direct port |
| C6 | Semaphore can be moved into session() | F003 | high | Single `async with self._semaphore:` wrapping the yield |
| C7 | Tools can access `current_context()` for user_id | F010 | medium | New capability, not yet tested; tools must handle None |

Distribution: **5** high, **2** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **How should PBAC + semaphore from retrieval() be handled?** — *Resolved*: Move everything into `session()`. `retrieval()` is removed entirely.
  *Resolves claims*: C5, C6

- [x] **What happens to RequestBot?** — *Resolved*: Remove immediately. No deprecation period.
  *Resolves claims*: C4

### Unresolved (defer to spec / implementation)

*(None — all material unknowns resolved during proposal phase.)*

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-175`** — *Rationale*: Localization is high-confidence (C1-C6), the
scope is well-bounded (6 files, one new ContextVar, one new method, one removal),
the user provided implementation code sketches, and all unknowns are resolved.
This is ready for a detailed specification.

### Alternatives

- **`/sdd-task FEAT-175`** — if you want to skip the spec and go straight to tasks.
  Viable here because the user's inline description is already spec-quality, but
  a formal spec would capture PBAC porting details.
- **`/sdd-brainstorm FEAT-175`** — not recommended. The architectural decision is made;
  there are no alternative approaches to explore.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-175/state.json` |
| Source (raw) | `sdd/state/FEAT-175/source.md` |
| Findings (digests) | `sdd/state/FEAT-175/findings/F001-*.md` through `F011-*.md` |

**Budget consumed**:
- Files read: 22 / 40
- Grep calls: 18 / 25
- Git calls: 3 / 10
- Truncated: **no**

**Mode determination**: `enrichment` — user-provided architectural improvement
with detailed implementation guidance, not a bug investigation.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Research method | 3 parallel Explore agents (RequestBot/AbstractBot, handlers/AgentTalk, ctx flow/tools) |
| Operator | Claude Opus 4.6 |
