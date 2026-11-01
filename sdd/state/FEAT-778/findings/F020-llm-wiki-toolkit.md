---
id: F020
query_id: Q040
type: grep
intent: "Wiki toolkit available to agents (mandatory wikitoolkit access): class name and scope/tag filters."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 700
parent_id: null
depth: 0
merged_from: [FC-021-llm-wiki-toolkit]
---

# F020 — Agent-facing wiki access is `LLMWikiToolkit(AbstractToolkit)` in ai-parrot-tools (`wiki_*` tools, scoped by `wiki_name`, with `confine_sources`); core has only the MCP `WikiToolBundle`

## Summary

`parrot_tools/wiki/toolkit.py` (1379 lines): tools are `wiki_<method>` (`wiki_ingest_source`, `wiki_query`, …); every public method takes `wiki_name: str` and resolves a local or federated-scoped store (`_store_for`, `_search_for`); server params inject `pageindex_toolkit`, `graphindex_toolkit`, `okf_toolkit`; `confine_sources` restricts ingestion paths. Scoping is by wiki name/namespace, not by a tag set — the source's `scope: {tags: [...]}` would need a tag filter added to `query` or a per-expert wiki namespace.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py`
  lines: 48-80
  symbol: `LLMWikiToolkit`
  excerpt: |
    class LLMWikiToolkit(AbstractToolkit):
        wiki_<method_name> (e.g. wiki_ingest_source, wiki_query).
        "pageindex_toolkit": ServerParam(source="server"), "graphindex_toolkit": ..., "okf_toolkit": ...

- path: `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py`
  lines: 82-115
  symbol: `LLMWikiToolkit.__init__`
  excerpt: |
    confine_sources: bool = False,  # PA-14 host switch ... ingest_source accepts a URL or a file under <storage_dir>/sources only

- path: `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py`
  lines: 208-230
  symbol: `_is_namespace / _store_for / _search_for`
  excerpt: |
    def _store_for(self, wiki_name: str) -> BaseWikiStore: ... return federated.scoped(wiki_name)

- path: `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py`
  lines: 373-375
  symbol: `LLMWikiToolkit.query`
  excerpt: |
    async def query(self, wiki_name: str, ...

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py`
  lines: 87
  symbol: `WikiToolBundle`
  excerpt: |
    class WikiToolBundle:

## Notes

Bookstore has its own `BookstoreToolkit` (knowledge/bookstore/toolkit.py) — "wiki + bookstore mandatory" means two toolkits.
