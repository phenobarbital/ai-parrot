# TASK-836: `FormOperator` ABC + `OperatorContext`

**Feature**: FEAT-121 — Parrot FormDesigner POST Submission Pipeline
**Spec**: `sdd/specs/parrot-formdesigner-post-method.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-835
**Assigned-to**: unassigned

---

## Context

Operators are the business-rule plugin layer around form submission. A `FormOperator` is a class
with four optional async hooks: `pre_validate`, `post_validate`, `pre_save`, `post_save`. Each
hook is invoked with an `OperatorContext` carrying per-request state (request, form_schema, user
ids, shared scratchpad). Spec §2 New Public Interfaces, §3 Module 3.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot/formdesigner/operators/__init__.py` that
  re-exports `FormOperator` and `OperatorContext`.
- Create `packages/parrot-formdesigner/src/parrot/formdesigner/operators/base.py` containing:
  - `OperatorContext` — Pydantic v2 model with fields `request: Any`, `form_schema: FormSchema`,
    `user_id: int | None = None`, `org_id: int | None = None`, `programs: list[str] = []`,
    `scratchpad: dict[str, Any] = {}`. Use `ConfigDict(arbitrary_types_allowed=True)` because
    `request` is an aiohttp object.
  - `FormOperator` — an `ABC` (use `ABC` not `ABCMeta`) with four async hook methods, each with a
    safe no-op default implementation (subclasses override what they need).
- Write unit tests covering default no-op behavior, context validation, and correct method
  signatures.

**NOT in scope**:
- Any concrete operator (that is TASK-838 for `UserDetails`).
- Pipeline orchestration / calling hooks from the handler (that is TASK-839).
- Registering operators (declarative decorator registry is a deferred open question).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/operators/__init__.py` | CREATE | Re-exports |
| `packages/parrot-formdesigner/src/parrot/formdesigner/operators/base.py` | CREATE | `FormOperator` ABC + `OperatorContext` model |
| `packages/parrot-formdesigner/tests/unit/test_operator_base.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Inside operators/base.py
from __future__ import annotations

from abc import ABC
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from parrot.formdesigner.core.schema import FormSchema
from parrot.formdesigner.services.submissions import FormSubmission
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:107-133 (verified)
class FormSchema(BaseModel):
    form_id: str
    version: str = "1.0"
    title: LocalizedString
    description: LocalizedString | None = None
    sections: list[FormSection]
    submit: SubmitAction | None = None
    cancel_allowed: bool = True
    meta: dict[str, Any] | None = None
```

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/submissions.py (post-TASK-835)
class FormSubmission(BaseModel):
    submission_id: str
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime
    # NEW (added in TASK-835):
    user_id: int | None = None
    org_id: int | None = None
    program: str | None = None
    client: str | None = None
    status: str | None = None
    enrichment: dict[str, Any] | None = None
```

### Does NOT Exist
- ~~`parrot.formdesigner.operators`~~ package — this task creates it.
- ~~`FormOperator`, `OperatorContext`~~ — new in this task.
- ~~`@form_operator` decorator / operator registry~~ — deferred (spec §8 open question).
- ~~`BaseOperator` or `OperatorBase` under other names~~ — use exactly `FormOperator`.

---

## Implementation Notes

### Pattern to Follow

Default hook bodies return the input unchanged so subclasses override only what they need:

```python
class FormOperator(ABC):
    """Class-based submission operator. All hooks are optional."""

    async def pre_validate(
        self, payload: dict[str, Any], ctx: OperatorContext
    ) -> dict[str, Any]:
        """Mutate the raw payload before typed validation. Default: no-op."""
        return payload

    async def post_validate(
        self, validated: BaseModel, ctx: OperatorContext
    ) -> BaseModel:
        """Apply business rules after typed validation. Default: no-op."""
        return validated

    async def pre_save(
        self, submission: FormSubmission, ctx: OperatorContext
    ) -> FormSubmission:
        """Final mutation before persistence. Default: no-op."""
        return submission

    async def post_save(
        self,
        submission: FormSubmission,
        ctx: OperatorContext,
        *,
        conn: "asyncpg.Connection",
    ) -> None:
        """In-transaction side effects after persistence. Default: no-op."""
        return None
```

### Context model

