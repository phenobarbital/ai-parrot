# TASK-3914: formdesigner F5 — layering regression + harness doubles (3 failures)

**Feature**: FEAT-618 — Merge-Tier Gate Integrity & parrot-formdesigner Baseline Repair
**Spec**: `sdd/specs/tests-test-wheel-layout-tech-debt.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 7 (failure cluster **F5**, 3 of the 40). Three
unrelated failures grouped only by "none of the other clusters". Two are test
doubles; **one is a genuine product regression**.

**F5a — `parrot_formdesigner.ui` transitively imports `parrot_formdesigner.api`
(PRODUCT).** `test_ui_imports.py:9` asserts `ui/` is independently mountable from
`api/`, and that invariant is currently broken:
`AssertionError: parrot_formdesigner.ui transitively imported parrot_formdesigner.api`.
The test is right; the import graph is wrong. Find the edge and cut it.

**F5b — `test_duplicate_location_raises` uses a double that is not a unique
violation (TEST).** The test raises `Exception("23505 unique violation")`
(`test_venue_service.py:253`). `is_unique_violation()` (`_db_utils.py:8-20`)
recognises a unique violation by **three** checks, and that exception passes
none of them:

```python
if type(exc).__name__ == "UniqueViolationError":  # ← plain Exception, no
sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
if sqlstate == "23505":                            # ← no sqlstate attribute, no
text = str(exc).lower()
return "duplicate key" in text or "unique constraint" in text
#        ↑ the message says "unique violation", not "unique constraint" — no
```

So `create_location` (`venue_service.py:359-363`) correctly re-raises and the raw
`Exception` escapes instead of `DuplicateVenueError`. **The product is correct**;
the double must be made to look like a real unique violation.

**F5c — `test_shortcut_equals_explicit`** in
`tests/unit/test_deterministic_integration.py` (`assert None is not None` /
`assert not True`). Diagnose before fixing; it has not been root-caused.

---

## Scope

- **F5a**: move the shared tenant layer to `core/` (see the DECIDED design note
  below) so `import parrot_formdesigner.ui` no longer pulls `parrot_formdesigner.api`.
- **F5b**: make the venue test's fake exception satisfy `is_unique_violation()`.
  Do not relax the production detector.
- **F5c**: root-cause `test_shortcut_equals_explicit` and fix the correct side,
  stating in the Completion Note which side moved and why.

**NOT in scope**: changing `is_unique_violation()` or `VenueService`; any other
cluster (TASK-3910 / 3911 / 3912 / 3913).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/tenant_errors.py` | CREATE | the three tenant error classes, moved verbatim from `api/errors.py` (F5a) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/tenant.py` | CREATE | the tenant decorator/helpers, moved verbatim from `api/tenant.py`; imports errors from `.tenant_errors` (F5a) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/errors.py` | MODIFY | becomes a re-export of `core.tenant_errors` — same class objects (F5a) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/tenant.py` | MODIFY | becomes a re-export of `core.tenant` — every public AND underscore name it defined (F5a) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py` | MODIFY | `from ..core.tenant import requires_tenant` (F5a) |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/telegram.py` | MODIFY | `from ..core.tenant import declared_tenant` (F5a) |
| `packages/parrot-formdesigner/tests/unit/api/test_requires_tenant.py` | MODIFY | `TestNoForbiddenReferences` must inspect `core.tenant` (where the code now lives), not the re-export shim |
| `packages/parrot-formdesigner/tests/unit/test_venue_service.py` | MODIFY | fix the unique-violation double (F5b) |
| `packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py` | MODIFY | fix after root-causing (F5c) |

> **F5a design DECIDED (orchestrator, after the first attempt failed).** The
> `ui → api` edges are `ui/routes.py:27` (`requires_tenant`, a decorator applied
> at definition time — it cannot be deferred) and `ui/telegram.py:15`
> (`declared_tenant`). Any import of `parrot_formdesigner.api.*` runs
> `api/__init__`, so a deferred import or a sibling module under `api/` does not
> cut the edge. The shared tenant layer moves to a layer-neutral location
> (`core/`) and `api/tenant.py` / `api/errors.py` re-export it, so every existing
> `api` importer and test keeps working with the SAME objects.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.services._db_utils import is_unique_violation  # verified: services/_db_utils.py:8
from parrot_formdesigner.services.venue_service import (                # verified: services/venue_service.py:50
    DuplicateVenueError,
)
import importlib, sys   # stdlib — the layering test's mechanism (test_ui_imports.py:5-6)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/_db_utils.py  — DO NOT MODIFY
_UNIQUE_VIOLATION_CODE = "23505"                 # line 5
def is_unique_violation(exc: Exception) -> bool: # line 8
    if type(exc).__name__ == "UniqueViolationError":   # line 14
        return True
    sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)  # line 16
    if sqlstate == _UNIQUE_VIOLATION_CODE:             # line 17
        return True
    text = str(exc).lower()                            # line 19
    return "duplicate key" in text or "unique constraint" in text  # line 20

# packages/parrot-formdesigner/src/parrot_formdesigner/services/venue_service.py  — DO NOT MODIFY
class DuplicateVenueError(Exception):            # line 50
#   create_location(...) — lines 346-364:
#       except Exception as exc:
#           if is_unique_violation(exc):
#               raise DuplicateVenueError("location", name) from exc
#           raise

# packages/parrot-formdesigner/tests/unit/test_venue_service.py
    async def test_duplicate_location_raises(self) -> None:   # line 251
        conn = _make_conn(fetchrow_side_effect=Exception("23505 unique violation"))  # line 252-254
        with pytest.raises(DuplicateVenueError):              # line 256

# packages/parrot-formdesigner/tests/unit/ui/test_ui_imports.py
def test_importing_ui_does_not_pull_api():       # line 9
    # drops every parrot_formdesigner.ui* / .api* module from sys.modules (lines 17-21)
    importlib.import_module("parrot_formdesigner.ui")   # line 23
```

