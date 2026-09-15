---
id: F001
query_id: Q001
type: wiki_query
executed_at: 2026-09-14T00:04:56Z
duration_ms: 6600
parent_id: null
depth: 0
---

# F001 — Wiki orientation identifies the relevant planes and lifecycle artifacts

## Summary

The healthy local wiki indexes 35,087 pages and reports 226 stale sources, so it was used to locate candidate modules but not as sole line-level proof. It identified the SQLite wiki store, the existing worktree plane resolver, the SDD workflow, and task artifacts as the primary research targets.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1-1
  symbol: `SQLiteWikiStore`
  excerpt: |
    Wiki result: "WikiStore — single-file SQLite retrieval plane for the LLM Wiki."
- path: `packages/ai-parrot/src/parrot/tools/repo/graph_search.py`
  lines: 31-119
  symbol: `resolve_plane_root`, `open_plane`
  excerpt: |
    Wiki result: "Worktree-aware resolution and opening of the wiki retrieval plane."
- path: `sdd/WORKFLOW.md`
  lines: 1-1
  symbol: null
  excerpt: |
    Wiki result: "AI-Parrot SDD Workflow."

## Notes

The raw-source findings below verify the material contracts because the wiki is not fully fresh.
