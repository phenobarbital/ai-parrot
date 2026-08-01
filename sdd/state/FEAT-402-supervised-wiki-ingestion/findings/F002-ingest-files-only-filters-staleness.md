# F002 — `_ingest_files` admits everything; the only gate is staleness

- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:264-326` —
  `_ingest_files()`: for each scanned file, skip only when
  `sources.is_stale(source_id)` is false (unchanged hash/mtime). Otherwise the
  file is upserted unconditionally via `store.replace_source_slice`.
- There is no relevance, category, or quality gate. For a code repo this is
  correct; for a documents folder (meetings, summaries) it ingests noise.

Method: direct read.
