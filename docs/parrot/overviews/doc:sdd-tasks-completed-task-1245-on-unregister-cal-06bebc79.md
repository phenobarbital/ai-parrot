---
type: Wiki Overview
title: 'TASK-1245: Audit and update `on_unregister` callback consumers'
id: doc:sdd-tasks-completed-task-1245-on-unregister-callback-consumers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 6 of the spec. The `on_unregister` callback signature
---

# TASK-1245: Audit and update `on_unregister` callback consumers

**Feature**: FEAT-183 — FormRegistry Multi-Tenancy
**Spec**: `sdd/specs/formregistry-multi-tenancy.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1239
**Assigned-to**: unassigned

---

## Context

Implements Module 6 of the spec. The `on_unregister` callback signature
becomes a breaking change in TASK-1239: from
`Callable[[str], Awaitable[None]]` to
`Callable[[str, str], Awaitable[None]]` — callbacks receive `(form_id,
tenant)`. The firing site in `services/registry.py` (currently line 216)
is updated by TASK-1239 to pass the tenant captured at unregister time.

This task audits the rest of the tree (and any consumers across the
monorepo packages) for code that calls `FormRegistry.on_unregister(...)`
or otherwise depends on the old signature, and updates them.

---

## Scope

- Run `grep -rn "on_unregister" packages/ --include="*.py"` and inventory
  every match. Categorize each match:
  - **Producer** (registers a callback): must update the callback function
    to accept `(form_id: str, tenant: str)`.
  - **Documentation / type hint reference**: update to the new signature.
  - **Firing site** (`services/registry.py:216`): already handled by
    TASK-1239 — verify only, do NOT re-edit.
  - **Test**: update to assert against the new tuple-shaped invocation.
- For each producer, update the callback signature. Preserve the producer's
  behavior; only the function signature and any direct uses of `form_id`
  inside change. If the consumer previously didn't care about tenant, the
  new `tenant` parameter is captured as `_` and ignored (with a comment
  explaining).
- For each test that mocks/exercises `on_unregister`, update the mock /
  assertion to the tuple form.

If the audit yields ZERO producers outside of tests, document the
finding — the only change in this task is then to verify the firing site
in `registry.py` (no callback shape change needed elsewhere).

**NOT in scope**:
- The `FormRegistry.on_unregister` method signature itself — already changed
  by TASK-1239.
- The firing site in `register()` for `on_register` — that callback's
  signature is unchanged.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| (TBD by audit) | MODIFY | Each consumer of `on_unregister` updated to new signature. |
| `packages/parrot-formdesigner/tests/**/test_*.py` (subset) | MODIFY | Tests that exercise `on_unregister` callbacks. |

The exact file list is produced by the audit step. Include the list in the
Completion Note.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# FormRegistry's on_unregister method (post-TASK-1239):
from parrot_formdesigner.services import FormRegistry
# Signature: def on_unregister(
#     self, callback: Callable[[str, str], Awaitable[None]]
# ) -> None
```

### Existing Signatures to Use

```python
# Post-TASK-1239 callback contract:
async def my_callback(form_id: str, tenant: str) -> None:
    """Receives the unregistered form's id AND its tenant."""
    ...

# Producer side:
registry.on_unregister(my_callback)
```

### Does NOT Exist

- ~~`on_unregister_v2`~~ — no parallel-versioned hook. Change in place.
- ~~A legacy adapter that wraps `(form_id, tenant)` → `(form_id)`~~ — out
  of scope. Update consumers directly.
- ~~`tenant: str | None`~~ on the callback — the tenant is always resolved
  by the time the callback fires; it's `str`, not `str | None`.

---

## Implementation Notes

### Pattern to Follow

