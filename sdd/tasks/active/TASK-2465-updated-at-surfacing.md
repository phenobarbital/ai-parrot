# TASK-2465: Surface `updated_at` on WikiPageRecord and honor caller-provided stamps

**Feature**: FEAT-461 — wikitoolkit Environment Support (env-aware config + memory sync)
**Spec**: `sdd/specs/wikitoolkit-env-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4, with an **important correction discovered during task
decomposition**: both backends ALREADY persist `created_at`/`updated_at` —
the sqlite `pages` DDL has had `created_at TEXT NOT NULL, updated_at TEXT
NOT NULL` since the original FEAT-260 schema (store.py:87-88 area), and the
Arango store stamps both on upsert (arango_store.py:547-548). What is
missing for sync (TASK-2466):

1. `WikiPageRecord` does not CARRY the timestamps, so callers can't read or
   compare them.
2. Both backends unconditionally stamp `updated_at = now` on upsert
   (store.py:820 `now = _now_iso()` used for both values;
   arango_store.py:547-548) — sync must be able to PRESERVE the source's
   `updated_at` when replicating a record, otherwise every pushed record
   looks "newer" at the destination and LWW breaks.

No `ALTER TABLE` migration is needed (contrary to the spec's §7 note —
columns already exist); this task is model surfacing + upsert semantics.

---

## Scope

- Add `updated_at: Optional[str] = None` (ISO-8601 UTC) to `WikiPageRecord`
  (store.py:215). Document: `None` on write means "stamp now"; on read it is
  always populated from the DB.
- sqlite backend (`store.py`): populate `updated_at` in every read path that
  builds page dicts/records (the SELECT at store.py:1094 already fetches
  it — surface it); on upsert (store.py:820-850), use `p.updated_at or now`
  for the `updated_at` column (keep `created_at` behavior: `now` on insert,
  untouched on conflict-update — verify the ON CONFLICT clause does not
  overwrite `created_at`; it currently doesn't).
- Arango backend (`arango_store.py`): same semantics — honor
  `p.updated_at` when provided (arango_store.py:547-548), keep stamping when
  absent; read paths already return `updated_at` (arango_store.py:829, 978)
  — ensure it lands on returned dicts consistently.
- `toolkit.py`: authoring surfaces (`remember()` at toolkit.py:944,
  `update_page`, and the note writer in `tools.py` WikiNoteTool) may keep
  passing no stamp (backend stamps now) — verify and add a regression test
  that a `remember()` round-trip yields a fresh ISO-8601 `updated_at`.
- Ordering contract for sync: records with `updated_at=None` (defensive —
  should not occur given NOT NULL columns) sort OLDEST.
- Write tests per the Test Specification.

**NOT in scope**: the sync engine itself (TASK-2466); env config
(TASK-2462/2463/2464).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | model field + sqlite read surfacing + upsert honors caller stamp |
| `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` | MODIFY | upsert honors caller stamp; read consistency |
| `tests/knowledge/wiki/test_updated_at.py` | CREATE | round-trip + preserve-stamp + ordering tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import WikiPageRecord, BaseWikiStore  # store.py:215, 289
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
# sqlite DDL (module constant, ~line 78-91): pages has
#   created_at  TEXT NOT NULL,
#   updated_at  TEXT NOT NULL,
# _MIGRATION_COLUMNS (line ~117-124) covers only origin/asserted_by —
#   created_at/updated_at are ORIGINAL columns; no migration entry needed.
class WikiPageRecord(BaseModel):                 # line 215
    concept_id: str                              # line 234
    origin: str = "ingest"                       # line 242
    asserted_by: Optional[str] = None            # line 243
    # NO timestamp fields today — THIS task adds updated_at.
class BaseWikiStore(ABC):                        # line 289
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int  # line 308
    async def add_edges(self, edges: list[tuple]) -> int              # line 311
    async def get_page(...)                                           # line 331
    async def list_pages(..., origin: Optional[list[str]] = None)     # lines 336-340
# sqlite upsert (lines ~820-850): now = _now_iso(); INSERT ... VALUES uses
#   `now` for BOTH created_at and updated_at; ON CONFLICT SET updates
#   updated_at=excluded.updated_at (created_at NOT in the update set).
# sqlite get_page SELECT already fetches created_at, updated_at (line 1094).

# packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py
# upsert doc build stamps "created_at": now, "updated_at": now (lines 547-548)
# read AQL already projects updated_at (lines 559, 825-829, 977-978)
```

### Does NOT Exist
- ~~`WikiPageRecord.updated_at` / `created_at`~~ — model fields do not exist
  yet; THIS task adds `updated_at` (NOT `created_at` — leave creation
  stamping fully backend-side).
- ~~an `ALTER TABLE` need for updated_at~~ — the columns already exist in
  the original DDL; do NOT add a `_MIGRATION_COLUMNS` entry for them.
- ~~store-level "preserve timestamp" flag~~ — the contract is simply
  `p.updated_at or now` inside the backends; no new method parameters.

---

## Implementation Notes

### Pattern to Follow
```python
# sqlite upsert value change (store.py ~845):
#   before: now,          # updated_at
#   after:  p.updated_at or now,
# Same idea in arango_store.py doc construction (~547-548).
```

### Key Constraints
- ISO-8601 UTC strings throughout (match the existing `_now_iso()` format —
  lexicographic comparison must equal chronological comparison).
- Backwards compatible: existing callers pass no `updated_at` → behavior
  identical to today (stamp now).
- Do NOT surface `created_at` on the model in this task (YAGNI; sync only
  needs `updated_at`).

### References in Codebase
- `store.py:799-860` — migration helper + upsert (the exact SQL to touch).
- `arango_store.py:540-560` — doc construction on upsert.
- `tests/knowledge/wiki/` — store test conventions (tmp sqlite planes).

---

## Acceptance Criteria

- [ ] `WikiPageRecord.updated_at: Optional[str]` exists; reads populate it
  from both backends (`get_page`, `list_pages` results include it).
- [ ] Upsert with `updated_at=None` stamps now (both backends) — existing
  behavior preserved.
- [ ] Upsert with an explicit `updated_at` preserves it verbatim (both
  backends) — the sync prerequisite.
- [ ] `remember()` round-trip yields a fresh ISO-8601 `updated_at`.
- [ ] `created_at` is never overwritten on conflict-update (regression test).
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_updated_at.py -v`
- [ ] No linting errors on touched files.

---

## Test Specification

```python
# tests/knowledge/wiki/test_updated_at.py

class TestSqliteUpdatedAt:
    async def test_upsert_stamps_now_when_none(self, tmp_path): ...
    async def test_upsert_preserves_explicit_stamp(self, tmp_path): ...
    async def test_get_page_and_list_pages_return_updated_at(self, tmp_path): ...
    async def test_created_at_survives_conflict_update(self, tmp_path): ...

class TestRememberStamp:
    async def test_remember_roundtrip_has_fresh_iso_stamp(self, tmp_path): ...
```

(Arango variants marked with the existing arango-availability skip decorator
used by the suite; the sqlite tests are the required gate.)

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/wikitoolkit-env-support.spec.md` (§3 Module 4, §6, §7)
   — NOTE the correction in this task's Context (columns already exist).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** before writing ANY code.
4. **Update status** in `sdd/tasks/index/wikitoolkit-env-support.json` → `"in-progress"`.
5. **Implement**, then verify all acceptance criteria.
6. **Move this file** to `sdd/tasks/completed/`.
7. **Update index** → `"done"` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
