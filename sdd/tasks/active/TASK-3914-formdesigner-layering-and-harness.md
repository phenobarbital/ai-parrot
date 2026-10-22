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

- **F5a**: locate the `ui → api` import edge and break it, so
  `import parrot_formdesigner.ui` no longer pulls `parrot_formdesigner.api`.
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
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/__init__.py` | MODIFY | break the transitive `api` import (F5a) |
| `packages/parrot-formdesigner/tests/unit/test_venue_service.py` | MODIFY | fix the unique-violation double (F5b) |
| `packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py` | MODIFY | fix after root-causing (F5c) |

> The exact `ui/` file carrying the offending import is **not** pre-identified —
> step 1 of the blueprint locates it. If it is not `ui/__init__.py`, correct this
> table in the task file before implementing.

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
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/ui/__init__.py", "action": "MODIFY"},
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
- Prefer a function-local (deferred) import or a shared-module extraction over
  deleting a re-export that callers depend on. Check who imports the symbol
  before moving it.
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
1. Locate the `ui → api` edge — *why*: the fix is unknowable until the actual import chain is known.
2. Break it with the least invasive change — *why*: `ui/` and `api/` are both mounted in production; a careless move changes registration order.
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

### `packages/parrot-formdesigner/src/parrot_formdesigner/ui/<module>.py` (MODIFY)
```python
# FILL IN: break the transitive import of parrot_formdesigner.api found in step 1
# — bounded by test_ui_imports.py:9 (ui must be independently mountable) and by
# the constraint that no public name exported from ui/ disappears.
# Preferred shapes, in order:
#   1. move the `from ..api import X` inside the function that uses it (deferred import)
#   2. extract the shared symbol into a module that neither ui/ nor api/ owns
#   3. only if neither works: re-export via a lazy module __getattr__
# Correct the "Files to Create / Modify" table above if the module is not ui/__init__.py.
```
**Why**: a deferred import removes the import-time edge while keeping the call
site working, which is why it is tried first. Deleting the import outright would
break whatever uses the symbol at runtime.

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
- [ ] `ui/<module>.py` — break the `api` import edge; bounded by `test_ui_imports.py:9`
- [ ] `test_venue_service.py:252` — faithful unique-violation double; bounded by `_db_utils.py:14-20`
- [ ] `test_deterministic_integration.py` — root cause stated, correct side fixed; bounded by AC6
- [ ] "Files to Create / Modify" table corrected if the `ui/` module differs

---

## Acceptance Criteria

- [ ] `test_importing_ui_does_not_pull_api` passes — `import parrot_formdesigner.ui` pulls no `parrot_formdesigner.api` module.
- [ ] `test_duplicate_location_raises` passes **without modifying** `services/_db_utils.py` or `services/venue_service.py`.
- [ ] `test_shortcut_equals_explicit` passes, with its root cause stated in the Completion Note.
- [ ] The `ui/` and `api/` test directories show no new failures from the import change.
- [ ] **AC6** No product behaviour changed to satisfy a stale test; the only product change is the F5a import edge.
- [ ] **AC7** `ruff check` clean on every changed file.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/ui/test_ui_imports.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_venue_service.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_deterministic_integration.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_init_imports_metadata_only.py -q`

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
