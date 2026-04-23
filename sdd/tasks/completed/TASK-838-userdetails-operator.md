# TASK-838: `UserDetails` operator

**Feature**: FEAT-121 — Parrot FormDesigner POST Submission Pipeline
**Spec**: `sdd/specs/parrot-formdesigner-post-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-836
**Assigned-to**: unassigned

---

## Context

First concrete `FormOperator` shipped with FEAT-121. Reads navigator-auth session fields off the
aiohttp request and stamps `user_id`, `org_id`, `program` onto the `FormSubmission` metadata.
Spec §3 Module 4, §2 New Public Interfaces.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot/formdesigner/operators/user_details.py`
  implementing `UserDetails(FormOperator)` with:
  - `post_validate(validated, ctx)` — populate `ctx.user_id`, `ctx.org_id`, `ctx.programs`
    from `ctx.request` using the **same extraction logic** already present in
    `FormAPIHandler._get_org_id` (`api.py:151-177`) and `_get_programs` (`api.py:179-198`).
    Store these on `ctx.scratchpad` too if useful for subsequent hooks.
  - `pre_save(submission, ctx)` — set `submission.user_id`, `submission.org_id`,
    `submission.program` (first entry of `ctx.programs` if non-empty, else `None`).
- Register `UserDetails` from `operators/__init__.py`.
- Unit tests: stamps correct values from a mock request, no-ops gracefully when session data is
  missing.

**NOT in scope**:
- Wiring `UserDetails` into `FormAPIHandler` — that is TASK-839 / TASK-840.
- Multi-program handling beyond "first entry" (deferred, spec §8 OQ on operator catalog).
- An `AuditTrail` or `OrgContext` operator.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/operators/user_details.py` | CREATE | `UserDetails` operator |
| `packages/parrot-formdesigner/src/parrot/formdesigner/operators/__init__.py` | MODIFY | Re-export `UserDetails` |
| `packages/parrot-formdesigner/tests/unit/test_userdetails_operator.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations

from typing import Any

from .base import FormOperator, OperatorContext  # from TASK-836
# FormSubmission from TASK-835 (extended with user_id/org_id/program)
from parrot.formdesigner.services.submissions import FormSubmission
```

### Existing Signatures to Use

**Session extraction logic to mirror** — copy the behavior, do NOT import the helpers because
they are instance methods of `FormAPIHandler`:

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:151-177
def _get_org_id(self, request: web.Request) -> int | None:
    user = getattr(request, "user", None)
    if user and user.organizations:
        try:
            return int(user.organizations[0].org_id)
        except (TypeError, ValueError):
            return None
    return None
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:179-198
def _get_programs(self, request: web.Request) -> list[str]:
    session = getattr(request, "session", None)
    if session is None:
        return []
    userinfo = session.get("session", {})
    return userinfo.get("programs", [])
```

**navigator-auth user_id** — session may carry `user_id` inside `session["session"]["user_id"]`
(the same `AUTH_SESSION_OBJECT="session"` key). Mirror the pattern used in
`packages/ai-parrot/src/parrot/handlers/chat_interaction.py:39-61`:
```python
# Existing pattern in chat_interaction.py:39-61
session = await get_session(request)
userinfo = session.get(AUTH_SESSION_OBJECT, {})
user_id = userinfo.get("user_id")
```

For this operator, access it directly from `ctx.request` via the same key style — do NOT call
`get_session` (that dep belongs to the outer handler); trust `ctx.request.session["session"]["user_id"]`
when present, else try `getattr(ctx.request.user, "user_id", None)`.

### Does NOT Exist
- ~~`UserDetails` class anywhere~~ — this task creates it.
- ~~`FormAPIHandler._get_user_id` helper~~ — only `_get_org_id` / `_get_programs` exist.
- ~~`AUTH_SESSION_OBJECT` constant imported from parrot-formdesigner~~ — it is a navigator-auth
  constant. For the operator, avoid importing it; hard-code the literal `"session"` inside the
  operator or read `_get_programs` comment reference in `api.py:179-198` for the exact key.

---

## Implementation Notes

### Pattern to Follow

