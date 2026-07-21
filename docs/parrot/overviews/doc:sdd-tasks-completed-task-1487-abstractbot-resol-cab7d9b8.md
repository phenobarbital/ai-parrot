---
type: Wiki Overview
title: 'TASK-1487: AbstractBot._resolve_output_mode no-op hook + ask()/conversation()
  call sites'
id: doc:sdd-tasks-completed-task-1487-abstractbot-resolve-output-mode-hook-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 4 (G3). Declares the single narrow template-method
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.utils.helpers
  rel: mentions
---

# TASK-1487: AbstractBot._resolve_output_mode no-op hook + ask()/conversation() call sites

**Feature**: FEAT-224 — IntentRouterMixin Embedding-Based Output-Mode Routing
**Spec**: `sdd/specs/intent-router-mixin-embedding-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1486
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4 (G3). Declares the single narrow template-method
extension point on the base class and wires it into BOTH `ask()` and
`conversation()` — guarded so it only runs when the caller did not specify a
mode. Default is a verified no-op, so behavior is identical when no mixin is
present. Keep the edit minimal: the base churns (visualization work).

---

## Scope

- Add `async def _resolve_output_mode(self, query, ctx) -> "OutputMode | None"`
  to `AbstractBot` (`bots/abstract.py`) returning `None` (no-op default).
- In `AbstractBot.ask()` and `AbstractBot.conversation()`: when the incoming
  `output_mode == OutputMode.DEFAULT`, call `resolved = await
  self._resolve_output_mode(question, ctx)`; if `resolved is not None`, set the
  local `output_mode = resolved` and, when `ctx` is not None, mirror
  `ctx.output_mode = resolved` (and `ctx.intent_score` if the mixin attached one
  — see note). Call the hook **exactly once** per request.
- Add unit tests asserting the base hook is a no-op and that the guard respects
  an explicit caller mode.

**NOT in scope**: the embedding engine, config fields (TASK-1485), the mixin
override + LLM tie-break (TASK-1488). Do NOT implement routing logic here — only
the no-op hook and the guarded call sites.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add no-op hook + 2 guarded call sites in `ask()`/`conversation()` |
| `packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py` | CREATE | base no-op + explicit-mode precedence |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.outputs import OutputMode          # verified: models/outputs.py:37 (already imported in abstract.py)
from parrot.utils.helpers import RequestContext        # verified: utils/helpers.py:7 (already imported in abstract.py:56)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot(...):
    async def configure(self, app=None) -> None: ...                  # line 1231

    async def conversation(self, question: str, ...,                  # line 3107
                           ctx: Optional[RequestContext] = None,
                           output_mode: OutputMode = OutputMode.DEFAULT, ...): ...

    async def ask(self, question: str, ...,                           # line 3660
                  ctx: Optional[RequestContext] = None,
                  output_mode: OutputMode = OutputMode.DEFAULT, ...): ...

# RequestContext now carries .output_mode / .intent_score (TASK-1486, utils/helpers.py)
```

### Does NOT Exist
- ~~`AbstractBot._resolve_output_mode`~~ — does not exist yet; this task adds the no-op.
- ~~a full `ask()` override pattern for routing~~ — rejected (spec §2/§7); use the
  template-method hook only.
- Do not assume `ctx` is always non-None — both methods default `ctx=None`; guard writes.

---

## Implementation Notes

### Pattern to Follow
```python
# no-op extension point (place near other AbstractBot REQUEST helpers)
async def _resolve_output_mode(self, query: str,
                               ctx: "RequestContext | None") -> "OutputMode | None":
    """Extension point for pre-LLM output-mode routing. Default: no-op."""
    return None

# at the TOP of ask() and conversation(), after ctx is available and BEFORE
# downstream rendering consumes output_mode:
if output_mode == OutputMode.DEFAULT:
    resolved = await self._resolve_output_mode(question, ctx)
    if resolved is not None:
        output_mode = resolved
        if ctx is not None:
            ctx.output_mode = resolved
```

### Key Constraints
- The guard `output_mode == OutputMode.DEFAULT` is the precedence rule: explicit
  caller arg > router > default. Never overwrite a non-DEFAULT caller value.
- Exactly one call per request per method. Do not call inside loops/retries.
- `intent_score` is attached by the mixin onto `ctx` directly (TASK-1488); this
  task only guarantees the call-site + `ctx.output_mode` mirroring.
- Keep diffs surgical; the base file is under active churn.

### References in Codebase
- `bots/data.py:1857`, `bots/base.py:409` — existing `response.output_mode = output_mode`
  assignment sites that consume the resolved mode downstream (do not change them).

---

## Acceptance Criteria

- [ ] `AbstractBot._resolve_output_mode` exists and returns `None`.
- [ ] `ask()` and `conversation()` call it exactly once, only when
      `output_mode == OutputMode.DEFAULT`.
- [ ] With no mixin present, behavior is identical to pre-change (no-op verified).
- [ ] An explicit `output_mode != DEFAULT` is never overwritten.
- [ ] When a mode resolves and `ctx` is not None, `ctx.output_mode` is set.
- [ ] `pytest packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/abstract.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_resolve_output_mode_noop.py
import pytest
from parrot.models.outputs import OutputMode
from parrot.utils.helpers import RequestContext


class _Dummy:
    # minimal object exposing AbstractBot._resolve_output_mode bound semantics
    pass


async def test_base_hook_is_noop():
    from parrot.bots.abstract import AbstractBot
    # the unbound coroutine returns None regardless of input
    result = await AbstractBot._resolve_output_mode(object(), "create a pie chart", RequestContext())
    assert result is None


def test_default_enum_is_default():
    assert OutputMode.DEFAULT == OutputMode("default")
```

> Note: if `AbstractBot` cannot be instantiated standalone, test the guard logic
> via a lightweight subclass or by asserting the method body returns `None`.

---

## Agent Instructions

Standard SDD flow. Confirm TASK-1486 (ctx fields) is in `completed/` first.
Verify the contract, implement, make tests pass, move file to `completed/`,
update index to `done`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Opus)
**Date**: 2026-06-05
**Notes**: Added the no-op `_resolve_output_mode` hook to `AbstractBot`. Added the
guarded (`output_mode == OutputMode.DEFAULT`) call sites to the REAL implementations.
5 unit tests pass (real AbstractBot forced past the conftest stub via the codebase's
established pop-and-import pattern); ruff clean.
**Deviations from spec (REVIEW FIXES — approved by user 'fix all issues')**:
- The spec/§6 contract claimed `ask()`/`conversation()` impls live in
  `bots/abstract.py:3660,3107`, but those are abstract STUBS (`...`); a guard there
  would be dead code (shadowed in the MRO). Call sites were instead placed in the
  real bodies: `BaseBot.ask` and `BaseBot.conversation` (`bots/base.py`).
- Added `bots/data.py` to scope: `PandasAgent.ask` fully overrides `ask` and is the
  PRIMARY data/viz agent ("create a pie chart of Q1 sales"). Guard placed after its
  `None -> DEFAULT` normalization so the headline use case is actually covered.
File scope amended: abstract.py (hook) + base.py + data.py (call sites).
