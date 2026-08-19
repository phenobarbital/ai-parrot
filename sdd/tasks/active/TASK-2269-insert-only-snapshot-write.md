# TASK-2269: Make publish's immutability guard real (insert-only snapshot write)

**Feature**: FEAT-433 — Form Version History — repair the read path
**Spec**: `sdd/specs/form-version-history-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2264
**Assigned-to**: unassigned

---

## Context

Spec Module 6 (raised by the maintainer review). `publish()` documents
*"the database UNIQUE constraint is the authoritative immutability guard —
two concurrent publishes cannot both succeed"* and wraps `_save_snapshot`
in an `is_unique_violation` handler. Against `PostgresFormStorage` that
guarantee **does not exist**: `_upsert_sql` ends in
`ON CONFLICT (form_uid, version) DO UPDATE`, so a collision is an
overwrite, never a violation — `is_unique_violation` never fires and a
frozen published snapshot is silently replaced.

The suite is green because the only backend the tests exercise is the
`InMemoryStorage` double, whose `save()` *raises* on a duplicate.
`test_unique_violation_surfaces_as_frozen_error` asserts a behaviour the
production SQL does not have — the double is stricter than the real thing,
the inverse of what a double may be.

**Why now**: with `_storage is None` the hole is unreachable.
**TASK-2264 makes it reachable.** Shipping that task without this one
introduces the regression.

---

## Scope

- Add an insert-only write path for snapshot publication:
  `INSERT … ON CONFLICT (form_uid, version) DO NOTHING RETURNING id`;
  an empty result means the tag exists → raise the frozen `ValueError`.
- Keep the existing UPSERT for the editor's save path, which legitimately
  rewrites a draft in place. **Two write paths, deliberately.**
- Point `_save_snapshot` at the insert-only path.
- Align the `InMemoryStorage` double with whichever contract the protocol
  declares, so the double stops being the stricter of the two.

**NOT in scope**: changing what `publish()` versions — whether publish
should promote in place instead of bumping to a new tag is spec §8 Q5,
open and explicitly out of this feature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../services/storage.py` | MODIFY | insert-only SQL + method; keep `_upsert_sql` for saves |
| `.../services/form_version.py` | MODIFY | `_save_snapshot` (`:497`) uses it |
| `packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py` | MODIFY | align the `InMemoryStorage` double (`:53`, `:224`) |

---

## Codebase Contract (Anti-Hallucination)

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py
    def _upsert_sql(self, tenant: str | None) -> str: ...   # line 173
    #   ... ON CONFLICT (form_uid, version) DO UPDATE        # line 187  ← the hole
    async def save(self, ...) -> None: ...                   # line 316

# packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py
    #   "the database UNIQUE constraint is the authoritative guard"  # lines 209-211 (docstring, currently false)
    async def _save_snapshot(self, snapshot, *, tenant) -> None: ... # line 497
from ._db_utils import is_unique_violation

# packages/parrot-formdesigner/tests/unit/test_feat300_review_fixes.py
class InMemoryStorage:  # line 53 — save() raises RuntimeError("duplicate key value violates...")
def test_unique_violation_surfaces_as_frozen_error(...)  # line 224
```

### Does NOT Exist
- ~~a UNIQUE-violation path in the current production SQL~~ — the
  constraint exists on the table, but `DO UPDATE` means it is never
  violated

---

## Implementation Notes

### Key Constraints
- Do **not** replace the editor's UPSERT. Saves must keep rewriting a
  draft in place; only snapshot publication is insert-only.
- `DO NOTHING RETURNING id` returns no row on conflict — treat the empty
  result as the collision signal; do not rely on rowcount semantics that
  differ between drivers.
- Once real, the guard makes `publish()` raise where it used to overwrite.
  That is the point, and it pairs with TASK-2268 making the pre-check
  honest.
- Fix the docstring at `:209-211` in the same change — it currently
  documents a guarantee that does not hold.

---

## Acceptance Criteria

- [ ] The snapshot path emits `ON CONFLICT … DO NOTHING`, not `DO UPDATE`
- [ ] Publishing over an existing tag raises `ValueError` **and** leaves
      the stored row byte-identical
- [ ] The editor's save path still upserts (a draft rewrite still works)
- [ ] The `InMemoryStorage` double and `PostgresFormStorage` agree on
      duplicate-key behaviour for **both** write paths
- [ ] The `:209-211` docstring describes the guard that now exists
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` passes

---

## Test Specification

```python
async def test_publish_over_existing_tag_raises_not_overwrites(...): ...
async def test_snapshot_write_is_insert_only(...): ...
async def test_inmemory_double_matches_postgres_contract(...): ...
async def test_publish_twice_same_tag_does_not_overwrite(pg_storage): ...  # integration
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
