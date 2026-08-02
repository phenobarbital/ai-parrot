# TASK-2073: Sources decision columns migration + bookkeeper triage tags

**Feature**: FEAT-402 — Supervised Wiki Ingestion (charter-driven triage + HITL manifest review)
**Spec**: `sdd/specs/supervised-wiki-ingestion.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2070
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec (§3). Triage decisions must be
persisted per source (destination, provenance, charter version, composite)
so re-runs, audits, and staleness checks see them — and every decision must
surface in `wikitoolkit audit` via the bookkeeper. Pre-FEAT-402 wiki
databases MUST keep opening cleanly (additive migration only).

---

## Scope

- Extend the `sources` table schema and add an additive migration:
  - New columns: `destination TEXT` (`wiki|archive|discard`),
    `decision_source TEXT` (`heuristic|model|human|auto`),
    `charter_version TEXT`, `composite_score REAL` — all
    nullable/defaulted so old DBs open cleanly.
  - Update the base DDL in `store.py` (schema string, lines 58-66) AND add
    an idempotent `ALTER TABLE ... ADD COLUMN` upgrade path for existing
    databases (guard on `PRAGMA table_info(sources)` — follow the
    `_migrate_json_manifest` compatibility precedent for tone/placement).
- Extend `SourceCollectionManager`:
  - Persist the four fields on the ingest/reject path (extend
    `mark_ingested` or add a sibling `record_decision(...)` — keep the
    existing signature backward-compatible: new params optional).
  - Rejected docs: recorded with `status="rejected"`, never ingested.
  - `SourceManifestEntry` (models.py:142) gains matching optional fields.
- Bookkeeper wiring helper: log `TRIAGE` / `ADMIT` / `ARCHIVE` / `DISCARD`
  operations via `WikiBookkeeper.log_operation` (free-string tags — do NOT
  invent an enum). A small helper in `review.py` or `sources.py` (pick one,
  document) formats the details line (source uri, composite, decision_source).
- Write/extend tests: `tests/knowledge/wiki/test_sources.py` (+ a bookkeeper
  tag assertion in `test_bookkeeper.py` if natural).

**NOT in scope**: the triage logic that produces decisions (TASK-2071),
orchestrator calls (TASK-2074), ArangoDB decision persistence (document as
follow-up if the async Arango path needs parity — do not block on it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | sources DDL + idempotent column migration |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | MODIFY | persist decision fields; rejected path |
| `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | MODIFY | `SourceManifestEntry` optional decision fields |
| `tests/knowledge/wiki/test_sources.py` | MODIFY | migration + persistence tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `ad6365242` (2026-08-02).

### Verified Imports
```python
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.models import SourceManifestEntry
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:58-66 — the sources DDL lives HERE:
# CREATE TABLE IF NOT EXISTS sources (
#     source_id       TEXT PRIMARY KEY,
#     source_uri      TEXT NOT NULL UNIQUE,
#     file_hash       TEXT NOT NULL,
#     mtime           REAL NOT NULL,
#     ingested_at     TEXT NOT NULL,
#     pages_generated TEXT NOT NULL DEFAULT '[]',
#     status          TEXT NOT NULL DEFAULT 'ingested'
# );                                            -- 7 columns today

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
class SourceCollectionManager:                   # line 47; __init__ 72
    def add_source(self, path: Path) -> SourceManifestEntry: ...                  # 160
    def is_stale(self, source_id: str) -> bool: ...                               # 239
    def mark_ingested(self, source_id: str, pages_generated: list[str],
                      status: str = "ingested") -> Optional[SourceManifestEntry]: ...  # 282-287
    def _migrate_json_manifest(self) -> None: ...                                 # 657 (compatibility precedent)
    def _connect(self, ...): ...                                                  # 367
    def _upsert(self, ...): ...                                                   # 379
    def _row_to_entry(self, ...): ...                                             # 410
    # ArangoDB async path: _async_* at 600-656; JSON/memory backend: _load_manifest 697, _save_manifest 726

# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class SourceManifestEntry(BaseModel): ...        # line 142

# packages/ai-parrot/src/parrot/knowledge/wiki/bookkeeper.py
class WikiBookkeeper:                            # line 31; LOG_FILENAME = "log.md" (45)
    def log_operation(self, wiki_dir: Path, operation: str, details: str,
                      timestamp: Optional[str] = None) -> None: ...   # 175-181
    # operation is a FREE STRING, upper-cased at write time (:199) — tags in tree:
    # INGEST, QUERY, LINT, REMEMBER, NOTE, LINK. Adding TRIAGE/ADMIT/ARCHIVE/DISCARD
    # requires NO schema change.
    def read_log(self, wiki_dir: Path, last_n: int = 50, ...): ...    # 207
```

### Does NOT Exist
- ~~a `WikiBookkeeper` operation enum~~ — tags are free strings; do not create an enum.
- ~~sources DDL in `sources.py`~~ — the CREATE TABLE lives in `store.py:58-66`; `sources.py` only reads/writes rows.
- ~~`destination` / `decision_source` / `charter_version` / `composite_score` columns~~ — you are adding them (7 columns today).
- ~~`record_decision`~~ — does not exist yet; if you add it, it is new API.

---

## Implementation Notes

### Key Constraints
- Migration MUST be idempotent (safe to run on already-migrated DBs) and
  additive-only — never rewrite or drop existing rows/columns.
- `_row_to_entry` (:410) must tolerate both old rows (columns absent/NULL)
  and new rows.
- SQLite work stays sync inside the manager (existing pattern) — callers
  offload via `asyncio.to_thread` as today.
- Keep `mark_ingested`'s existing call sites working (check
  `wiki/ingest.py` and `wiki/cli.py::_ingest_files` usage before changing
  its signature — new params must be optional).

### References in Codebase
- `sources.py:657` `_migrate_json_manifest` — migration precedent (existing rows win, legacy renamed).
- `tests/knowledge/wiki/test_sources.py` — existing suite to extend, must not regress.

---

## Acceptance Criteria

- [ ] A pre-FEAT-402 SQLite DB (created from the OLD 7-column DDL in a test) opens and migrates cleanly; new columns readable with defaults.
- [ ] Decision fields persist and round-trip through `SourceManifestEntry`.
- [ ] Rejected docs recorded with `status="rejected"` and no pages.
- [ ] `TRIAGE`/`ADMIT`/`ARCHIVE`/`DISCARD` lines appear via `log_operation` and are readable via `read_log`.
- [ ] Existing tests pass: `pytest tests/knowledge/wiki/test_sources.py tests/knowledge/wiki/test_bookkeeper.py -v`
- [ ] `ruff check` clean on modified modules.

---

## Test Specification

```python
# tests/knowledge/wiki/test_sources.py (add)
def test_sources_migration_old_db(tmp_path): ...      # old 7-col DDL → migrated, defaults OK
def test_sources_persist_decision(tmp_path): ...      # destination/decision_source/charter_version/composite stored
def test_sources_rejected_no_pages(tmp_path): ...
def test_bookkeeper_triage_tags(tmp_path): ...        # TRIAGE/ADMIT/ARCHIVE/DISCARD via log_operation
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2070 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm DDL/lines above still hold;
   check `mark_ingested` call sites before touching its signature
4. **Update status** in `sdd/tasks/index/supervised-wiki-ingestion.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and **update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