### Does NOT Exist
- ~~a lazy-import helper in `parrot_formdesigner.ui`~~ — verify what `ui/` actually does before assuming a pattern exists to copy.
- ~~`is_unique_violation` matching the substring `"unique violation"`~~ — it matches `"duplicate key"` or `"unique constraint"` only (`_db_utils.py:20`). This is exactly why F5b fails.
- ~~`asyncpg.exceptions.UniqueViolationError` being importable here~~ — `_db_utils.py` deliberately avoids driver imports and duck-types on `type(exc).__name__`; the test double should do the same rather than adding an asyncpg dependency.
- ~~`VenueService.create_location` swallowing non-unique errors~~ — it re-raises (`venue_service.py:364`); that is correct behaviour.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/tenant_errors.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/core/tenant.py", "action": "CREATE"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/errors.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/tenant.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/ui/telegram.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_requires_tenant.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_venue_service.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/_db_utils.py#is_unique_violation",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/venue_service.py#DuplicateVenueError"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **F5a is the only product change in this task.** Breaking an import edge can
  change what is registered at import time — run the `ui/` and `api/` test
  directories, not just the one failing test.
- **F5a is a shared-module extraction, NOT a deferred import.** A deferred
  `from ..api.tenant import ...` inside a method (the first attempt) leaves
  `test_ui_imports` red, because `ui/routes.py:27` imports `requires_tenant` at
  module level and it is used as a decorator. Do not use function-local imports.
- Move code **verbatim** (git will show a rename-with-edits). Change only
  import lines and module docstrings. No behaviour change, no renames.
- `api/errors.py` and `api/tenant.py` must stay importable with every name they
  exposed before, including `_get_programs`, `_is_superuser`, `_authorize`,
  `_Handler`, `_EXPECTED_HINT` and `logger` in `api/tenant.py` — re-export them
  explicitly (and list public ones in `__all__`). The classes/functions must be
  the *same objects* (`api.errors.TenantForbiddenError is core.tenant_errors.TenantForbiddenError`)
  so `except`/`pytest.raises` across both import paths keep working.
- `core/tenant.py` and `core/tenant_errors.py` must import nothing from
  `parrot_formdesigner.api`, `parrot_formdesigner.ui` or `parrot_formdesigner.handlers`.
- **F5b must not touch `_db_utils.py`.** Loosening `is_unique_violation` to
  match `"unique violation"` would make the production detector fire on
  arbitrary error text — the opposite of what this feature is for.
- For F5b, the cheapest faithful double is an exception carrying
  `sqlstate = "23505"` (the second check), or a message using the real Postgres
  wording `duplicate key value violates unique constraint "..."`. Either is
  closer to a real driver error than the current string.
