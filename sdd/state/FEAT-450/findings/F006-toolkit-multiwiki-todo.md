---
id: F006
query_id: Q011
type: read
intent: Confirm LLMWikiToolkit carries an explicit multi-wiki dispatch placeholder
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F006 — LLMWikiToolkit already threads wiki_name through its API and reserves a dispatch point

## Summary
`LLMWikiToolkit._config_for(wiki_name)` (toolkit.py:1205-1228) raises `ValueError` on any
name other than the configured one, with the docstring "Multi-wiki support would dispatch to
different configs here". `list_wikis` (499-516) returns the single configured wiki and says
"Multi-wiki support can be added in a future iteration". `search`/`search_compact` (991-1047)
take `wiki_name` and pass it as `tree_name`. The toolkit builds its own store via
`create_wiki_store` (toolkit.py:~110-120) — a federated store can be injected the same way.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py`
  lines: 1205-1228
  symbol: `LLMWikiToolkit._config_for`
  excerpt: |
    Multi-wiki support would dispatch to different configs here; for now
    a mismatch is an explicit programming error rather than a silent
    data-routing bug.
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py`
  lines: 499-516
  symbol: `LLMWikiToolkit.list_wikis`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py`
  lines: 991-1047
  symbol: `LLMWikiToolkit.search`, `search_compact`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py`
  lines: 75-165
  symbol: `LLMWikiToolkit.__init__`
  excerpt: |
    self._store = create_wiki_store(config.storage_dir, wiki_name=config.wiki_name, backend=config.storage_backend)
    self._search = WikiCombinedSearch(pageindex_toolkit, graphindex_toolkit, config.search_weights, store=self._store)
