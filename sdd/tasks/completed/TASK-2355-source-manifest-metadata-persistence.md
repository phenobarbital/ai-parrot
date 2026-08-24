# TASK-2355: Persist document metadata on `SourceManifestEntry` (sqlite + Arango)

**Feature**: FEAT-451 — `wikitoolkit ingest` — Binary Documents, URLs, and Metadata Frontmatter
**Spec**: `sdd/specs/wikitoolkit-ingest-documents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2351
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec (§3) — the machine/audit half of "metadata
persisted twice". `SourceManifestEntry` today records provenance about *the
ingest run* (hash, mtime, triage decision, charter version) but nothing about
*the document* itself. This task adds `doc_metadata`, `content_type`, and
`loader`, with an additive migration so pre-FEAT-451 databases keep opening.

This task touches `models.py` and `sources.py` only — **no overlap with
`documents.py`**, so it can be implemented independently of TASK-2352/2353/2354.

---

## Scope

- MODIFY `packages/ai-parrot/src/parrot/knowledge/wiki/models.py`:
  add three optional fields to `SourceManifestEntry` (line 159), documented in
  the class docstring's `Attributes:` block like the FEAT-402 fields above them:
  - `doc_metadata: Optional[dict[str, Any]] = None`
  - `content_type: Optional[str] = None`
  - `loader: Optional[str] = None`
- MODIFY `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py`:
  - Add a `_SOURCES_DOCUMENT_COLUMNS` dict mirroring
    `_SOURCES_DECISION_COLUMNS` (line 49-54):
    `{"doc_metadata": "TEXT", "content_type": "TEXT", "loader": "TEXT"}`.
  - Apply it in `_migrate_sources_columns` (line 804-821) using the **same
    `PRAGMA table_info` guarded, additive loop** — iterate both dicts.
  - `_upsert` (line 486): serialize `doc_metadata` with `json.dumps` when not
    `None`; write `None` as SQL `NULL`.
  - `_row_to_entry` (line 547): read the three columns via the existing
    `_optional_column` helper (line 526); `json.loads` `doc_metadata` inside a
    `try/except (TypeError, ValueError, json.JSONDecodeError)` falling back to
    `None` — a corrupt cell must not make the whole manifest unreadable.
  - `_doc_to_entry` (line 735, the Arango path): mirror the same three fields.
    Arango stores documents natively, so `doc_metadata` needs no JSON
    round-trip there — but the field must be present and round-trip equal.
  - Add `record_document_metadata(self, source_id: str, *, doc_metadata: dict | None,
    content_type: str | None, loader: str | None) -> None` following the shape
    of `record_decision` (line 332).
- Extend `tests/knowledge/wiki/test_sources.py` and
  `tests/knowledge/wiki/test_models.py`.

**NOT in scope**: `documents.py` (other tasks); calling
`record_document_metadata` from the orchestrator (TASK-2356); page frontmatter
(TASK-2352/2356); any query/filter surface over `doc_metadata` (explicit spec
Non-Goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | MODIFY | 3 new optional fields on `SourceManifestEntry` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | MODIFY | Columns, migration, upsert/read, Arango mirror, writer method |
| `tests/knowledge/wiki/test_sources.py` | MODIFY | Migration + round-trip tests |
| `tests/knowledge/wiki/test_models.py` | MODIFY | Model default tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `2026-08-23`. `sources.py` is shared with FEAT-450
> (wiki-namespaces) — **re-anchor line numbers before editing.**

### Verified Imports

```python
import json
import sqlite3
from typing import Any, Optional

from pydantic import BaseModel, Field
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:49-54
# THE PATTERN TO MIRROR — a module-level dict of {column_name: sql_type}
_SOURCES_DECISION_COLUMNS: dict[str, str] = {
    "destination": "TEXT",
    "decision_source": "TEXT",
    "charter_version": "TEXT",
    "composite_score": "REAL",
}

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:804-821
# THE ADDITIVE MIGRATION — idempotent, guarded on PRAGMA table_info,
# never rewrites or drops. Extend this loop; do not write a new mechanism.
def _migrate_sources_columns(self) -> None:
    with self._connect() as conn:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(sources)").fetchall()
        }
        for name, col_type in _SOURCES_DECISION_COLUMNS.items():
            if name in existing:
                continue
            conn.execute(f"ALTER TABLE sources ADD COLUMN {name} {col_type}")
            self.logger.debug(
                "Migrated sources table: added column %s (%s)", name, col_type
            )

class SourceCollectionManager:                                        # line 57
    def add_source(self, path: Path) -> SourceManifestEntry:          # 171-211
    def mark_ingested(self, ...)                                      # 293
    def record_decision(self, ...)                                    # 332   <-- shape to copy
    def _upsert(self, entry: SourceManifestEntry) -> None:            # 486
    @staticmethod
    def _optional_column(row: sqlite3.Row, name: str) -> Any:         # 526   <-- use for new reads
    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> SourceManifestEntry:       # 547
    @staticmethod
    def _doc_to_entry(doc: dict[str, Any]) -> SourceManifestEntry:    # 735   (Arango)
    async def _async_upsert(self, entry: SourceManifestEntry) -> None: # 747  (Arango)
