# TASK-3910: formdesigner F1 — tenant test double (18 failures)

**Feature**: FEAT-618 — Merge-Tier Gate Integrity & parrot-formdesigner Baseline Repair
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3908
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3 (failure cluster **F1**, 18 of the 40). The largest
single cause of `parrot-formdesigner`'s red baseline is a **knowingly deferred**
test double. `test_api_feat300.py:173` says so in its own docstring:

> `_make_request()` predates FEAT-421 and only stubs the legacy session-derived
> `programs` list; `FormAPIHandler._get_tenant()` now resolves via
> `declared_tenant(request)`, which reads `request.get("tenant")` … a
> `MagicMock(spec=web.Request)`'s inherited `.get()` returns a fresh (truthy)
> `MagicMock` for any key, so every handler call silently resolves to a nonsense
> tenant instead of `"t1"`. **Scoped to the FEAT-433 tests … not applied to the
> shared `_make_request()` used by pre-existing tests elsewhere in this file
> (out of scope).**

`_tenant_request()` (`:173`) is the already-written fix, applied to only 6 of the
31 call sites. The other 25 produce `404 == 200` / `404 == 409` / `404 == 204`
and `ValueError: Invalid tenant: "<MagicMock name='mock.get()' …>"`.

This is a **test-only** fix. `FormAPIHandler._get_tenant()`
(`handlers.py:270-295`) is correct and must not change.

---

## Scope

- Fold `_tenant_request()`'s tenant patch into `_make_request()` itself in
  `test_api_feat300.py`, so every call site resolves the real tenant.
- Delete the now-redundant `_tenant_request()` and repoint its 6 call sites.
- Apply the same stub to `test_form_uid_integration.py`'s own separate
  `_make_request()` (`:43`).
- `test_feat300_review_fixes.py` imports `_make_request` from
  `test_api_feat300` — confirm it inherits the fix and needs no change beyond
  TASK-3908's import rewrite.

**NOT in scope**: changing any `src/` file; the registry/snippet gaps
(TASK-3911); pinned-constant drift (TASK-3912); the controls contract fixture
(TASK-3913); layering/harness (TASK-3914).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/unit/test_api_feat300.py` | MODIFY | fold the tenant stub into `_make_request`, delete `_tenant_request` |
| `packages/parrot-formdesigner/tests/test_form_uid_integration.py` | MODIFY | same stub in its own `_make_request` (`:43`) |
| `packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py` | MODIFY | verify it inherits the fix; adjust only if needed |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.api.handlers import FormAPIHandler  # verified: tests/unit/test_api_feat300.py:30
from unittest.mock import AsyncMock, MagicMock               # verified: tests/unit/test_api_feat300.py:26
from aiohttp import web                                      # verified: tests/unit/test_api_feat300.py:146 (local import)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/tests/unit/test_api_feat300.py
def _make_request(*, method: str = "GET", form_uid: str = _UNKNOWN_FORM_UID,
                  version: str | None = None, body: dict | None = None,
                  session_programs: list[str] | None = None,
                  tenant: str = "t1") -> MagicMock:          # line 125  (25 call sites)
def _tenant_request(*, tenant: str = "t1", **kwargs) -> MagicMock:   # line 173 (6 call sites)
def _make_handler(registry: FormRegistry | None = None, *,
                  tenant: str = "t1") -> FormAPIHandler:     # line 193

# the exact one-line patch _tenant_request already applies (test_api_feat300.py:190):
#     req.get = lambda key, default=None: tenant if key == "tenant" else default

# packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py
from tests.unit.test_api_feat300 import _make_form, _make_handler, _make_request  # line 32

# packages/parrot-formdesigner/tests/test_form_uid_integration.py
def _make_request(                                            # line 43  (its OWN helper, 12 call sites)

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py  — DO NOT MODIFY
    def _get_tenant(self, request: web.Request) -> str:       # line 270
        return declared_tenant(request)                       # line 295
```

### Does NOT Exist
- ~~a shared `conftest.py` fixture providing the request double~~ — each test module defines its own `_make_request`; there are **two** distinct ones (`test_api_feat300.py:125` and `test_form_uid_integration.py:43`).
- ~~`FormAPIHandler.set_tenant()` / `FormAPIHandler.tenant`~~ — not real; the tenant is read off the request only.
- ~~`declared_tenant` being importable from `parrot_formdesigner.api.handlers`~~ — it is imported *into* `handlers.py` at line 34 from `api/tenant.py`; do not re-export it.
- ~~`MagicMock(spec=web.Request)` honouring `.get()` automatically~~ — it returns a truthy `MagicMock` for every key; that is the whole bug.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/tests/unit/test_api_feat300.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/test_form_uid_integration.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py#FormAPIHandler._get_tenant"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **No `src/` file changes.** If a handler looks wrong, it is not — `_get_tenant`
  was deliberately rewritten by FEAT-421 and the test double is what lagged.
- `_make_request` already takes a `tenant: str = "t1"` kwarg (`:132`); the stub
  must use **that** value, so no call site needs a new argument.
- Keep `session_programs` / `req.session` as they are — some tests still assert
  on the legacy session path. The tenant stub is additive.
- After folding, `_tenant_request` is a pure alias; delete it and repoint its 6
  call sites rather than leaving a wrapper behind.
- `req.__contains__` is stubbed to always return `False` (`:163`). Do not change
  it; `declared_tenant` uses `.get()`, not `in`.

### References in Codebase
- `test_api_feat300.py:173-191` — `_tenant_request`, the already-correct patch.
- `handlers.py:270-295` — `_get_tenant`, the (correct) production path.

---

## Implementation Blueprint

