---
type: Wiki Entity
title: SourceCollectionManager
id: class:parrot.knowledge.wiki.sources.SourceCollectionManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages the raw-source collection for a single wiki instance.
---

# SourceCollectionManager

Defined in [`parrot.knowledge.wiki.sources`](../summaries/mod:parrot.knowledge.wiki.sources.md).

```python
class SourceCollectionManager
```

Manages the raw-source collection for a single wiki instance.

Attributes:
    sources_dir: Directory where raw source files live.
    backend: ``"sqlite"`` (sources table in ``wiki.db``) or
        ``"json"`` (``.manifest.json`` in ``sources_dir``).
    db_path: Path of the shared ``wiki.db`` file (sqlite mode).
    manifest_path: ``.manifest.json`` location (json-mode storage;
        sqlite-mode legacy migration source).
    logger: Standard Python logger.

Example::

    mgr = SourceCollectionManager(Path("/wiki/sources"))
    entry = mgr.add_source(Path("/docs/article.md"))
    print(entry.source_id, entry.file_hash)

    if mgr.is_stale(entry.source_id):
        mgr.reingest(...)

## Methods

- `def add_source(self, path: Path) -> SourceManifestEntry` — Register a new source file in the sources table.
- `def list_sources(self) -> list[SourceManifestEntry]` — Return all tracked sources.
- `def get_source(self, source_id: str) -> Optional[SourceManifestEntry]` — Retrieve a single source entry by its ID.
- `def is_stale(self, source_id: str) -> bool` — Determine whether a tracked source has changed since last ingest.
- `def mark_ingested(self, source_id: str, pages_generated: list[str], status: str='ingested') -> Optional[SourceManifestEntry]` — Update the sources table after a successful ingest run.
- `def remove_source(self, source_id: str) -> bool` — Remove a source from the sources table.
- `def find_by_uri(self, source_uri: str) -> Optional[str]` — Look up an existing source ID by URI (public API).
