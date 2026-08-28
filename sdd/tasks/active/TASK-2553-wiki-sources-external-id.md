# TASK-2553: Add `external_id` to the wiki sources manifest

**Feature**: FEAT-472 — Fireflies Meeting Registry
**Spec**: `sdd/specs/fireflies-meeting-registry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 / §2 Data Models. The registry reuses `SourceCollectionManager`
(`parrot/knowledge/wiki/sources.py`), which is keyed by file path. This task adds
the one additive column that lets a row be found by an immutable external
identity (`fireflies:<transcript_id>`), plus the lookups and a URI-update verb
that later tasks need. It also fixes a latent bug: `mark_ingested` rebuilds the
entry from seven fields and silently drops the FEAT-402/451 columns — it would
drop `external_id` too (spec §7 Patterns).

---

## Scope

- Add `external_id: str | None = None` to `SourceManifestEntry` (models.py) with a
  docstring stating the `<source>:<id>` convention (spec §7).
- `store.py` `WIKI_SCHEMA_SQL`: add `external_id TEXT` to the `sources` DDL and
  `CREATE INDEX IF NOT EXISTS idx_sources_external_id ON sources(external_id);`.
- `sources.py`:
  - `_SOURCES_EXTERNAL_COLUMNS = {"external_id": "TEXT"}` consumed by
    `_migrate_sources_columns`; create the index in the migration as well
    (idempotent) so pre-existing DBs get it.
  - Grow `_SOURCES_UPSERT_SQL` to 15 columns; update `_entry_params`,
    `_row_to_entry` (via `_optional_column`), `_entry_to_doc`, `_doc_to_entry`,
    and the json-backend manifest serialisation.
  - `add_source(path, *, external_id=None)` and
    `record_decision(path, *, ..., external_id=None)` — when given, stored on the row.
  - New readers: `find_by_external_id(external_id) -> SourceManifestEntry | None`,
    `find_entries_by_external_ids(ids) -> dict[str, SourceManifestEntry]` (chunked
    by `_SQLITE_IN_CHUNK`), `list_by_external_prefix(prefix) -> list[...]`.
  - New writers: `set_external_id(source_id, external_id | None)`,
    `update_source_uri(source_id, new_uri)` — keeps `source_id`, re-hashes the file
    at the new path, raises `FileNotFoundError` if absent, enforces `source_uri`
    uniqueness.
  - Fix `mark_ingested` and `mark_ingested_many` to use `entry.model_copy(update=…)`
    so `external_id`, `doc_metadata`, `destination`, etc. survive.
  - Arango backend: implement the three readers as AQL filters on the
    `wiki_sources` collection (`_run_async` bridge), matching existing `_async_*` style.
- Document the convention in the `SourceCollectionManager` class docstring.
- Tests in `tests/knowledge/wiki/test_sources.py` (extend) and
  `tests/knowledge/wiki/test_sources_arango.py` (mapping only).

**NOT in scope**: `MeetingRegistry`, anything under `parrot/agents/`, fingerprints.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | MODIFY | `SourceManifestEntry.external_id` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | DDL column + index |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | MODIFY | migration map, upsert, readers/writers, `mark_ingested*` fix, arango mapping |
| `tests/knowledge/wiki/test_sources.py` | MODIFY | new tests below |
| `tests/knowledge/wiki/test_sources_arango.py` | MODIFY | `_entry_to_doc`/`_doc_to_entry` round-trip includes `external_id` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.sources import SourceCollectionManager        # sources.py:96
from parrot.knowledge.wiki.models import SourceManifestEntry             # models.py:155
from parrot.knowledge.wiki.store import WIKI_SCHEMA_SQL                  # imported at sources.py:189
from parrot.knowledge.wiki import SourceCollectionManager, SourceManifestEntry   # lazy map wiki/__init__.py:52-53
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class SourceManifestEntry(BaseModel):                                            # :155
    source_id: str; source_uri: str; file_hash: str; mtime: float; ingested_at: str   # :195-199
    pages_generated: list[str]; status: str                                      # :200-…
    destination: str | None; decision_source: str | None; charter_version: str | None; composite_score: float | None  # FEAT-402
    doc_metadata: dict[str, Any] | None; content_type: str | None; loader: str | None   # FEAT-451

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
WIKI_SCHEMA_SQL   # CREATE TABLE IF NOT EXISTS sources (source_id PK, source_uri UNIQUE, file_hash, mtime,
                  #   ingested_at, pages_generated, status, destination, decision_source, charter_version, composite_score)  :58-70

# packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
_ARANGO_SOURCES_COLLECTION = "wiki_sources"                                      # :43
_SOURCES_UPSERT_SQL   # 14 columns, ON CONFLICT(source_id) DO UPDATE               # :50-67
_SQLITE_IN_CHUNK = 500                                                           # :72
_SOURCES_DECISION_COLUMNS: dict[str, str]                                        # :83-88
_SOURCES_DOCUMENT_COLUMNS: dict[str, str]                                        # :91-95
class SourceCollectionManager:                                                   # :96
    def __init__(self, sources_dir: Path, db_path: Path | None = None,
                 backend: Literal["sqlite","json","arangodb"] = "sqlite",
                 arango_db=None, arango_store=None) -> None                       # :121 — sqlite path: executescript(WIKI_SCHEMA_SQL); self._migrate_sources_columns(); self._migrate_json_manifest()  :188-194
    def add_source(self, path: Path) -> SourceManifestEntry                      # :205 — FileNotFoundError; id = _find_id_by_uri or _generate_source_id
    def find_entries_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]   # :260 — chunked IN pattern to copy
    def find_entries_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]   # :301
    def add_sources(...)                                                         # :339
    def mark_ingested_many(...)                                                  # :400
    def list_sources(self) -> list[SourceManifestEntry]                          # :442
    def get_source(self, source_id: str) -> SourceManifestEntry | None           # :457
    def mark_ingested(self, source_id, pages_generated, status="ingested") -> SourceManifestEntry | None   # :533 — rebuilds entry with 7 fields at :544-556 (BUG to fix)
    def record_decision(self, path: Path, *, destination: str, decision_source=None, charter_version=None,
                        composite_score=None, pages_generated=None, status=None) -> SourceManifestEntry   # :570
    def record_document_metadata(self, source_id, *, doc_metadata, content_type, loader) -> None   # :663
    def remove_source(self, source_id: str) -> bool                              # :708
    def find_by_uri(self, source_uri: str) -> str | None                         # :737
    def _connect(self) -> sqlite3.Connection                                     # :752
    def _upsert(self, entry) -> None / _upsert_many(self, entries) -> None       # :764 / :776
    @staticmethod def _entry_params(entry) -> tuple                              # :800 — bind order == upsert column order
    @staticmethod def _optional_column(row, name)                                # :820
    @staticmethod def _row_to_entry(row) -> SourceManifestEntry                  # :841
    def _compute_hash(self, path: Path) -> str                                   # :870
    def _generate_source_id(self, source_uri: str) -> str                        # :887
    def _find_id_by_uri(self, source_uri: str) -> str | None                     # :902 — sqlite / json / arango branches
    def _run_async(self, coro)                                                   # :922
    async def _arango_query(self, aql, bind_vars) -> list                        # :1001
    async def _arango_execute(self, aql, bind_vars) -> list                      # :1017
    @staticmethod def _doc_to_entry(doc) -> SourceManifestEntry                  # :1026
    @staticmethod def _entry_to_doc(entry) -> dict                                # :1042
    async def _async_find_id_by_uri(self, source_uri) -> str | None              # :1108 — pattern for the AQL readers
    def _migrate_sources_columns(self) -> None                                   # :1116 — iterates (_SOURCES_DECISION_COLUMNS, _SOURCES_DOCUMENT_COLUMNS); add the new map to that tuple
    def _load_manifest(self) -> None                                             # :1170 (json backend)
```