```

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py:159-224
class SourceManifestEntry(BaseModel):
    source_id: str = Field(..., description="Stable source identifier")
    source_uri: str = Field(..., description="Absolute path or URI")
    file_hash: str = Field(..., description="SHA-1 hex digest at ingest time")
    mtime: float = Field(..., description="File mtime at ingest time")
    ingested_at: str = Field(..., description="ISO-8601 UTC ingest timestamp")
    pages_generated: list[str] = Field(default_factory=list, ...)
    status: str = Field(default="ingested", ...)
    destination: Optional[str] = Field(default=None, ...)        # FEAT-402
    decision_source: Optional[str] = Field(default=None, ...)    # FEAT-402
    charter_version: Optional[str] = Field(default=None, ...)    # FEAT-402
    composite_score: Optional[float] = Field(default=None, ge=0.0, le=1.0, ...)
```

### Does NOT Exist

- ~~`SourceManifestEntry.doc_metadata` / `.content_type` / `.loader`~~ — **you
  are adding them.** Verified absent: the model ends at `composite_score`
  (models.py:218-224).
- ~~`SourceManifestEntry.metadata`~~ — do not name the field `metadata`;
  Pydantic `BaseModel` reserves nothing there but the codebase already uses
  `doc_metadata` as the term of art (`AbstractLoader.create_metadata` takes a
  `doc_metadata` kwarg, abstract.py:864). Stay consistent.
- ~~a JSON column type in sqlite~~ — sqlite has no JSON column type here. Use
  `TEXT` and `json.dumps`/`json.loads` at the boundary, like every other
  serialized value in this file.
- ~~an Alembic / migration-framework step~~ — this codebase migrates the
  sources table with in-place `ALTER TABLE` guarded by `PRAGMA table_info`
  (sources.py:804-821). Do not introduce a migration framework.
- ~~`SourceCollectionManager.add_source(<url>)`~~ — takes a `Path` and calls
  `path.stat()` (sources.py:190, 200). Not part of this task, but do not
  "fix" it here.

---

## Implementation Notes

### Pattern to Follow

```python
# sources.py — mirror the existing constant, then iterate BOTH dicts.
_SOURCES_DOCUMENT_COLUMNS: dict[str, str] = {
    "doc_metadata": "TEXT",     # JSON-encoded DocumentMetadata.model_dump()
    "content_type": "TEXT",
    "loader": "TEXT",
}

def _migrate_sources_columns(self) -> None:
    with self._connect() as conn:
        existing = {row["name"] for row in
                    conn.execute("PRAGMA table_info(sources)").fetchall()}
        for column_map in (_SOURCES_DECISION_COLUMNS, _SOURCES_DOCUMENT_COLUMNS):
            for name, col_type in column_map.items():
                if name in existing:
                    continue
                conn.execute(f"ALTER TABLE sources ADD COLUMN {name} {col_type}")
                self.logger.debug(
                    "Migrated sources table: added column %s (%s)", name, col_type
                )
```

### Key Constraints

- **Additive only.** Never `DROP`, never rewrite existing rows, never
  reorder columns. A pre-FEAT-451 database must open cleanly and keep its data.
- All three fields default to `None`, so every existing row and every
  non-`ingest` code path (`build`, `upsert`) is unaffected.
- Corrupt `doc_metadata` JSON degrades to `None`, never raises — one bad cell
  must not make `list_sources()` unusable.
- Keep sqlite and Arango behavior identical from the caller's point of view:
  the same `SourceManifestEntry` in, the same one out.
- `sources.py` is shared with FEAT-450 (wiki-namespaces). Rebase on `dev`
  immediately before starting **and** before committing.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:49-54, 332, 486, 526, 547, 735, 804-821`
- `packages/ai-parrot/src/parrot/knowledge/wiki/models.py:159-224`
- `tests/knowledge/wiki/test_sources.py`, `tests/knowledge/wiki/test_sources_arango.py` — existing test shape.

---

## Acceptance Criteria

- [ ] `SourceManifestEntry(doc_metadata={"author": "X"}, content_type="application/pdf", loader="MarkdownLoader", ...)` constructs.
- [ ] All three fields default to `None`; constructing without them still works.
- [ ] A sqlite file created **before** this change opens without error, gains
      the three columns, and its existing rows come back unchanged with
      `doc_metadata is None`.
- [ ] `_migrate_sources_columns` is idempotent — running it twice is a no-op.
- [ ] `doc_metadata` round-trips as an **equal dict** through
      `_upsert` → `_row_to_entry`.
- [ ] A corrupt `doc_metadata` cell yields `None`, not an exception.
- [ ] The same round-trip holds on the Arango backend (`_doc_to_entry`).
- [ ] `record_document_metadata()` persists all three fields for an existing
      `source_id` and is a no-op (logged) for an unknown one — matching how
      `record_decision` behaves.
- [ ] `wikitoolkit build` output is unchanged (no new column is written by it).
- [ ] Tests pass: `pytest tests/knowledge/wiki/test_sources.py tests/knowledge/wiki/test_models.py -v`
- [ ] `ruff check` and `mypy` clean on both changed files.

---

## Test Specification

```python
# tests/knowledge/wiki/test_sources.py  (append)
import json
import sqlite3

