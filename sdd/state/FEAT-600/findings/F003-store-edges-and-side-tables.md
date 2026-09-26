---
id: F003
query_id: Q003/Q022
type: read
intent: Edges carry (src,dst,rel,provenance) only — no attribute slot; `symbols` is the precedent for a side table
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F003 — Edges carry (src,dst,rel,provenance) only — no attribute slot; `symbols` is the precedent for a side table

## Summary

edges DDL: src, dst, rel (default 'references'), provenance (default 'extracted'), PRIMARY KEY (src,dst,rel), two indexes. add_edges takes (src,dst,rel[,provenance]) tuples. A FK column pair therefore cannot ride on the edge without either encoding it in `rel` or a schema bump. The `symbols` table (L131) plus upsert_symbols/find_symbols/page_hashes/replace_source_slice/compare_and_swap_page are the side-table + slice-replace + CAS primitives the plane would reuse.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 112-120
  symbol: `edges DDL`
  excerpt: |
    CREATE TABLE IF NOT EXISTS edges (src TEXT NOT NULL, dst TEXT NOT NULL, rel TEXT NOT NULL DEFAULT 'references', provenance TEXT NOT NULL DEFAULT 'extracted', PRIMARY KEY (src, dst, rel));
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 131
  symbol: `symbols DDL`
  excerpt: |
    CREATE TABLE IF NOT EXISTS symbols (
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 550,610,721,768,837
  symbol: `BaseWikiStore.replace_source_slice / compare_and_swap_page / upsert_symbols / find_symbols / page_hashes`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1593-1612
  symbol: `SQLiteWikiStore.add_edges`
  excerpt: |
    edges: (src, dst, rel) or (src, dst, rel, provenance) tuples; rel is an open string
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1527,1614
  symbol: `SQLiteWikiStore._insert_edges_conn / replace_source_slice`
