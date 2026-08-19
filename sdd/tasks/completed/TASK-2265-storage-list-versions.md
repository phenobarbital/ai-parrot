# TASK-2265: FormStorage.list_versions() — one ordered query, no probing

**Feature**: FEAT-433 — Form Version History — repair the read path
**Spec**: `sdd/specs/form-version-history-repair.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2264
**Assigned-to**: unassigned

---

## Context

Spec Module 2. History is currently reconstructed by probing storage one
candidate version at a time (`_probe_storage_versions`), giving up after
two consecutive misses and capped at `_MAX_VERSION_PROBES = 200`. A
15-version form costs ~16 sequential round-trips, and any two-version gap
truncates everything after it.

Replace it with a first-class storage method: one query, ordered on the
parsed `(major, minor)` integers.

---

## Scope

- Add `list_versions()` to the `FormStorage` protocol and implement it on
  `PostgresFormStorage`, with the SQL in spec §2 verbatim — **projected
  columns, not `schema_json` whole**, and the **guarded `CASE` cast**.
- Rewrite `FormVersionService.list_versions` to call it.
- Delete `_probe_storage_versions` and `_MAX_VERSION_PROBES`.
- Keep merging in-process `_meta` entries, keyed by version; on conflict
  **the storage row wins** (a `_meta` entry is an in-process echo of a
  publish that already wrote a row), so a restart never changes an answer.
- Sort the merged result with `_parse_major_minor`.

**NOT in scope**: the `is_published` label and the response key
(TASK-2266) — this task keeps `list_versions` returning whatever it
returns today, only sourced correctly.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../services/storage.py` | MODIFY | protocol method + `PostgresFormStorage.list_versions()` + SQL builder |
| `.../services/form_version.py` | MODIFY | `list_versions` delegates; delete probing |
| `packages/parrot-formdesigner/tests/unit/test_form_version.py` | MODIFY | ordering, single-query, gap tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/storage.py
class PostgresFormStorage:
    def _resolve_schema(self, tenant: str | None) -> str: ...   # line 135
    def _qualified(self, tenant: str | None) -> str: ...        # line 147
    def _list_sql(self, tenant: str | None) -> str: ...         # line 217  ← shape to mirror

# packages/parrot-formdesigner/src/parrot_formdesigner/services/form_version.py
_MAX_VERSION_PROBES = 200                                       # line 30   ← delete
def _parse_major_minor(version: str) -> tuple[int, int]: ...    # line 69
class FormVersionService:
    async def list_versions(self, form_uid, *, tenant) -> list[VersionMeta]: ...  # line 275
    async def _probe_storage_versions(self, form_uid, *, tenant) -> list[str]: ...# line 316 ← delete
```

### The SQL (spec §2 — use as written)
```sql
SELECT version,
       created_at,
       updated_at,
       schema_json ->> 'form_id'                AS form_id,
       schema_json ->> 'published_version'      AS published_version,
       schema_json -> 'meta' ->> 'published_at' AS published_at
FROM <qualified>
WHERE form_uid = $1
ORDER BY CASE WHEN version ~ '^[0-9]+\.[0-9]+$'
              THEN split_part(version, '.', 1)::int END NULLS LAST,
         CASE WHEN version ~ '^[0-9]+\.[0-9]+$'
              THEN split_part(version, '.', 2)::int END NULLS LAST,
         version
```

### Does NOT Exist
- ~~`FormStorage.list_versions()`~~ — this task introduces it; its absence
  is precisely why the probing loop was written
- ~~`form_schemas.published_version`~~ — not a column; it lives inside
  `schema_json`, hence the `->>` projection

---

## Implementation Notes

### Key Constraints
- **Never interpolate a schema name.** Build the target through
  `_qualified()`, exactly as `_list_sql` does.
- **Do not drop the `CASE` guard.** `version` is a free `VARCHAR(50)` with
  no CHECK; a bare `::int` raises `22P02` and would 500 the endpoint for
  the whole form instead of mis-sorting one row. Unparseable versions sort
  last, deterministically, by raw string.
- **Project, do not haul.** Selecting `schema_json` whole would transfer
  15 complete schemas to compute six scalars.
- Async throughout, through the existing pool.

---

## Acceptance Criteria

- [ ] `PostgresFormStorage.list_versions()` exists and is on the protocol
- [ ] Listing a 15-version form issues **exactly one** storage call
- [ ] `1.0…1.14` come back in that order (`1.9` before `1.10`, `1.14` last)
- [ ] Deleting `1.2` and `1.3` still lists `1.4`+ (no truncation)
- [ ] A row with `version='draft-x'` sorts last and does **not** raise `22P02`
- [ ] The SQL selects the projected columns, not `schema_json`
- [ ] `_probe_storage_versions` and `_MAX_VERSION_PROBES` no longer exist
- [ ] `pytest packages/parrot-formdesigner/tests/ -v` passes

---

## Test Specification

```python
async def test_list_versions_single_query(spy_storage, form_with_15_versions): ...
async def test_list_versions_orders_past_ten(pg_storage, form_with_15_versions): ...
async def test_list_versions_survives_gaps(pg_storage, form_with_gap): ...
async def test_list_versions_orders_unparseable_last(pg_storage): ...
async def test_list_versions_projects_not_hauls(pg_storage): ...
```

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-19
**Notes**: Added `FormStorage.list_versions()` (registry.py) as a concrete
(non-abstract) method returning `[]` by default — NOT abstract, deliberately:
making it abstract would break every existing `FormStorage` subclass that
predates this task (`DummyStorage`/`StorageWithoutInit` in
`test_registry_lifecycle.py`, `_FakeFormStorage` added by TASK-2264) at
construction time, which is out of scope for this task and would violate
file-fidelity. `PostgresFormStorage.list_versions()` + `_list_versions_sql()`
implement the SQL verbatim from spec §2 (projected columns, guarded `CASE`
cast, `NULLS LAST`). `FormVersionService.list_versions()` now calls
`storage.list_versions()` once instead of probing; `_probe_storage_versions`
and `_MAX_VERSION_PROBES` are deleted. Kept "today's" `published_version ==
version` gate in the merge (demoting it to a label is TASK-2266's job, not
this one's — confirmed by the task's own "NOT in scope" note). Added
`_published_at_from_row()` as a dict-shaped sibling of
`_published_at_from_snapshot()` (same precedence, still falls back to
`datetime.now()` — TASK-2266 removes that fallback).

**Deviations from spec**: Added `list_versions()` to the `InMemoryStorage`
test double in `test_feat300_review_fixes.py` (not in this task's listed
files) — required to keep `TestH1HistorySurvivesRestart` passing, since
`FormVersionService.list_versions()` now calls `storage.list_versions()`
instead of probing via `.load()`; without it that double would silently
return `[]` for every version. This is the same kind of mechanical,
spec-mandated blast-radius fix the spec's own §8 Q3 describes for other
files, just for a file not explicitly enumerated by this task (it IS
already listed as a TASK-2269 file, so the coupling was expected, just
sequenced earlier here). No other file was touched beyond this task's list
plus that one addition.
