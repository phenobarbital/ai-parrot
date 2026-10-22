# TASK-4635: `on_submitted` post-submit callback + `SubmittedEvent`

**Feature**: FEAT-730 — FormDesigner public response controls
**Spec**: `sdd/specs/formdesigner-public-form-controls.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4632, TASK-4634
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. FieldSync (FEAT-796) indexes every `/data` submission of a
public form into its response viewer. It needs a typed host hook after a
successful REST `/data` store. Cross-repo contract (Juan, 2026-10-22): the
event carries NO `anonymous` field — "es público… da igual" — FieldSync indexes
on `is_public` alone.

---

## Scope

- Create `api/submission_events.py` with `SubmittedEvent` and `SubmittedCallback`.
- `FormAPIHandler.__init__`: kwarg `on_submitted: SubmittedCallback | None = None`.
- `submit_data`: before the final 200 reply, await the callback when set and `outcome.stored_in != "none"`; swallow + log any exception.
- `setup_form_api`: kwarg `on_submitted`, passed to `FormAPIHandler`.
- Export `SubmittedEvent`, `SubmittedCallback` from `parrot_formdesigner.api`.
- Tests.

**NOT in scope**: calling the callback from the audio WS (REST `/data` only, per spec).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/submission_events.py` | CREATE | event model + callback type |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | ctor kwarg + call before 200 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | `on_submitted` kwarg plumbing |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/__init__.py` | MODIFY | exports |
| `packages/parrot-formdesigner/tests/unit/api/test_on_submitted.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

> Relative to `packages/parrot-formdesigner/src/parrot_formdesigner/`. Verified @ `685e6176c`
> (line numbers BEFORE TASK-4634 lands — re-grep; TASK-4634 inserts lines in both files).

### Existing Signatures to Use
```python
# api/handlers.py
class FormAPIHandler:                                    # :111
    def __init__(..., sink_factory=None, tenant_scoped_submissions=False)   # after TASK-4634
    async def submit_data(self, request) -> web.Response
    #   outcome = await pipeline.submit(... tenant=tenant ...)     :1837
    #   return _reply(body_out, status=200)                         :1897 (count 1)
# SubmitOutcome.created_at: datetime | None    — added by TASK-4632
# form.is_public: bool (core/schema.py:483); form.form_uid / form_id / version

# api/routes.py — setup_form_api(..., tenant_scoped_submissions: bool = False)  after TASK-4634
#   FormAPIHandler(..., tenant_scoped_submissions=tenant_scoped_submissions,)   after TASK-4634

# api/__init__.py
__all__ = ["setup_form_api"]                             # :24 (count 1)
from .routes import setup_form_api                       # :22
```

### Does NOT Exist
- ~~`SubmittedEvent.anonymous`~~ — DROPPED by decision (Juan, 2026-10-22). Do not add it.
- ~~A host post-submit hook~~ — only the per-form `onAfterSubmit` lifecycle exists today.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/submission_events.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/__init__.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_on_submitted.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler.submit_data",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py#setup_form_api"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Create the event module — *why*: fixed contract consumed by FieldSync FEAT-796.
2. Ctor kwarg + attribute; call before the 200 reply — *why*: AC9 (once per successful store, never on 4xx/5xx).
3. Routes kwarg + pass-through; exports.
4. Tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/submission_events.py` (CREATE)
```python
"""Host post-submit hook for REST /data (FEAT-730)."""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from pydantic import BaseModel


class SubmittedEvent(BaseModel):
    """Emitted after a successful REST /data store. Never on rejection or failure."""

    submission_id: str
    form_uid: uuid.UUID
    form_id: str
    form_version: str
    tenant: str
    is_public: bool
    created_at: datetime


SubmittedCallback = Callable[[SubmittedEvent], Awaitable[None]]

__all__ = ["SubmittedEvent", "SubmittedCallback"]
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` (MODIFY)
```python
# AFTER — insert below `        tenant_scoped_submissions: bool = False,` (ctor signature, added by TASK-4634; re-grep, count 1)
        on_submitted: "SubmittedCallback | None" = None,