### Does NOT Exist
- ~~`SourceManifestEntry.external_id`~~, ~~`find_by_external_id`~~, ~~`find_entries_by_external_ids`~~, ~~`list_by_external_prefix`~~, ~~`set_external_id`~~, ~~`update_source_uri`~~ — this task creates them.
- ~~`_SOURCES_EXTERNAL_COLUMNS`~~ — this task creates it.
- ~~a `sources` index on any column today~~ — only the PK and the `source_uri` UNIQUE constraint exist.
- ~~`SourceManifestEntry.model_copy` being used anywhere in sources.py~~ — `mark_ingested` constructs a fresh entry; that is the bug.

---

## Implementation Notes

### Pattern to Follow
Follow FEAT-451 exactly (search `doc_metadata` in `sources.py`): a column map → migration, one extra `?` in `_SOURCES_UPSERT_SQL`, `_entry_params` order, `_optional_column` in `_row_to_entry`, and the `_entry_to_doc`/`_doc_to_entry` pair. `find_entries_by_external_ids` copies `find_entries_by_uris`'s chunked `IN (...)` loop.

### Key Constraints
- Additive only; existing rows/columns untouched; opening a pre-FEAT-472 DB twice must be a no-op the second time.
- `update_source_uri` must raise `ValueError` if `new_uri` is already tracked by a different `source_id` (UNIQUE constraint would otherwise surface as `sqlite3.IntegrityError`).
- Public API stays synchronous (module docstring); no `async def` on the manager's sqlite/json paths.
- Google-style docstrings; type hints; `self.logger`.

