---
id: F007
query_id: Q007
type: read
intent: Analyze Karpathy LLM Wiki reference design
executed_at: 2026-06-26T00:00:00Z
duration_ms: 800
parent_id: null
depth: 0
---

# F007 — Karpathy LLM Wiki: Reference Architecture

## Summary

The Karpathy LLM Wiki pattern defines a 3-layer architecture for persistent knowledge bases: (1) Raw Sources (immutable, curated), (2) Wiki (LLM-generated markdown, maintained by LLM), (3) Schema (configuration doc defining structure, conventions, workflows). Three core operations: Ingest (source → multi-page wiki update), Query (search → synthesize → optionally file answer back), Lint (health-check for contradictions, orphans, stale claims). Two special files: index.md (content catalog) and log.md (chronological record). Optional tooling: search engine (BM25 + vector), file management.

## Citations

- url: `https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f`
  excerpt: |
    Three layers: Raw sources, The wiki, The schema
    Operations: Ingest, Query, Lint
    Special files: index.md (content catalog), log.md (chronological)
    Key insight: good answers can be filed back into the wiki as new pages

## Notes

The Karpathy design is intentionally abstract — it describes the pattern, not a specific implementation. AI-Parrot's existing PageIndex + GraphIndex provide the indexing infrastructure. The missing layer is the wiki orchestrator that ties sources → ingestion → multi-page updates → index maintenance → search → answer filing → lint. The "schema" layer maps naturally to ai-parrot's skills system — a wiki schema could be a skill document that the agent loads.