from parrot.knowledge.wiki.models import SourceManifestEntry


class TestDocumentMetadataColumns:
    def test_migration_is_additive(self, legacy_sources_db):
        """A pre-FEAT-451 db opens, gains columns, keeps its rows."""
        mgr = SourceCollectionManager(...)
        rows = mgr.list_sources()
        assert rows and all(r.doc_metadata is None for r in rows)

    def test_migration_idempotent(self, tmp_path):
        mgr = SourceCollectionManager(...)
        mgr._migrate_sources_columns()
        mgr._migrate_sources_columns()   # must not raise

    def test_doc_metadata_roundtrip(self, tmp_path):
        mgr = SourceCollectionManager(...)
        entry = SourceManifestEntry(
            source_id="s1", source_uri="/tmp/a.pdf", file_hash="h",
            mtime=1.0, ingested_at="2026-08-23T00:00:00Z",
            doc_metadata={"author": "Legal", "page_count": 42},
            content_type="application/pdf", loader="MarkdownLoader",
        )
        mgr._upsert(entry)
        got = mgr.get_source("s1")
        assert got.doc_metadata == {"author": "Legal", "page_count": 42}
        assert got.content_type == "application/pdf"
        assert got.loader == "MarkdownLoader"

    def test_corrupt_doc_metadata_degrades_to_none(self, tmp_path):
        """A bad JSON cell must not break list_sources()."""
        ...

    def test_record_document_metadata(self, tmp_path):
        ...


# tests/knowledge/wiki/test_models.py  (append)
def test_source_entry_new_fields_default_none():
    e = SourceManifestEntry(
        source_id="s", source_uri="/a", file_hash="h", mtime=0.0,
        ingested_at="2026-08-23T00:00:00Z",
    )
    assert e.doc_metadata is None
    assert e.content_type is None
    assert e.loader is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§3 Module 5, §7).
2. **Check dependencies** — TASK-2351 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — `sources.py` is shared with FEAT-450.
   Re-`grep` every line number above before editing. If they shifted, update
   this contract first, then implement.
4. **Update status** in `sdd/tasks/index/wikitoolkit-ingest-documents.json` → `"in-progress"`.
5. **Implement** following the scope and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/TASK-2355-source-manifest-metadata-persistence.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude session 2026-08-23)
**Date**: 2026-08-23
**Notes**: Added `doc_metadata`/`content_type`/`loader` to
`SourceManifestEntry` (models.py) and a mirroring
`_SOURCES_DOCUMENT_COLUMNS` dict + additive migration loop, `_upsert`,
`_row_to_entry` (JSON-decoded with a `try/except` degrading corrupt cells
to `None`), `_doc_to_entry`/`_async_upsert` (Arango — native dict, no JSON
round-trip needed), and `record_document_metadata()` (sources.py). Merged
`origin/dev` first per the task's shared-file warning (only unrelated SDD
doc commits landed since branch-off; no code conflict). All three new
fields default to `None` so pre-FEAT-451 rows and non-`ingest` code paths
are unaffected. `record_document_metadata` follows `mark_ingested`'s
no-op-plus-warning shape for an unknown `source_id` (matching the
acceptance criteria's literal wording), not `record_decision`'s
create-if-missing shape, since a document's metadata is only meaningful
once the source is already tracked. 71 tests pass in
`test_sources.py`/`test_models.py` (18 new, incl. an Arango round-trip
test added to `test_sources.py` itself — `test_sources_arango.py` was not
in this task's Files to Create/Modify list, so it stayed untouched); the
pre-existing `test_build_unaffected` regression guard in
`test_integration.py` still passes. `ruff check`/`mypy` clean on
`sources.py`/`models.py`/`test_sources.py`; `test_models.py` has 4
pre-existing `pytest.raises(Exception)` B017 findings verified present on
`origin/dev` before this task (not introduced here, left untouched per
no-scope-creep).

**Deviations from spec**: none — `store.py`'s `WIKI_SCHEMA_SQL` CREATE
TABLE DDL was deliberately left untouched (not in this task's Files to
Create/Modify list); the always-run additive migration in
`_migrate_sources_columns` adds the new columns to brand-new databases
too, so this has no functional effect, only a documentation-comment
symmetry gap with the FEAT-402 precedent.
