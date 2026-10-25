# TASK-4686: Request-local FormDesigner turn context

**Feature**: FEAT-734 — Serve FormDesigner forms from a Teams agent
**Spec**: `sdd/specs/formdesigner-serve-forms.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Delivery contracts, **"Normal-turn toolkit lifecycle"**: when the LLM
calls `formdesigner_get_form` during an ordinary chat turn, the tool must
(a) see the speaking user's tenant/bearer without the LLM ever passing them,
and (b) queue a card the mixin sends after the turn — never leaking into
another turn or a late detached task. This task builds that request-local
object and its `ContextVar`. It is pure (no Bot Framework), so the mixin
(TASK-4691) and the toolkit tests can share it.

Split out of M4 to keep the mixin under the blueprint size cap. Leaf, wave 1.

---

## Scope

- Create `formdesigner_turn.py` with the `FormDesignerTurn` dataclass, the
  module-level `ContextVar`, `active_turn()` and the async context manager
  `bind_turn(turn)`.
- `enqueue(uid)` dedupes in first-request order and returns `False` once closed.
- `close()` marks closed, clears bearer and queue. `bind_turn` ALWAYS closes and
  resets the ContextVar token in `finally` (error, exception, cancellation).
- Write `tests/msteams/test_formdesigner_turn.py`.

**NOT in scope**: resolving identity (mixin), sending cards (mixin), the toolkit.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_turn.py` | CREATE | FormDesignerTurn, active_turn, bind_turn |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_turn.py` | CREATE | turn isolation tests |


---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import AsyncIterator
```

### Existing Signatures to Use
None — new pure module.

### Does NOT Exist
- ~~`FormDesignerTurn`~~, ~~`bind_turn`~~, ~~`active_turn`~~ — created here.
- ~~A request-scoped context in `parrot.integrations.msteams` for tools~~ — none exists; do not reuse `parrot.auth.context.UserContext` (different purpose).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_turn.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-integrations/tests/msteams/test_formdesigner_turn.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Tasks spawned inside the turn copy the *context*, so they see the *same*
  `FormDesignerTurn` object (shared queue). After `close()`, a late task's
  `active_turn()` returns `None` because `closed` is checked — that is the
  isolation guarantee; do not try to "detect" late tasks any other way.
- Do not store the `TurnContext` on the object — only plain values.

---

## Implementation Blueprint

### Steps (in order)
1. Write the dataclass with `enqueue`/`drain`/`close` — *why*: the toolkit calls `enqueue`, the mixin calls `drain`.
2. Write the ContextVar + `active_turn` + `bind_turn` — *why*: one place owns reset-in-finally.
3. Test isolation across concurrent `asyncio` tasks and late tasks.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_turn.py` (CREATE)
```python
"""Request-local FormDesigner context for one Teams turn (FEAT-734 normal-turn toolkit lifecycle)."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class FormDesignerTurn:
    """Identity + pending-card queue for exactly one turn. Plain values only."""

    conversation_id: str
    tenant: str | None = None
    tenant_source: str | None = None
    bearer: str | None = None
    user_id: str | None = None
    login_required: bool = False
    error: str | None = None
    pending: list[uuid.UUID] = field(default_factory=list)
    closed: bool = False

    def enqueue(self, form_uid: uuid.UUID) -> bool:
        """Queue a card; False when closed. Dedupes, first-request order."""
        # FILL IN: closed -> False; already queued -> True without duplicating; else append, True
        raise NotImplementedError

    def drain(self) -> list[uuid.UUID]:
        """Return and clear the queue."""
        items, self.pending = self.pending, []
        return items

    def close(self) -> None:
        """Mark closed and drop credentials and queue."""
        self.closed = True
        self.bearer = None
        self.pending = []


_CURRENT: ContextVar[FormDesignerTurn | None] = ContextVar("formdesigner_turn", default=None)


def active_turn() -> FormDesignerTurn | None:
    """The bound, still-open turn, or None (unbound or closed)."""
    turn = _CURRENT.get()
    return turn if turn is not None and not turn.closed else None


@asynccontextmanager
async def bind_turn(turn: FormDesignerTurn) -> AsyncIterator[FormDesignerTurn]:
    """Bind `turn` for the block; always close it and reset the ContextVar."""
    token = _CURRENT.set(turn)
    try:
        yield turn
    finally:
        turn.close()
        _CURRENT.reset(token)
```
**Why this shape**: spec says "A ContextVar holds a fresh per-turn object; its queue is shared with awaited tool tasks but never with another turn … mark the context closed, clear its bearer and queue, and reset the ContextVar token in finally." Each line of `bind_turn` maps to that sentence.

### `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_turn.py` (CREATE)
```python
"""FEAT-734 — FormDesignerTurn isolation."""
import asyncio
import uuid

import pytest

from parrot.integrations.msteams.formdesigner_turn import FormDesignerTurn, active_turn, bind_turn


async def test_enqueue_dedupes_in_order(): ...           # FILL IN
async def test_closed_turn_refuses_enqueue(): ...        # FILL IN
async def test_bind_turn_resets_on_exception(): ...      # FILL IN: raise inside; active_turn() is None after; bearer cleared
async def test_concurrent_turns_are_isolated(): ...      # FILL IN: two tasks each bind their own turn; queues never mix
async def test_late_task_sees_no_active_turn(): ...      # FILL IN: task created inside, awaited after exit -> active_turn() None
async def test_cancellation_closes_turn(): ...           # FILL IN
```

### FILL IN checklist
- [ ] `FormDesignerTurn.enqueue`
- [ ] six test bodies

---

## Acceptance Criteria

- [ ] Concurrent turns never share a queue or bearer.
- [ ] After `bind_turn` exits by any path: `closed`, `bearer is None`, empty queue, `active_turn() is None`.
- [ ] `ruff check` clean.

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/msteams/test_formdesigner_turn.py -q`


---

## Test Specification

Six tests in the blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug formdesigner-serve-forms --feature-id FEAT-734`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in
   `sdd/tasks/index/formdesigner-serve-forms.json`
4. **Verify the Codebase Contract** — confirm every import/signature before writing code; never use anything under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, never change a fixed signature or path
7. **Verify** — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src`
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4686 formdesigner-serve-forms verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any


### Completion Note
Implemented by the sdd-coder pool; merged to the feature branch, file-fidelity gate green, merge-tier validation green, review recorded (0 corrections).
