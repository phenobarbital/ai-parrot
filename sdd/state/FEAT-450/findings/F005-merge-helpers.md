---
id: F005
query_id: Q009,Q010
type: read
intent: Confirm min-max + weight + dedup merge helpers reusable for cross-namespace merge
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F005 — Cross-group merge already exists: _merge_groups / _apply_weight / _store_row_to_wiki

## Summary
`WikiCombinedSearch._merge_groups(groups: list[(results, weight)])` (search.py:473-495)
min-max-normalises each group via `_apply_weight` (497-530), multiplies by weight, dedups by
`node_id` keeping the higher score, sorts desc. `_store_row_to_wiki` (249-268) converts a
`search_fts` row into `WikiSearchResult` (node_id = concept_id). The CLI path uses its own
`_normalize_scores` (cli.py:164). Both are per-group min-max — exactly what a broadcast
across namespaces with different corpus sizes needs (F002/F003: raw scores are -bm25,
corpus-relative).

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/search.py`
  lines: 473-495
  symbol: `WikiCombinedSearch._merge_groups`
  excerpt: |
    seen: dict[str, WikiSearchResult] = {}
    for results, weight in groups:
        for result in self._apply_weight(results, weight):
            existing = seen.get(result.node_id)
            if existing is None or result.score > existing.score:
                seen[result.node_id] = result
    return sorted(seen.values(), key=lambda r: r.score, reverse=True)
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/search.py`
  lines: 497-530
  symbol: `WikiCombinedSearch._apply_weight`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/search.py`
  lines: 229-268
  symbol: `_normalize_rows`, `_store_row_to_wiki`
  excerpt: |
    node_id=str(row.get("concept_id") or row.get("node_id") or ""),   # 260
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/models.py`
  symbol: `WikiSearchResult`
  excerpt: |
    node_id, title, score (0..1), source ('lexical'/'vector'/...), token_count, snippet