### Steps (in order)
1. Add the tenant stub inside `_make_request` — *why*: one edit fixes all 25 call sites at once.
2. Delete `_tenant_request` and repoint its 6 call sites to `_make_request` — *why*: it becomes an exact alias; leaving it invites the two helpers drifting apart again.
3. Apply the same stub in `test_form_uid_integration.py:43` — *why*: it is a separate helper with the identical defect (3 of the 15 failures).
4. Re-run the three files and confirm 15 failures become 0 — *why*: AC1 counts this cluster exactly.

### `packages/parrot-formdesigner/tests/unit/test_api_feat300.py` (MODIFY — part 1)
```python
# occurrences: 1 (verified: grep -c '    req.session = session_obj' tests/unit/test_api_feat300.py)
# AFTER — insert below `    req.__contains__ = lambda self, key: False  # no "session" key item access` (verified: tests/unit/test_api_feat300.py:163)

    # FEAT-618 TASK-3910: FormAPIHandler._get_tenant() resolves via
    # declared_tenant(request), which reads request.get("tenant") — set in
    # production by the @requires_tenant decorator these mocked-request unit
    # tests bypass. Without this, MagicMock(spec=web.Request).get() returns a
    # fresh truthy MagicMock for every key and every handler call resolves a
    # nonsense tenant, surfacing as 404s and "Invalid tenant: <MagicMock ...>".
    req.get = lambda key, default=None: tenant if key == "tenant" else default
```
**Why**: this is verbatim the patch `_tenant_request` already applies at
`:190`, moved up into the shared helper. `tenant` is the existing kwarg at
`:132`, so no call site changes. It must sit **after** `req.session` is
assigned so it cannot be clobbered.

### `packages/parrot-formdesigner/tests/unit/test_api_feat300.py` (MODIFY — part 2)
```python
# occurrences: 1 (verified: grep -c 'def _tenant_request' tests/unit/test_api_feat300.py)
# DELETE the whole `_tenant_request` definition at tests/unit/test_api_feat300.py:173-191
# FILL IN: repoint its 6 call sites to `_make_request` — bounded by AC1 and by
# the constraint that no call site gains or loses an argument (the signatures
# are `_tenant_request(*, tenant="t1", **kwargs)` over `_make_request(...)`,
# so the call text is identical apart from the name).
```
**Why**: once the stub is in `_make_request`, `_tenant_request` is an exact
alias. Two helpers that must stay in sync is how this defect arose; removing one
removes the failure mode.

### `packages/parrot-formdesigner/tests/test_form_uid_integration.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _make_request(' tests/test_form_uid_integration.py)
# FILL IN: apply the same `req.get = lambda key, default=None: tenant if key == "tenant" else default`
# stub inside this module's own `_make_request` (tests/test_form_uid_integration.py:43)
# — bounded by AC1. Read the helper first: confirm it has a `tenant` parameter;
# if it does not, add `tenant: str = "t1"` as a keyword-only default rather than
# hardcoding a literal.
```
**Why**: this module defines a second, independent request double with the same
gap — it is the source of the three
`ValueError: Invalid tenant: "<MagicMock name='mock.get()' …>"` failures.

### `packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from tests.unit.test_api_feat300 import' tests/unit/test_feat300_review_fixes.py)
# This module imports `_make_request` from test_api_feat300 (line 32), so it
# inherits the fix automatically.
# FILL IN: after TASK-3908 rewrites this import line, re-run the module and
# change nothing else unless a failure remains — bounded by AC1.
```
**Why**: the import at `:32` is one of the 24 sites TASK-3908 rewrites, which is
why this task depends on it. No independent fix should be invented here.

### FILL IN checklist
- [ ] `test_api_feat300.py` — repoint the 6 `_tenant_request` call sites; bounded by AC1
- [ ] `test_form_uid_integration.py::_make_request` — tenant stub (+ `tenant` kwarg if absent); bounded by AC1
- [ ] `test_feat300_review_fixes.py` — confirm it inherits the fix; bounded by AC1

---

## Acceptance Criteria

- [ ] All 18 F1 failures pass — standalone counts verified at spec time: `test_api_feat300.py` 9, `test_feat300_review_fixes.py` 6, `test_form_uid_integration.py` 3.
- [ ] `_tenant_request` no longer exists in `test_api_feat300.py`.
- [ ] **No file under `packages/parrot-formdesigner/src/` is modified** — `git diff --name-only` shows test files only.
- [ ] No previously-passing test in the three files regresses.
- [ ] **AC7** `ruff check` clean on all three files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/test_api_feat300.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py -q`
- `pytest packages/parrot-formdesigner/tests/test_form_uid_integration.py -q`

---

## Test Specification

No new test file. The 15 existing failures ARE the specification — each must
pass unchanged. Do not weaken an assertion to make it pass; if a test looks
wrong, it belongs to another cluster (TASK-3912 owns stale-constant tests).

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug tests-test-wheel-layout-tech-debt --feature-id FEAT-618`)
2. **Read the spec** §3 Module 3 and §2's failure taxonomy row **F1**.
3. **Check dependencies** — TASK-3908 must be `"done"` in `sdd/tasks/index/tests-test-wheel-layout-tech-debt.json`.
4. **Verify the Codebase Contract** — re-confirm `test_api_feat300.py:125/173/193` and `handlers.py:270`.
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** the Validation Commands. Prefix with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only this task's three files.
9. **Close** with `scripts/sdd/close_task.sh TASK-3910 tests-test-wheel-layout-tech-debt verified`.
10. **Fill in the Completion Note** with the new failure count for the package.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: New `parrot-formdesigner` failure count after this task (was 40).

**Deviations from spec**: none | describe if any