```python
# Before
async def _cleanup(form_id: str) -> None:
    await some_cache.invalidate(form_id)

registry.on_unregister(_cleanup)

# After (consumer doesn't care about tenant)
async def _cleanup(form_id: str, _tenant: str) -> None:
    await some_cache.invalidate(form_id)

registry.on_unregister(_cleanup)

# After (consumer needs to partition by tenant)
async def _cleanup(form_id: str, tenant: str) -> None:
    await some_cache.invalidate(form_id, tenant=tenant)

registry.on_unregister(_cleanup)
```

For tests using `AsyncMock`:

```python
# Before
mock_callback = AsyncMock()
registry.on_unregister(mock_callback)
await registry.unregister("form-a")
mock_callback.assert_awaited_once_with("form-a")

# After
mock_callback = AsyncMock()
registry.on_unregister(mock_callback)
await registry.unregister("form-a", tenant="epson")
mock_callback.assert_awaited_once_with("form-a", "epson")
```

### Key Constraints

- The callback's `tenant` parameter is always provided by the firing site
  in `registry.py` — it's whatever `_resolve_tenant` returned at unregister
  time, NEVER `None`.
- If a consumer needs tenant for its logic, integrate it; if not, accept
  it as `_tenant` to satisfy the signature.
- Order of arguments is `(form_id, tenant)` — match the spec exactly.

### References in Codebase

- `services/registry.py:216` (post-TASK-1239) — firing site. Use as the
  source of truth for the argument order.
- TASK-1239's test `test_on_unregister_callback_receives_tuple` — pattern
  for assertions.

---

## Acceptance Criteria

- [ ] `grep -rn "on_unregister" packages/ --include="*.py"` produces an
      inventory; every producer is listed in the Completion Note.
- [ ] Every producer's callback accepts `(form_id: str, tenant: str)`.
- [ ] No callback in the tree retains the single-argument signature.
- [ ] All tests exercising `on_unregister` pass with the updated mocks.
- [ ] `pytest packages/parrot-formdesigner/tests/ -k "unregister" -v` is
      green.
- [ ] `ruff check` clean for modified files.
- [ ] `mypy` clean for modified files.

---

## Test Specification

No new dedicated test file. Existing tests under
`packages/parrot-formdesigner/tests/` that touch `on_unregister` MUST be
updated to assert against the tuple-shaped call. The exact set is produced
by the audit.

---

## Agent Instructions

1. **Read the spec** §3 Module 6 and §2 Overview (callback signature
   change).
2. **Check dependencies**: TASK-1239 done.
3. **Run the audit**: `grep -rn "on_unregister" packages/ --include="*.py"`
   and produce a table of (file, line, role, action).
4. **Update each producer and test** per the patterns above.
5. **Run** the relevant tests and full ruff/mypy on the touched files.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `done`.
8. **Fill in the Completion Note** with the full inventory.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-19
**Notes**: Audit results:

grep -rn "on_unregister" packages/ --include="*.py" produced:

Within parrot-formdesigner:
- services/registry.py:178 — DEFINITION (list[Callable[[str, str], ...]]) — already updated by TASK-1239
- services/registry.py:350-351 — FIRING SITE — already updated by TASK-1239, passes (form_id, tenant)
- services/registry.py:660-673 — METHOD DEFINITION — already updated by TASK-1239
- tests/unit/test_registry_multi_tenancy.py:223-243 — TESTS with tuple form — already added by TASK-1239

External packages:
- packages/ai-parrot/src/parrot/forms/registry.py:121,184,336,344 — SEPARATE legacy FormRegistry in
  the `ai-parrot` package. This is NOT the parrot-formdesigner FormRegistry and is NOT in scope for FEAT-183.
  Its tests (packages/ai-parrot/tests/unit/forms/test_registry.py) use the old single-arg signature
  and are unaffected by this feature.

ZERO external producers of parrot-formdesigner's FormRegistry.on_unregister found outside its own test file.
No code changes were required — TASK-1239 already completed all necessary updates.
4 unregister tests pass.

**Deviations from spec**: None. Audit confirmed no producers to update outside of what TASK-1239 already handled.
