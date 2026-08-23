---
id: F014
query_id: Q019
type: read
intent: Determine what FEAT-450 wiki-namespaces covers and whether it resolves the OQ1 namespace gap
executed_at: 2026-08-23T00:41:06Z
depth: 2
parent_id: F002
---

# F014 — FEAT-450 is a live parallel proposal that explicitly names the lawyer multi-brain use case, but it federates the WIKI plane, not GraphIndex

## Summary

FEAT-450 "wiki-namespaces" is an in-flight `/sdd-proposal` run (16 findings already on disk)
whose stated goal is federating N wiki stores behind an `ns::id` scheme with explicit and
broadcast routing. Its Problem statement calls out **this exact feature by name**: "the same
mechanism should let a user compose multiple 'brains' (e.g. a lawyer with graphs for
legislation, jurisprudence, own cases) and query all of them or a specific one". Its fixed
constraints already include an `arangodb` namespace kind keyed by `database`, and its own
F015 confirms `ArangoDBWikiStore` already isolates one database per wiki
(`self._database = database or f"wiki_{wiki_name or 'codebase'}"`). Critically, FEAT-450
operates on `parrot/knowledge/wiki/` (a page plane), **not** on `parrot/knowledge/graphindex/`
— so it solves "which brain do I query" but not "typed legal entities with temporal validity".

## Citations

- path: `sdd/state/FEAT-450/source.md`
  lines: 1-40
  excerpt: |
    # wiki-namespaces — Namespaces (multi-wiki federation) for wikitoolkit / LLM Wiki
    Beyond code, the same mechanism should let a user compose multiple "brains" (e.g. a lawyer
    with graphs for legislation, jurisprudence, own cases — built via `wikitoolkit ingest`) and
    query all of them or a specific one.
    1. **Namespaced page id scheme: `ns::id`**
    3. **v1 routing = explicit** (`--ns <name>`) **+ broadcast** (`--ns all`)
       An intent/LLM-based automatic router (reusing `IntentRouterMixin`) is OUT OF SCOPE for v1

- path: `sdd/state/FEAT-450/findings/F015-arango-isolation.md`
  excerpt: |
    F015 — ArangoDB namespaces are already "one database per wiki"
    A namespace entry {"backend": "arangodb", "database": "wiki_legal"} therefore maps 1:1
    onto an existing constructor argument

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py`
  lines: 160-175
  symbol: `ArangoDBWikiStore.__init__`
  excerpt: |
    database: str = "",
    self._database = database or f"wiki_{wiki_name or 'codebase'}"

## Notes

Direct consequence for U1: the federation/routing half of the multi-brain question is being
answered right now by another feature. The legal feature should consume it, not re-invent it —
and should coordinate, since FEAT-450 v1 explicitly defers the intent-based router.
