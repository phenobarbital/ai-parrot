---
type: Wiki Overview
title: 'TASK-1451: Implement SessionManager for BrowserContext lifecycle'
id: doc:sdd-tasks-completed-task-1451-session-manager-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FlowExecutor needs multiple BrowserContexts (one per "session" label). SessionManager
  owns
relates_to:
- concept: mod:parrot_tools.scraping.flow_models
  rel: mentions
- concept: mod:parrot_tools.scraping.session_manager
  rel: mentions
---

# TASK-1451: Implement SessionManager for BrowserContext lifecycle

**Feature**: FEAT-222 — ScrapingFlow: Composable Long-Horizon Scraping
**Spec**: `sdd/specs/scrapingflow-composable-scraping.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1450
**Assigned-to**: unassigned

---

## Context

FlowExecutor needs multiple BrowserContexts (one per "session" label). SessionManager owns
the Playwright Browser instance, lazily creates/caches BrowserContexts by label, and closes
them deterministically when the last node using that session completes.

Implements spec §Module 7 (SessionManager).

---

## Scope

- Create `SessionManager` class:
  - `__init__(browser, default_context_kwargs=None, session_configs=None)`
  - `get_context(session)` → lazy create, return cached BrowserContext
  - `new_page(session)` → create a Page in the session's context
  - `precompute_last_use(topo_order)` → scan ordered FlowNodes, set `last_use[session] = node.id`
  - `close_if_last(session, node_id)` → close context if this was its last node
  - `close_all()` → cleanup all remaining contexts
- Write unit tests with mocked Playwright Browser

**NOT in scope**: FlowExecutor (TASK-1452), PageDriver (TASK-1450 — but referenced as type)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/session_manager.py` | CREATE | SessionManager implementation |
| `packages/ai-parrot-tools/tests/scraping/test_session_manager.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.flow_models import FlowNode  # created in TASK-1449
```

### Does NOT Exist
- ~~`parrot_tools.scraping.session_manager`~~ — this is what you're creating
- ~~`PlaywrightDriver.new_context()`~~ — PlaywrightDriver only supports one context
- ~~`AbstractDriver.get_context()`~~ — not in the abstract interface

---

## Implementation Notes

### Key Constraints
- Contexts are lazily created on first `get_context()` call for a session label
- `default_context_kwargs` applies to all contexts (viewport, locale, etc.)
- `session_configs` allows per-session overrides (e.g., storage_state for auth sessions)
- `close_if_last` must be called after each node completes; if `last_use[session] == node_id`,
  close that context and remove from cache
- `close_all()` is the safety net for cleanup (called in finally block by FlowExecutor)
- All context operations are async (Playwright API)

---

## Acceptance Criteria

- [ ] `get_context()` creates on first call, returns cached on subsequent calls
- [ ] Different session labels get different BrowserContexts
- [ ] `new_page()` creates a page in the correct session's context
- [ ] `precompute_last_use()` correctly identifies the last node per session
- [ ] `close_if_last()` closes context only after its last node
- [ ] `close_all()` cleans up all remaining contexts
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_session_manager.py -v`

---

## Completion Note

Created `session_manager.py` with `SessionManager`:

- `__init__(browser, default_context_kwargs=None, session_configs=None)`.
- `get_context(session)` lazily creates a context (merging
  `default_context_kwargs` with the per-session override from
  `session_configs`), caches and returns it; subsequent calls reuse the cache.
- `new_page(session)` → `await (await get_context(session)).new_page()`.
- `precompute_last_use(topo_order)` iterates nodes in execution order so the
  final per-session assignment is the last-using node; returns the mapping.
- `close_if_last(session, node_id)` closes + evicts the context only when the
  node is the recorded last user (no-op otherwise / for unknown sessions).
- `close_all()` closes every remaining context, suppressing per-context close
  errors, then clears the cache.

10 unit tests pass against a mocked Browser (lazy/cache, distinct sessions,
default+override kwargs, last-use, close-if-last gating, close_all + error
suppression); ruff clean.
