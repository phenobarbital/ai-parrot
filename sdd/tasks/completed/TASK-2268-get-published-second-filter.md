# TASK-2268: `get_published()` — drop the second filter site

**Feature**: FEAT-433 — Form Version History — repair the read path
**Spec**: `sdd/specs/form-version-history-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec Module 5 (raised by the maintainer review; the original submission
missed it). `get_published` applies the identical
`snap.published_version == version` filter before returning a snapshot, so
`GET /api/v1/{tenant}/forms/{uid}/versions/{version}` returns **404 for
every version the editor ever saved** — all 105 measured rows.

Without this task, TASK-2264/2265/2266 would ship a repaired history list
in which **every entry 404s when clicked**. That is the regression this
task exists to prevent, so it must land in the same release even though it
has no code dependency on the others.

It also repairs `publish()`'s fast-path pre-check (`:193`), which calls
`get_published`: with the filter in place the check returns `None` for an
existing *draft* row at the target tag, so the pre-check silently passes
on a real collision.

---

## Scope

- Remove the `published_version == version` condition from
  `get_published`; return the stored snapshot for any version, draft or
  published. The returned `FormSchema` still carries `published_version`,
  so callers can tell the two apart.
- Keep the in-memory fallback path behaving consistently.
- Tests, including the anti-regression that every entry returned by
  `GET .../versions` resolves 200 on `GET .../versions/{version}`.

**NOT in scope**: renaming `get_published` (public API — optional, out of
scope; if it is ever done, keep an alias). The real immutability guard is
TASK-2269.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../services/form_version.py` | MODIFY | `get_published` (`:243`) |
| `packages/parrot-formdesigner/tests/unit/test_form_version.py` | MODIFY | draft retrievable |
| `packages/parrot-formdesigner/tests/integration/test_feat300_integration.py` | MODIFY | list↔fetch parity |

---

## Codebase Contract (Anti-Hallucination)

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py
    async def get_published(self, form_uid, *, version, tenant) -> FormSchema | None:  # line 243
        if self._storage is not None:
            snap = await self._storage.load(form_uid, version=version, tenant=tenant)
            if snap is not None and snap.published_version == version:   # ← the filter to drop
                return snap

    async def publish(self, form_uid, *, tenant, bump="minor") -> str:   # line 158
        existing = await self.get_published(form_uid, version=new_version, tenant=tenant)  # line ~193

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
    async def get_version(self, request) -> web.Response: ...            # line 1946
```

### Does NOT Exist
- ~~a separate `get_draft()`~~ — one accessor serves both states

---

## Implementation Notes

### Key Constraints
- This changes what `publish()`'s pre-check sees: it will now find draft
  rows at the target version and raise the frozen `ValueError` where it
  used to pass.
- **Coordinate with TASK-2269 (spec §8 Q5, closed 2026-08-19).** With
  publish promoting in place there is no *bumped* tag to pre-check: the
  question becomes "is the **live** version already published?". Keep the
  pre-check honest under that target, and let TASK-2269's promote guard be
  the authoritative one. That is the intended correction — the pre-check is a fast path,
  and TASK-2269 provides the authoritative guard.
- The method name becomes a misnomer once the filter is gone. Update the
  docstring; leave the name.

---

## Acceptance Criteria

- [ ] `get_published()` returns a row whose `published_version != version`
      instead of `None`
- [ ] Every entry returned by `GET .../versions` resolves 200 on
      `GET .../versions/{version}` — the anti-regression for
      "list works, clicking 404s"
- [ ] `publish()`'s pre-check no longer passes silently on an existing
      draft row at the target tag
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` passes

---

## Test Specification

```python
async def test_get_published_returns_draft_version(...): ...
async def test_get_version_endpoint_serves_every_listed_version(...): ...
```

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-19
**Notes**: Removed the `snap.published_version == version` filter from
`get_published()` — it now returns any stored snapshot at `version`,
draft or published. This automatically makes `publish()`'s fast-path
pre-check (which calls `get_published()`) honest: it now sees an existing
draft row at the target tag instead of silently passing, satisfying that
acceptance criterion with no separate code change (verified with a
dedicated test simulating the same stale-live-version race H4 already
covers for the storage-level path). In-memory `_snapshots` fallback is
unaffected — it's populated only by `publish()`/`backfill_published()`, so
every entry there was already "published"; removing the filter changes
nothing observable on that branch, confirmed by the existing RF-06 test
(`test_publish_then_edit_isolation`) still passing unmodified. Added the
anti-regression at both unit (`test_form_version.py`,
`_LoadableStorage` double) and integration (`test_feat300_integration.py`,
`_ListFetchStorage` double) level: every entry `list_versions()` returns
resolves via `get_published()`.
**Deviations from spec**: none — kept the `get_published` name (renaming
is explicitly optional/out of scope per the task), only updated its
docstring to describe the corrected behavior.
