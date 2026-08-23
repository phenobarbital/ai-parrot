---
id: F002
query_id: Q005,Q027
type: read
intent: Confirm --store/WIKI_STORE single-store read path and its precedence rules
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F002 — Read commands already open an arbitrary store, but exactly one and unnamed

## Summary
`_resolve_read_store(path_, store_opt, backend_opt)` (cli.py:199-251) resolves precedence
`--store > --path project > WIKI_STORE env > auto-detected project` and returns ONE
`BaseWikiStore`. `_store_options` (255) attaches `--store/--backend` to query/page/related.
An almost identical copy lives in the authoring path (`_resolve_write_store`, 1488-1493).
Project resolution helpers: `_resolve_project` (87), `_require_built` (108), `_open_store` (118),
`_open_sources` (138), `_normalize_scores` (164, min-max for CLI rows). Docs describe the same
single-store semantics (parrot-wiki-cli.md:424-451).

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 199-251
  symbol: `_resolve_read_store`
  excerpt: |
    --store  >  --path project  >  WIKI_STORE env  >  auto-detected project
    ...
    store_override = _env_setting("WIKI_STORE")          # 238
    return create_wiki_store(storage_dir, backend=backend)  # 249
    return _require_built(root, config)                  # 251
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 255-272
  symbol: `_store_options`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 87-160
  symbol: `_resolve_project`, `_require_built`, `_open_store`, `_open_sources`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 164-180
  symbol: `_normalize_scores`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 1488-1493
  symbol: `_resolve_write_store`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 1075-1160
  symbol: `query`
  excerpt: |
    store = _resolve_read_store(path_, store_opt, backend_opt)
    rows = _run(store.search_fts(question, category=category, limit=top_k))
    rows = _normalize_scores(rows)
- path: `documentation/parrot-wiki-cli.md`
  lines: 424-451
