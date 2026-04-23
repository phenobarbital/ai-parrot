# TASK-840: `setup_form_routes` wiring for operators + resolver

**Feature**: FEAT-121 — Parrot FormDesigner POST Submission Pipeline
**Spec**: `sdd/specs/parrot-formdesigner-post-method.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-839
**Assigned-to**: unassigned

---

## Context

`setup_form_routes` is the public composition root for form-designer routes. It must forward the
new `operators` and `pydantic_resolver` kwargs to `FormAPIHandler(...)` so application code can
wire the new pipeline. No new routes are added. Spec §3 Module 7, §2 New Public Interfaces
(setup_form_routes extension).

---

## Scope

- Extend `setup_form_routes` signature with two new keyword-only kwargs:
  `operators: list["FormOperator"] | None = None`,
  `pydantic_resolver: "PydanticModelResolver | None" = None`.
- Forward them to `FormAPIHandler(...)` at construction (`routes.py:120-125`).
- Update the function docstring to describe the new parameters.
- Do NOT add or remove any `app.router.add_*` calls.
- Unit test: patch `FormAPIHandler` constructor, call `setup_form_routes` with the new kwargs,
  assert they arrived at the handler.

**NOT in scope**:
- Creating/registering any default operator catalog.
- The warm-up call for `PydanticModelResolver` (deferred — see spec §8 open question about
  warm-up trigger). Applications can call `resolver.warm_up(registry)` themselves after
  `setup_form_routes` if desired.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py` | MODIFY | Extend `setup_form_routes` signature + forward kwargs |
| `packages/parrot-formdesigner/tests/unit/test_setup_form_routes_wiring.py` | CREATE | Unit test for kwarg forwarding |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Top of handlers/routes.py — add:
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.formdesigner.operators import FormOperator
    from parrot.formdesigner.services.pydantic_resolver import PydanticModelResolver
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:82-125 (verified)
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    prefix: str = "",
    protect_pages: bool = True,
    submission_storage: "FormSubmissionStorage | None" = None,
    forwarder: "SubmissionForwarder | None" = None,
) -> None:
    if registry is None:
        registry = FormRegistry()

    api = FormAPIHandler(
        registry=registry,
        client=client,
        submission_storage=submission_storage,
        forwarder=forwarder,
    )
    ...
```

### Does NOT Exist
- ~~New routes parallel to `/data`~~ — not added (spec §1 Non-Goals).
- ~~Automatic warm-up call in `setup_form_routes`~~ — not added; applications do their own
  warm-up after wiring.

---

## Implementation Notes

### Pattern to Follow

```python
def setup_form_routes(
    app,
    *,
    registry=None,
    client=None,
    prefix="",
    protect_pages=True,
    submission_storage=None,
    forwarder=None,
    operators=None,            # NEW
    pydantic_resolver=None,    # NEW
):
    ...
    api = FormAPIHandler(
        registry=registry,
        client=client,
        submission_storage=submission_storage,
        forwarder=forwarder,
        operators=operators,
        pydantic_resolver=pydantic_resolver,
    )
    ...  # routes unchanged
```

### Key Constraints
- Maintain backward compat: existing callers pass no new kwargs and get today's behavior.
- Keep the routes block byte-identical — do NOT touch `add_get` / `add_post` lines.
- Docstring must mention the new params in the same style as existing params.

### References in Codebase
- `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py:82-159` — current func.

---

## Acceptance Criteria

- [ ] `setup_form_routes` has two new keyword-only kwargs with `None` defaults.
- [ ] Both are forwarded to `FormAPIHandler(...)` at construction.
- [ ] No route additions or removals.
- [ ] Existing call-sites (without new kwargs) still work unchanged.
- [ ] Unit test verifies the kwargs arrive on the handler.
- [ ] `ruff check packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py` clean.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_setup_form_routes_wiring.py
import pytest
from unittest.mock import MagicMock, patch
from aiohttp import web

from parrot.formdesigner.handlers.routes import setup_form_routes
from parrot.formdesigner.operators import FormOperator
from parrot.formdesigner.services.pydantic_resolver import PydanticModelResolver


class TestSetupFormRoutesWiring:
    def test_forwards_new_kwargs_to_handler(self):
        app = web.Application()
        op = MagicMock(spec=FormOperator)
        resolver = MagicMock(spec=PydanticModelResolver)

        with patch(
            "parrot.formdesigner.handlers.routes.FormAPIHandler",
        ) as HandlerCls:
            setup_form_routes(
                app,
                operators=[op],
                pydantic_resolver=resolver,
            )
            kwargs = HandlerCls.call_args.kwargs
            assert kwargs["operators"] == [op]
            assert kwargs["pydantic_resolver"] is resolver

    def test_defaults_none_when_not_passed(self):
        app = web.Application()
        with patch(
            "parrot.formdesigner.handlers.routes.FormAPIHandler",
        ) as HandlerCls:
            setup_form_routes(app)
            kwargs = HandlerCls.call_args.kwargs
            assert kwargs["operators"] is None
            assert kwargs["pydantic_resolver"] is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path above (§3 Module 7, §2 New Public Interfaces).
2. **Check dependencies** — `TASK-839` done (handler accepts the new kwargs).
3. **Verify the Codebase Contract** — re-read `routes.py:82-159` to confirm current signature.
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
5. **Implement** kwarg extension + forwarding + test.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-840-setup-form-routes-wiring.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
