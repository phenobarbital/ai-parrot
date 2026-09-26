---
id: F020
query_id: Q018
type: wiki_query
intent: DevLoopWikiSearch.build_research_context already folds ledger context; table: hits would be one more source
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F020 — DevLoopWikiSearch.build_research_context already folds ledger context; table: hits would be one more source

## Summary

flows/dev_loop/wiki_search.py DevLoopWikiSearch.build_research_context 'Search the wiki and return token-budgeted context text' (score 1.00); tests/knowledge/wiki/test_devloop_ledger_context.py (TASK-3238 'DevLoop shared wiki and ledger research context') shows the pattern of adding an optional plane that degrades gracefully when unavailable.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py`
  lines: -
  symbol: `DevLoopWikiSearch.build_research_context`
  excerpt: |
    Search the wiki and return token-budgeted context text.
- path: `tests/knowledge/wiki/test_devloop_ledger_context.py`
  lines: -
  symbol: `TestDevLoopWikiLedgerContext.test_unavailable_ledger_leaves_research_usable`
