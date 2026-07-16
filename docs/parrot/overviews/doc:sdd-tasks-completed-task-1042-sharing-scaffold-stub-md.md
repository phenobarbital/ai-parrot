---
type: Wiki Overview
title: 'TASK-1042: Sharing scaffold (deferred stub)'
id: doc:sdd-tasks-completed-task-1042-sharing-scaffold-stub-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: '"""Agent sharing scaffold — deferred to a follow-up FEAT.'
relates_to:
- concept: mod:parrot.handlers.agents.sharing
  rel: mentions
---

# TASK-1042: Sharing scaffold (deferred stub)

**Feature**: FEAT-149 — Ephemeral User Agents
**Spec**: `sdd/specs/ephemeral-agents.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> The sharing scheme is deferred to a follow-up FEAT (spec §3 Module 9, §8 Open Questions).
> This task creates a stub module that documents the intended interface and links to the
> design decision (per-user permission list under `users_bots.permissions`).

---

## Scope

- Create `parrot/handlers/agents/sharing.py` as a stub module.
- Include a module docstring explaining the deferred sharing design.
- Define placeholder class `AgentSharingHandler(BaseView)` with `NotImplementedError` on all methods.
- Add a `TODO(FEAT-XXX)` comment linking to the follow-up feature.

**NOT in scope**: Actual sharing implementation (deferred to follow-up FEAT).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/agents/sharing.py` | CREATE | Stub module with placeholder |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Only needs the base handler pattern
# Check existing handlers for the actual BaseView import path
```

### Does NOT Exist
- ~~`parrot/handlers/agents/sharing.py`~~ — does not exist yet; this task creates it.
- ~~`AgentSharingHandler`~~ — does not exist yet; this task creates a stub.

---

## Implementation Notes

### Pattern to Follow
```python
"""Agent sharing scaffold — deferred to a follow-up FEAT.

Design decision (FEAT-149 §8): per-user permission list under
``users_bots.permissions``. Implementation details TBD.
"""
from aiohttp import web

class AgentSharingHandler:
    # TODO(FEAT-XXX): implement agent sharing
    async def post(self, request: web.Request) -> web.Response:
        raise NotImplementedError("Agent sharing is not yet implemented")
```

### Key Constraints
- This is a stub only — no functional code.
- Must not introduce any import errors (keep imports minimal).

---

## Acceptance Criteria

- [ ] `parrot/handlers/agents/sharing.py` exists with a stub class and docstring.
- [ ] Module imports without error: `from parrot.handlers.agents.sharing import AgentSharingHandler`
- [ ] No routes are registered for this handler (that's a future task).
- [ ] No linting errors: `ruff check parrot/handlers/agents/sharing.py`

---

## Test Specification

No tests needed for a stub module — just verify it imports cleanly.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/ephemeral-agents.spec.md` §3 Module 9, §8.
2. **Check dependencies** — none for this task.
3. **Update status** in `sdd/tasks/index/ephemeral-agents.json` → `"in-progress"`
4. **Create** the stub module.
5. **Verify** it imports cleanly.
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-05-07
**Notes**: `parrot/handlers/agents/sharing.py` created with `AgentSharingHandler` stub (post/get/delete all raise `NotImplementedError`). Module docstring describes the deferred sharing design and intended API surface. Imports cleanly. No routes registered (deferred to future FEAT).

**Deviations from spec**: none