# AFTER — insert below `        self._tenant_scoped_submissions = tenant_scoped_submissions` (added by TASK-4634)
        # FEAT-730 — host hook after a successful REST /data store.
        self._on_submitted = on_submitted
```
```python
# occurrences: 1 (verified: grep -c '        return _reply(body_out, status=200)' api/handlers.py)
# BEFORE — insert above `        return _reply(body_out, status=200)` (verified: :1897)
        if self._on_submitted is not None and outcome.stored_in != "none":
            await self._notify_submitted(form, outcome, tenant)
```
```python
# new private method — insert directly above `    async def submit_data(` (re-grep; count 1)
    async def _notify_submitted(self, form: FormSchema, outcome: Any, tenant: str) -> None:
        """Await the host's on_submitted hook; never fails the submit (FEAT-730)."""
        from .submission_events import SubmittedEvent

        try:
            # FILL IN: build SubmittedEvent(submission_id=outcome.submission_id, form_uid=form.form_uid,
            # form_id=form.form_id, form_version=form.version, tenant=tenant, is_public=bool(form.is_public),
            # created_at=outcome.created_at or datetime.now(timezone.utc)) and await self._on_submitted(event).
            pass
        except Exception as exc:  # noqa: BLE001 — the submit already succeeded
            self.logger.warning("on_submitted hook failed for %s: %s", outcome.submission_id, exc)
```
Add `from .submission_events import SubmittedCallback` under the module's `TYPE_CHECKING` block
(re-grep `if TYPE_CHECKING:` in handlers.py) so the annotation resolves.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` (MODIFY)
```python
# AFTER — insert below `    tenant_scoped_submissions: bool = False,` (signature, added by TASK-4634)
    on_submitted: "SubmittedCallback | None" = None,
# AFTER — insert below `        tenant_scoped_submissions=tenant_scoped_submissions,` (FormAPIHandler(...), TASK-4634)
        on_submitted=on_submitted,
```
Add `SubmittedCallback` to routes.py's `TYPE_CHECKING` imports; one docstring line for the kwarg.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '__all__ = \["setup_form_api"\]' api/__init__.py)
# REPLACE `__all__ = ["setup_form_api"]` (verified: :24) with:
from .submission_events import SubmittedCallback, SubmittedEvent

__all__ = ["setup_form_api", "SubmittedEvent", "SubmittedCallback"]
```

### `packages/parrot-formdesigner/tests/unit/api/test_on_submitted.py` (CREATE)
```python
"""FEAT-730 — on_submitted host hook."""
# FILL IN: same app harness as tests/unit/api/test_public_form_controls_http.py (TASK-4634).

async def test_on_submitted_called_once(): ...        # success -> exactly one SubmittedEvent with is_public; no `anonymous` attr
async def test_on_submitted_not_called_on_409(): ...  # closed form -> callback not called
async def test_on_submitted_error_swallowed(): ...    # callback raises -> still 200, warning logged
async def test_event_importable_from_api(): ...       # from parrot_formdesigner.api import SubmittedEvent
```

### FILL IN checklist
- [ ] `_notify_submitted` body (AC9)
- [ ] TYPE_CHECKING imports in handlers.py and routes.py
- [ ] Test bodies

---

## Acceptance Criteria

- [ ] Callback awaited exactly once per successful REST `/data` store; never on 4xx/5xx (AC9).
- [ ] A raising callback never changes the response (AC9).
- [ ] `SubmittedEvent` has exactly the seven contract fields (no `anonymous`).

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_on_submitted.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_setup_form_api.py -q`

---

## Test Specification

Spec §4 rows `test_on_submitted_called_once`, `test_on_submitted_error_swallowed`.

---

## Agent Instructions

1. Feature worktree; TASK-4632 and TASK-4634 must be `done` (shared files).
2. Re-grep every anchor (TASK-4634 shifted the lines).
3. Implement; run Validation Commands; commit only the listed files.
4. `scripts/sdd/close_task.sh TASK-4635 formdesigner-public-form-controls verified`.

---

## Completion Note

*(Agent fills this in when done)*