- **F5c: diagnose first.** Do not change an assertion until you can say what the
  test is proving and which side is wrong.

### References in Codebase
- `services/_db_utils.py:8-20` — the three-way unique-violation detector.
- `services/venue_service.py:346-364` — the correct `create_location` handling.
- `tests/unit/test_venue_service.py:259-264` — a neighbouring test showing the `_make_conn` double's intended shape.

---

## Implementation Blueprint

### Steps (in order)
1. Re-confirm the edges (`grep -n "from \.\.api" packages/parrot-formdesigner/src/parrot_formdesigner/ui/*.py` → `routes.py:27`, `telegram.py:15`) — *why*: the design below assumes exactly these two.
2. Create `core/tenant_errors.py` and `core/tenant.py` (verbatim moves), turn `api/errors.py` / `api/tenant.py` into re-exports, repoint `ui/routes.py` and `ui/telegram.py` to `..core.tenant`, repoint `TestNoForbiddenReferences` to `core.tenant` — *why*: it is the only change that removes the import-time edge without altering behaviour.
3. Fix the venue double — *why*: the product detector is correct and must stay strict.
4. Root-cause and fix F5c — *why*: it is the only failure in the feature with no diagnosis yet.

### Locating the `ui → api` edge (F5a)
```bash
# Reproduce and name the chain, rather than guessing at the import:
python - <<'PY'
import sys, importlib
for k in [m for m in sys.modules if m.startswith("parrot_formdesigner")]:
    sys.modules.pop(k, None)
import importlib.util
seen = []
class Tracer:
    def find_module(self, name, path=None):
        if name.startswith("parrot_formdesigner.api"):
            seen.append(name)
        return None
sys.meta_path.insert(0, Tracer())
importlib.import_module("parrot_formdesigner.ui")
print("api modules pulled in:", seen)
PY
# Then: grep the ui/ tree for the importing module and read it.
```
**Why**: `test_ui_imports.py` only reports *that* the edge exists. Naming the
exact module first is what makes the fix a one-line deferral instead of a
refactor.

### F5a — shared tenant layer (CREATE ×2, MODIFY ×5)
```python
# core/tenant_errors.py  — verbatim body of api/errors.py (3 classes + json/aiohttp imports)
#   TenantNotDeclaredError, TenantForbiddenError, TenantConflictError
# core/tenant.py         — verbatim body of api/tenant.py, with
#   `from .tenant_errors import TenantConflictError, TenantForbiddenError, TenantNotDeclaredError`
#   (replaces `from .errors import ...`). Exposes requires_tenant, declared_tenant,
#   enforce_membership_unless_public, assert_body_tenant_matches, and the private helpers.

# api/errors.py  (after)
from ..core.tenant_errors import (  # noqa: F401
    TenantConflictError, TenantForbiddenError, TenantNotDeclaredError,
)
__all__ = ["TenantNotDeclaredError", "TenantForbiddenError", "TenantConflictError"]

# api/tenant.py  (after)  — keep a short docstring pointing at core/tenant.py
from ..core.tenant import (  # noqa: F401
    _EXPECTED_HINT, _Handler, _authorize, _get_programs, _is_superuser, logger,
    assert_body_tenant_matches, declared_tenant,
    enforce_membership_unless_public, requires_tenant,
)
from ..core.tenant_errors import (  # noqa: F401  (api/handlers.py & tests import these from here)
    TenantConflictError, TenantForbiddenError, TenantNotDeclaredError,
)
__all__ = ["requires_tenant", "declared_tenant", "enforce_membership_unless_public",
           "assert_body_tenant_matches", "TenantConflictError", "TenantForbiddenError",
           "TenantNotDeclaredError"]
# FILL IN: if api/tenant.py defines or exposes any other module-level name not
# listed above, re-export it too (diff `dir()` of the module before/after).

# ui/routes.py:27     from ..core.tenant import requires_tenant
# ui/telegram.py:15   from ..core.tenant import declared_tenant     (leave the call sites as they were)
# tests/unit/api/test_requires_tenant.py:135  `from parrot_formdesigner.core import tenant as tenant_module`
#   — the source-inspection test must read the module that now holds the code.
```
**Why**: `ui` must not import `parrot_formdesigner.api.*` at all (that runs
`api/__init__`). Both `api` and `ui` already depend on `core`, so the shared
tenant layer belongs there. Re-exporting from `api/` keeps ~10 importers and the
tenant test modules untouched.

