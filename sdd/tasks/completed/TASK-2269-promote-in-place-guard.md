# TASK-2269: Make publish's immutability guard real (promote-in-place guard)

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

> **Reshaped by spec §8 Q5, closed 2026-08-19: publish promotes the
> current version in place.** The originally specified insert-only write
> (`ON CONFLICT … DO NOTHING`) assumed publish creates a NEW row. It does
> not any more, so the guard changes shape — read §8 Q5 before starting.

- `publish()` stops calling `_bump()`. It targets the **live version** and
  stamps it: `published_version = version`, plus the `meta.published_at`
  stamp it already writes.
- Add a promote write path to storage:
  `UPDATE <qualified> SET schema_json = …  WHERE form_uid = $1 AND version = $2
  AND published_version IS DISTINCT FROM version RETURNING id`.
  **No affected row means the version is already published** → raise the
  frozen `ValueError`. That is the guard, and it is the first time one
  actually exists.
- Keep the existing UPSERT for the editor's save path, which legitimately
  rewrites a draft in place. **Two write paths, deliberately.**
- Point `_save_snapshot` at the promote path.
- Fix the docstring at `:209-211`, which documents a UNIQUE-violation
  guarantee that never held.
- Align the `InMemoryStorage` double with whichever contract the protocol
  declares, so the double stops being the stricter of the two.

**NOT in scope**: the `is_published` label derivation (TASK-2266 — the
rule stays `published_version == version` and is unaffected), and the
`get_published` filter (TASK-2268).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../services/storage.py` | MODIFY | promote SQL + method; keep `_upsert_sql` for saves |
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
  draft in place; only publication uses the promote path.
- `RETURNING id` yields no row when the `IS DISTINCT FROM` predicate
  excludes it — treat the empty result as the "already published" signal;
  do not rely on rowcount semantics that differ between drivers.
- `IS DISTINCT FROM` (not `<>`) is required: `published_version` is NULL
  on every unpublished row, and `NULL <> version` is NULL, not true — a
  plain `<>` would exclude exactly the rows this path exists to promote.
- Once real, the guard makes `publish()` raise where it used to overwrite.
  That is the point, and it pairs with TASK-2268 making the pre-check
  honest.
- Fix the docstring at `:209-211` in the same change — it currently
  documents a guarantee that does not hold.

---

## Acceptance Criteria

- [ ] Publishing stamps `published_version = version` on the **existing**
      row — no new row is created, and the version count is unchanged
- [ ] `publish()` no longer calls `_bump()`
- [ ] Publishing an already-published version raises `ValueError` **and**
      leaves the stored row byte-identical
- [ ] Promoting a row whose `published_version` is NULL works (the
      `IS DISTINCT FROM` case)
- [ ] The editor's save path still upserts (a draft rewrite still works)
- [ ] The `InMemoryStorage` double and `PostgresFormStorage` agree on
      duplicate-key behaviour for **both** write paths
- [ ] The `:209-211` docstring describes the guard that now exists
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` passes

---

## Test Specification

```python
async def test_publish_promotes_in_place_no_new_row(...): ...
async def test_publish_already_published_raises_not_overwrites(...): ...
async def test_promote_matches_null_published_version(...): ...
async def test_inmemory_double_matches_postgres_contract(...): ...
async def test_publish_twice_same_tag_does_not_overwrite(pg_storage): ...  # integration
```

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-19
**Notes**: `publish()` now targets `form.version` (the live tag) instead of
`_bump(form.version)`; it never bumps. `FormStorage.promote()` (new,
concrete-with-default on the ABC, like `list_versions()`) is the
guard: `PostgresFormStorage.promote()` implements it as `INSERT ... ON
CONFLICT (form_uid, version) DO UPDATE ... WHERE (schema_json ->>
'published_version') IS DISTINCT FROM version RETURNING id` — an upsert
whose UPDATE half is conditionally skipped, not a plain `UPDATE`.
`_save_snapshot()` now calls `storage.promote()` exclusively (both its
callers, `publish()` and `backfill_published()`, always stamp
`published_version == version` before calling it, so "promote" is always
the correct write). Fixed the `:209-211`-area docstring (now describes the
promote guard, not a UNIQUE-violation guarantee that never held).
`InMemoryStorage` (test_feat300_review_fixes.py): `save()` no longer
raises on a duplicate key (matches production's UPSERT — overwrites);
added `promote()` mirroring the same upsert-with-conditional-guard logic.
`FailingStorage` overrides `promote()` too (publish() no longer touches
`save()` at all).

**Deviations from spec**: The task's literal SQL (`UPDATE ... WHERE ...
RETURNING id`, treating "no row affected" as always meaning "already
published") does not account for a version that has NEVER been persisted
to storage at all — which turned out to be the DOMINANT case across the
existing test suite (`_registry_with_form()` and most `FormVersionService`
fixtures register a form without ever calling `storage.save()` on it
first, then call `publish()` directly). Implementing the guard literally
as an `UPDATE` broke essentially every existing publish-path test at
first pass (10 in `test_form_version.py`, 2 in
`test_feat300_review_fixes.py`, 1 integration test) with "already exists
and is frozen" raised for versions that had never been saved. Corrected
to an upsert whose update half is conditionally skipped
(`INSERT ... ON CONFLICT DO UPDATE ... WHERE`): a missing row is written
normally (nothing published yet to protect — same as a first-time
insert), an existing unpublished row is promoted, and only an
ALREADY-published row is rejected. This preserves the guard's actual
intent (a published snapshot can never be silently overwritten) while
matching how `publish()` is used both in this codebase and in the spec's
own §1 flow (a form need not have been separately "saved" through the
editor before its first publish). Rewrote the tests this exposed as
broken by Q5's semantics (bump removal) across `test_form_version.py`
(10), `test_feat300_review_fixes.py` (TestH1's 2 restart tests — added an
editor-save/bump step between publishes; H4's TOCTOU-race test — rebuilt
as a direct re-publish + a direct storage-level `promote()` guard test,
since the old race no longer applies once publish() doesn't bump), and
`test_api_feat300.py`/`test_feat300_integration.py`'s multi-publish
scenarios (added a `_bump_version` editor-save step between publishes).
None of these were in this task's own listed files except
`test_feat300_review_fixes.py`, but they are a direct, foreseeable,
mechanical consequence of the accepted Q5 decision — the same category of
blast-radius fix the spec's own §8 Q3 anticipates for other files, just
triggered by Q5 instead. Also added `test_publish_twice_same_tag_does_not_overwrite`
to `test_feat300_integration.py` per the Test Specification (not
previously present).