```python
class UserDetails(FormOperator):
    """Populate user/org/program fields from the navigator-auth session."""

    async def post_validate(
        self, validated, ctx: OperatorContext,
    ):
        request = ctx.request
        # user_id
        user = getattr(request, "user", None)
        user_id = None
        if user is not None:
            user_id = getattr(user, "user_id", None) or getattr(user, "id", None)
        if user_id is None:
            session = getattr(request, "session", None)
            if session is not None:
                user_id = session.get("session", {}).get("user_id")
        ctx.user_id = int(user_id) if user_id is not None else None
        # org_id (mirror FormAPIHandler._get_org_id)
        if user is not None and getattr(user, "organizations", None):
            try:
                ctx.org_id = int(user.organizations[0].org_id)
            except (TypeError, ValueError):
                ctx.org_id = None
        # programs
        session = getattr(request, "session", None)
        ctx.programs = (session.get("session", {}).get("programs", []) if session else [])
        return validated

    async def pre_save(
        self, submission: FormSubmission, ctx: OperatorContext,
    ) -> FormSubmission:
        submission.user_id = ctx.user_id
        submission.org_id = ctx.org_id
        submission.program = ctx.programs[0] if ctx.programs else None
        return submission
```

### Key Constraints
- **Graceful on missing data**: if any session/user attribute is missing, the operator must NOT
  raise — just leave the corresponding field as `None` (open question in spec §8 contemplates a
  "strict mode" switch, but v1 default is soft).
- Reuse of `FormAPIHandler._get_org_id`/`_get_programs` helpers is not possible across instances;
  copy the extraction logic verbatim.
- `self.logger = logging.getLogger(__name__)` is optional; only log on unexpected shapes.
- Google-style docstrings.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:151-198` — helpers to mirror.
- `packages/ai-parrot/src/parrot/handlers/chat_interaction.py:39-61` — `user_id` extraction pattern.

---

## Acceptance Criteria

- [ ] `UserDetails` class at the specified path.
- [ ] Importing works: `from parrot.formdesigner.operators import UserDetails`.
- [ ] `UserDetails()` constructs without error (inherits default no-op hooks).
- [ ] Given a request mock with `user.organizations[0].org_id=42`, `user.user_id=7`, and
      `session["session"]["programs"]=["alpha"]`, after `post_validate + pre_save`:
  - `submission.user_id == 7`, `submission.org_id == 42`, `submission.program == "alpha"`.
- [ ] When no user / session is on the request, the operator does NOT raise; the resulting
      submission has `user_id=None`, `org_id=None`, `program=None`.
- [ ] Unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_userdetails_operator.py -v`.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot/formdesigner/operators/user_details.py` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_userdetails_operator.py
import pytest
from unittest.mock import MagicMock

from parrot.formdesigner.operators import UserDetails, OperatorContext
from parrot.formdesigner.services.submissions import FormSubmission


def _request_with(user_id=None, org_id=None, programs=None):
    req = MagicMock()
    if user_id is not None or org_id is not None:
        req.user = MagicMock()
        req.user.user_id = user_id
        req.user.organizations = [MagicMock(org_id=org_id)] if org_id is not None else []
    else:
        req.user = None
    req.session = {"session": {"user_id": user_id, "programs": programs or []}}
    return req


class TestUserDetailsOperator:
    @pytest.mark.asyncio
    async def test_stamps_all_fields(self):
        op = UserDetails()
        ctx = OperatorContext(
            request=_request_with(user_id=7, org_id=42, programs=["alpha"]),
            form_schema=MagicMock(),
        )
        validated = MagicMock()
        await op.post_validate(validated, ctx)
        sub = FormSubmission(form_id="f", form_version="1.0", data={}, is_valid=True)
        sub = await op.pre_save(sub, ctx)
        assert sub.user_id == 7
        assert sub.org_id == 42
        assert sub.program == "alpha"

    @pytest.mark.asyncio
    async def test_missing_session_is_graceful(self):
        op = UserDetails()
        req = MagicMock()
        req.user = None
        req.session = None
        ctx = OperatorContext(request=req, form_schema=MagicMock())
        await op.post_validate(MagicMock(), ctx)
        sub = await op.pre_save(
            FormSubmission(form_id="f", form_version="1.0", data={}, is_valid=True),
            ctx,
        )
        assert sub.user_id is None
        assert sub.org_id is None
        assert sub.program is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path above (§3 Module 4, §2 New Public Interfaces).
2. **Check dependencies** — `TASK-836` (FormOperator ABC) must be done.
3. **Verify the Codebase Contract** — re-read `handlers/api.py:151-198` to confirm the
   `_get_org_id` / `_get_programs` extraction logic is unchanged.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** the operator and tests.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-838-userdetails-operator.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
