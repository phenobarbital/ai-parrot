# F006 — `SourceCollectionManager`: SQLite manifest with migration precedent

- `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:40-110` —
  SQLite-backed source registry. Key methods: `add_source` (:111),
  `is_stale` (:186), `mark_ingested` (:229), `find_by_uri` (:294).
- `sources.py:411` — `_migrate_json_manifest()`: precedent for schema/storage
  migration (legacy JSON → SQLite).
- Implication: recording the admission decision (destination
  wiki/archive/discard, decision_source, charter_version) fits here as new
  columns; the migration pattern exists to follow.

Method: grep of class/def index + targeted reads.