### References in Codebase
- `tests/knowledge/wiki/test_sources.py` — existing fixtures for a tmp sqlite manifest; extend, don't fork.
- `tests/knowledge/wiki/test_sources_arango.py` — doc-mapping tests.

---

## Acceptance Criteria

- [ ] `pytest tests/knowledge/wiki/ -v` passes (whole wiki suite, not just the new tests).
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/`
- [ ] A `wiki.db` created from the *old* DDL (test builds it from a literal without the column) opens, gains `external_id` + index, and opens again without error.
- [ ] `add_source(path, external_id="fireflies:abc")` → `find_by_external_id("fireflies:abc").source_id == entry.source_id` on sqlite **and** json backends.
- [ ] After `mark_ingested(...)` and `mark_ingested_many(...)`, `external_id`, `doc_metadata`, `destination` are unchanged.
- [ ] `update_source_uri` keeps `source_id`, updates `file_hash`/`mtime`; missing file → `FileNotFoundError`; URI owned by another row → `ValueError`.
- [ ] `list_by_external_prefix("fireflies:")` excludes rows with `None` or other prefixes.
- [ ] `_entry_to_doc(entry)["external_id"]` round-trips through `_doc_to_entry`.
- [ ] Class docstring documents the `<source>:<id>` convention.

---

## Test Specification

```python
# tests/knowledge/wiki/test_sources.py (additions)
def test_migration_adds_external_id_column(tmp_path): ...
def test_add_source_with_external_id_roundtrip(tmp_manager, tmp_file): ...
@pytest.mark.parametrize("backend", ["sqlite", "json"])
def test_find_by_external_id_backends(tmp_path, backend): ...
def test_external_id_survives_mark_ingested(tmp_manager, tmp_file): ...
def test_external_id_survives_mark_ingested_many(tmp_manager, tmp_files): ...
def test_update_source_uri_keeps_source_id(tmp_manager, tmp_path): ...
def test_update_source_uri_missing_file_raises(tmp_manager): ...
def test_update_source_uri_conflict_raises(tmp_manager, tmp_files): ...
def test_list_by_external_prefix(tmp_manager, tmp_files): ...
def test_find_entries_by_external_ids_chunked(tmp_manager, tmp_files): ...   # > _SQLITE_IN_CHUNK ids

# tests/knowledge/wiki/test_sources_arango.py (addition)
def test_arango_doc_mapping_external_id(): ...
```

---

## Agent Instructions

1. Read the spec; 2. no dependencies; 3. verify the contract lines above (`sources.py` is ~1200 lines — re-grep the anchors); 4. mark in-progress in `sdd/tasks/index/fireflies-meeting-registry.json`; 5. implement; 6. run the full `tests/knowledge/wiki/` suite; 7. move this file to `sdd/tasks/completed/`; 8. mark done; 9. fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