### `packages/parrot-formdesigner/tests/unit/test_venue_service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'fetchrow_side_effect=Exception("23505 unique violation")' tests/unit/test_venue_service.py)
# REPLACE the double at tests/unit/test_venue_service.py:252-254, which reads:
#     conn = _make_conn(
#         fetchrow_side_effect=Exception("23505 unique violation")
#     )
#
# FILL IN: build an exception is_unique_violation() actually recognises —
# bounded by _db_utils.py:14-20 (three checks) and by the constraint that
# _db_utils.py is NOT modified. Pick ONE:
#   (a) an exception instance with `sqlstate = "23505"` set on it  → check 2
#   (b) a message using real Postgres wording, e.g.
#       'duplicate key value violates unique constraint "uq_location_site_name"'  → check 3
#   (c) a class literally named UniqueViolationError               → check 1
# (a) or (b) is preferred — they mirror what a real driver raises.
```
**Why**: the current string contains `"unique violation"`, which none of the three
checks look for — the test has never exercised the path it claims to. Fixing the
double makes it a real test of `create_location`'s error mapping.

### `packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py` (MODIFY)
```python
# FILL IN: root-cause `test_shortcut_equals_explicit` (fails with `assert None is not None`
# / `assert not True`) before editing anything. State in the Completion Note what
# the test proves, which side was wrong, and why — bounded by AC6 (no product
# behaviour changed merely to satisfy a test).
```
**Why**: this is the one failure in the whole feature with no diagnosis, so the
task fixes the *diagnosis* first and the code second.

### FILL IN checklist
- [ ] F5a — `core/tenant_errors.py`, `core/tenant.py` created; `api/errors.py`, `api/tenant.py` re-export; `ui/routes.py`, `ui/telegram.py` repointed; `TestNoForbiddenReferences` repointed; bounded by `test_ui_imports.py:9`
- [ ] `test_venue_service.py:252` — faithful unique-violation double; bounded by `_db_utils.py:14-20`
- [ ] `test_deterministic_integration.py` — root cause stated, correct side fixed; bounded by AC6

---

## Acceptance Criteria

- [ ] `test_importing_ui_does_not_pull_api` passes — `import parrot_formdesigner.ui` pulls no `parrot_formdesigner.api` module.
- [ ] `test_duplicate_location_raises` passes **without modifying** `services/_db_utils.py` or `services/venue_service.py`.
- [ ] `test_shortcut_equals_explicit` passes, with its root cause stated in the Completion Note.
- [ ] The whole `packages/parrot-formdesigner/tests` tree shows no new failures from the move — in particular `tests/unit/api/` (tenant tests), `tests/unit/ui/`, and every module importing `parrot_formdesigner.api.errors` / `.api.tenant`.
- [ ] `api.errors.TenantForbiddenError is core.tenant_errors.TenantForbiddenError` (same objects; `dir()` of `api.tenant` is a superset of what it exposed before).
- [ ] **AC6** No product behaviour changed to satisfy a stale test; the only product change is the verbatim F5a move of the tenant layer.
- [ ] **AC7** `ruff check` clean on every changed file.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/ui/test_ui_imports.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_venue_service.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_init_imports_metadata_only.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api packages/parrot-formdesigner/tests/unit/ui -q`

---

## Test Specification

No new test file — the 3 existing failures are the specification. F5a's test
already encodes the invariant; F5b's test becomes meaningful for the first time
once its double is faithful.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug tests-test-wheel-layout-tech-debt --feature-id FEAT-618`)
2. **Read the spec** §3 Module 7 and §2's taxonomy row **F5**.
3. **Check dependencies** — none.
4. **Verify the Codebase Contract** — re-confirm `_db_utils.py:8-20` and `venue_service.py:346-364`.
5. **Update status** in the per-spec index → `"in-progress"`.
6. **Implement** from the blueprint; run step 1's tracer before editing `ui/`.
7. **Verify** the Validation Commands. Prefix with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — stage only this task's files.
9. **Close** with `scripts/sdd/close_task.sh TASK-3914 tests-test-wheel-layout-tech-debt verified`.
10. **Fill in the Completion Note** with the F5c root cause and the new failure count.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: The `ui → api` edge that was cut; the F5c root cause; new failure count.

**Deviations from spec**: none | describe if any