```python
class OperatorContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: Any                       # aiohttp.web.Request — not typed to keep this module aiohttp-free
    form_schema: FormSchema
    user_id: int | None = None
    org_id: int | None = None
    programs: list[str] = Field(default_factory=list)
    scratchpad: dict[str, Any] = Field(default_factory=dict)
```

### Key Constraints
- `FormOperator` inherits from `abc.ABC` but has **no abstract methods** — all four hooks have
  default no-op implementations. This is intentional per spec §2 New Public Interfaces ("All
  hooks are optional (default no-op)").
- Every hook is `async def`.
- `post_save` takes `conn` as keyword-only — matches spec §7 "Operators-in-transaction".
- `OperatorContext` is a Pydantic v2 BaseModel; use `model_config = ConfigDict(arbitrary_types_allowed=True)`.
- Google-style docstrings on everything.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py:29-91` — ABC style.

---

## Acceptance Criteria

- [ ] `parrot.formdesigner.operators` package exists with `__init__.py` re-exporting
      `FormOperator` and `OperatorContext`.
- [ ] Importing works: `from parrot.formdesigner.operators import FormOperator, OperatorContext`.
- [ ] `class MyOp(FormOperator): pass` instantiates without error (no abstract methods).
- [ ] All four hooks exist on `FormOperator`, are `async def`, and return their input unchanged
      (or `None` for `post_save`) in the base class.
- [ ] `OperatorContext(request=<any>, form_schema=<FormSchema>)` validates (extras default).
- [ ] Unit tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_operator_base.py -v`.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot/formdesigner/operators/` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_operator_base.py
import inspect
import pytest
from unittest.mock import MagicMock

from parrot.formdesigner.operators import FormOperator, OperatorContext
from parrot.formdesigner.services.submissions import FormSubmission


def _make_ctx():
    form_schema = MagicMock()  # duck-typed FormSchema
    request = MagicMock()
    return OperatorContext(request=request, form_schema=form_schema)


class TestFormOperator:
    def test_subclass_instantiates(self):
        class NoOp(FormOperator):
            pass
        NoOp()  # must not raise

    @pytest.mark.asyncio
    async def test_pre_validate_default_noop(self):
        ctx = _make_ctx()
        payload = {"a": 1}
        out = await FormOperator().pre_validate(payload, ctx)
        assert out is payload

    @pytest.mark.asyncio
    async def test_post_validate_default_noop(self):
        ctx = _make_ctx()
        class M:
            pass
        m = M()
        out = await FormOperator().post_validate(m, ctx)
        assert out is m

    @pytest.mark.asyncio
    async def test_pre_save_default_noop(self):
        ctx = _make_ctx()
        sub = FormSubmission(form_id="f", form_version="1.0", data={}, is_valid=True)
        out = await FormOperator().pre_save(sub, ctx)
        assert out is sub

    @pytest.mark.asyncio
    async def test_post_save_default_noop(self):
        ctx = _make_ctx()
        sub = FormSubmission(form_id="f", form_version="1.0", data={}, is_valid=True)
        out = await FormOperator().post_save(sub, ctx, conn=MagicMock())
        assert out is None

    def test_all_hooks_async(self):
        for name in ("pre_validate", "post_validate", "pre_save", "post_save"):
            assert inspect.iscoroutinefunction(getattr(FormOperator, name))

    def test_post_save_conn_kw_only(self):
        sig = inspect.signature(FormOperator.post_save)
        assert sig.parameters["conn"].kind is inspect.Parameter.KEYWORD_ONLY


class TestOperatorContext:
    def test_minimal_construction(self):
        ctx = _make_ctx()
        assert ctx.user_id is None
        assert ctx.programs == []
        assert ctx.scratchpad == {}

    def test_accepts_extras(self):
        ctx = OperatorContext(
            request=MagicMock(),
            form_schema=MagicMock(),
            user_id=42,
            org_id=7,
            programs=["alpha"],
            scratchpad={"k": "v"},
        )
        assert ctx.user_id == 42
        assert ctx.programs == ["alpha"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path above (§2 New Public Interfaces; §3 Module 3; §7 Patterns).
2. **Check dependencies** — `TASK-835` (for the extended `FormSubmission` model) must be done.
3. **Verify the Codebase Contract** — re-read `core/schema.py:107-133` and
   `services/submissions.py` (post-TASK-835 shape).
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** the ABC, context, and tests.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-836-form-operator-abc.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
