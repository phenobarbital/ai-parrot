---
id: F003
slug: source-collection-manager
query: "SourceCollectionManager persistence and backend switching"
type: read
---

# F003: SourceCollectionManager

## Interface (sources.py)

- `__init__(sources_dir, db_path=None, backend="sqlite")`
- `add_source(path) -> SourceManifestEntry`
- `list_sources() -> list[SourceManifestEntry]`
- `get_source(source_id) -> Optional[SourceManifestEntry]`
- `is_stale(source_id) -> bool`
- `mark_ingested(source_id, pages_generated, status) -> Optional[SourceManifestEntry]`
- `remove_source(source_id) -> bool`
- `find_by_uri(source_uri) -> Optional[str]`

## Backend Switching

- Accepts `Literal["sqlite", "json"]` — NOT the same as WikiProjectConfig's `Literal["sqlite", "memory"]`
- Translation happens at call site: `WikiProjectConfig.backend == "memory"` → `SourceCollectionManager(backend="json")`
- sqlite: per-call `sqlite3.Connection` via `_connect()`, uses WAL for concurrent access
- json: in-memory `dict[str, SourceManifestEntry]` + atomic `.manifest.json` writes

## Critical Detail

- When backend="sqlite", `__init__` runs `WIKI_SCHEMA_SQL` creating ALL tables (meta, sources, pages, edges, pages_fts, embeddings) — not just sources
- `db_path` defaults to `sources_dir/../wiki.db` when not explicitly provided
- No FOREIGN KEY between sources and pages — linkage is logical via `pages.source_id`

## Toolkit Wiring (toolkit.py:110-118)

```python
if config.storage_backend == "sqlite":
    self._sources = SourceCollectionManager(sources_dir, db_path=config.storage_dir / "wiki.db")
else:
    self._sources = SourceCollectionManager(sources_dir, backend="json")
```

## Impact for ArangoDB

- Option A: Add "arangodb" backend to SourceCollectionManager (full parity)
- Option B: Keep JSON sidecar for source tracking (simpler — sources are small metadata)
- Option C: Store sources in an ArangoDB collection (reuse async client)
