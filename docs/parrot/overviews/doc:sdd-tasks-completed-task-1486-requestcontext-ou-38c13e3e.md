---
type: Wiki Overview
title: 'TASK-1486: Add output_mode / intent_score fields to RequestContext'
id: doc:sdd-tasks-completed-task-1486-requestcontext-output-mode-fields-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements spec §3 Module 3 and the U3 resolution: the resolved output mode
  is'
relates_to:
- concept: mod:parrot.utils.helpers
  rel: mentions
---

# TASK-1486: Add output_mode / intent_score fields to RequestContext

**Feature**: FEAT-224 — IntentRouterMixin Embedding-Based Output-Mode Routing
**Spec**: `sdd/specs/intent-router-mixin-embedding-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3 and the U3 resolution: the resolved output mode is
mirrored onto the per-request carrier so any layer in the stack can read it via
`current_context()`. `RequestContext` is a plain (non-Pydantic) class; this adds
two attributes defaulting to `None`.

---

## Scope

- In `RequestContext.__init__` (`utils/helpers.py`), initialize
  `self.output_mode = None` and `self.intent_score = None`.
- Keep the plain-class shape (no Pydantic migration, no new constructor params).
- Add a unit test asserting the new attributes default to `None`.

**NOT in scope**: writing to these fields (that happens in TASK-1487 base hook /
TASK-1488 mixin), any Pydantic conversion, changing `current_context()` /
`_current_ctx`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/utils/helpers.py` | MODIFY | Add 2 attributes in `RequestContext.__init__` |
| `packages/ai-parrot/tests/utils/test_requestcontext_fields.py` | CREATE | defaults are `None` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.utils.helpers import RequestContext, current_context, _current_ctx  # verified: utils/helpers.py:7,47,51
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/utils/helpers.py:7
class RequestContext:
    def __init__(self, request=None, app=None, llm=None,
                 user_id=None, session_id=None, **kwargs):   # line 20
        self.request = request
        self.app = app
        self.llm = llm
        self.user_id = user_id
        self.session_id = session_id
        self.kwargs = kwargs
        # ADD: self.output_mode = None ; self.intent_score = None

# line 47: _current_ctx: ContextVar[Optional[RequestContext]]
# line 51: def current_context() -> Optional[RequestContext]
```

### Does NOT Exist
- ~~`RequestContext.output_mode`~~ / ~~`RequestContext.intent_score`~~ — do not
  exist yet; this task adds them.
- ~~`RequestContext` as a Pydantic model~~ — it is a plain class; keep it plain.

---

## Implementation Notes

### Pattern to Follow
```python
# inside RequestContext.__init__, after self.kwargs = kwargs
self.output_mode = None     # set by the output-mode router when it resolves a mode
self.intent_score = None    # max-cosine score for the resolved mode (audit/telemetry)
```

### Key Constraints
- Default `None` so absence of routing is indistinguishable from pre-change behavior.
- Type hint optional: `self.output_mode: "OutputMode | None" = None` is fine but do
  NOT add a hard import of `OutputMode` into `helpers.py` if it risks a cycle —
  a plain `= None` is acceptable (mode stored as enum or its value at write time).

---

## Acceptance Criteria

- [ ] `RequestContext().output_mode is None` and `RequestContext().intent_score is None`.
- [ ] Existing attributes (`request/app/llm/user_id/session_id/kwargs`) unchanged.
- [ ] No import cycle introduced in `helpers.py`.
- [ ] `pytest packages/ai-parrot/tests/utils/test_requestcontext_fields.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/utils/helpers.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/utils/test_requestcontext_fields.py
from parrot.utils.helpers import RequestContext


def test_new_fields_default_none():
    ctx = RequestContext()
    assert ctx.output_mode is None
    assert ctx.intent_score is None


def test_existing_fields_preserved():
    ctx = RequestContext(user_id="u1", session_id="s1")
    assert ctx.user_id == "u1" and ctx.session_id == "s1"
    assert ctx.kwargs == {}
```

---

## Agent Instructions

Standard SDD flow. Verify the contract, implement, make tests pass, move file to
`completed/`, update index to `done`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Opus)
**Date**: 2026-06-05
**Notes**: Added `self.output_mode = None` and `self.intent_score = None` to
`RequestContext.__init__` (plain class, no Pydantic migration, no import cycle).
2 unit tests pass; ruff clean.
**Deviations from spec**: none
