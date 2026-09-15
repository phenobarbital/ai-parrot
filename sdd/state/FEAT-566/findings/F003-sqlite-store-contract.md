---
id: F003
query_id: Q004
type: read
executed_at: 2026-09-14T00:05:00Z
duration_ms: 100
parent_id: null
depth: 0
---

# F003 — SQLite store supplies reusable page-edge primitives but needs write-contention proof

## Summary

The SQLite plane opens with `aiosqlite`, initializes WAL schema, runs `_migrate()` on every normal connection, and commits independently after page or edge writes. Edges support caller-supplied provenance, while FTS, neighbors, and broken-edge checks provide the query and audit primitives proposed for the ledger. A focused source search found no `busy_timeout` or explicit `BEGIN IMMEDIATE` in this store.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 875-903
  symbol: `SQLiteWikiStore._connect`
  excerpt: |
    async with aiosqlite.connect(str(self._db_path)) as conn:
        ...
        await self._migrate(conn)
        yield conn
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1041-1063
  symbol: `SQLiteWikiStore._migrate`
  excerpt: |
    await conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'schema_version' AND value != ?",
        (SCHEMA_VERSION, SCHEMA_VERSION),
    )
    await conn.commit()
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1120-1128
  symbol: `SQLiteWikiStore._insert_edges_conn`
  excerpt: |
    rows = [(e[0], e[1], e[2], e[3] if len(e) > 3 else "extracted") for e in edges]
    INSERT OR REPLACE INTO edges (src, dst, rel, provenance)
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1134-1174
  symbol: `SQLiteWikiStore.upsert_pages`, `SQLiteWikiStore.add_edges`
  excerpt: |
    async with self._connect() as conn:
        await self._upsert_pages_conn(conn, pages)
        await conn.commit()
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1582-1628
  symbol: `SQLiteWikiStore.search_fts`
  excerpt: |
    "SELECT ... FROM pages_fts JOIN pages ... WHERE pages_fts MATCH ?"
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1672-1703
  symbol: `SQLiteWikiStore.neighbors`
  excerpt: |
    SELECT e.<other> AS concept_id, e.rel, e.provenance,
           p.title, p.category, p.summary, p.token_count
    FROM edges e LEFT JOIN pages p ON p.concept_id = e.<other>
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1773-1781
  symbol: `SQLiteWikiStore.broken_edges`
  excerpt: |
    SELECT e.src, e.dst, e.rel FROM edges e
    WHERE e.dst NOT IN (SELECT concept_id FROM pages)

## Notes

The no-match search for `busy_timeout` and explicit `BEGIN IMMEDIATE|EXCLUSIVE|DEFERRED` was limited to this file. It supports a scoped hardening investigation, not a claim about every SQLite use in the repository.
