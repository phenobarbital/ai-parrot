---
id: F006
query_id: Q006
type: read
intent: Check builder.py pipeline wiring — extractor selection, mtime, SQLite support
executed_at: 2026-06-16T00:00:00Z
duration_ms: 1500
parent_id: null
depth: 0
---

# F006 — Builder uses hardcoded CodeExtractor, no mtime, no backend selection

## Summary

`GraphIndexBuilder.build()` runs a 6-stage pipeline (+ 2 optional). Stage 1
(`_extract_code`, lines 404-440) creates `CodeExtractor()` directly and calls
`await extractor.extract(str(f), source)` — no mtime, no extractor selection.
Persistence is injected via constructor (`self.persistence`) but only ArangoDB
is ever instantiated. To support SQLite + Odoo extraction, the builder needs:
(1) extractor selection/injection, (2) mtime passing, (3) backend selection.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py`
  lines: 404-440
  symbol: `GraphIndexBuilder._extract_code`
  excerpt: |
    async def _extract_code(self, sources):
        extractor = CodeExtractor()
        # ... iterates files, calls await extractor.extract(str(f), source)

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py`
  lines: 122-274
  symbol: `GraphIndexBuilder.build`
  excerpt: |
    # Stage 1: Extract (concurrent)
    # Stage 2: Embed
    # Stage 3: Assemble
    # Stage 4: Resolve
    # Stage 5: Persist (self.persistence)
    # Stage 6: Analytics + Report

## Notes

The persistence is already injected (not hardcoded), so swapping in SQLitePersistence
is clean. The extractor selection is the harder part — CodeExtractor is hardcoded.
Options: (a) make extractor configurable via constructor param, (b) detect Odoo
repos heuristically, (c) always use OdooCodeExtractor (it falls back to base for
non-Odoo classes).
