---
id: F015
query_id: Q015
type: wiki_query
intent: wiki_remember already supports one asserted link (link_page_id, rel) — annotations need no new tool
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F015 — wiki_remember already supports one asserted link (link_page_id, rel) — annotations need no new tool

## Summary

tools.py WikiRememberTool (wiki score 1.00) — 'Save durable knowledge to the knowledge graph'; inputs fact, category='note', title, link_page_id, rel (per brainstorm and sdd/state/FEAT-566/findings/F005 'Existing wiki tools support one asserted link'). Memory pages are origin='memory' and are not part of any ingest slice, so replace_source_slice on the schema slice leaves them intact.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: -
  symbol: `WikiRememberTool`
  excerpt: |
    Save durable knowledge to the knowledge graph — decisions, gotchas, …
- path: `sdd/state/FEAT-566/findings/F005-wiki-tools-and-hooks.md`
  lines: -
  excerpt: |
    Existing wiki tools support one asserted link and post-commit structural refresh
