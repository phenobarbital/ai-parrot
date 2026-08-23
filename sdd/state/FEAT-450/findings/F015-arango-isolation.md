---
id: F015
query_id: Q024,Q025
type: read
intent: Confirm ArangoDB backend isolates wikis per database and its spec targets cross-repo sharing
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F015 — ArangoDB namespaces are already "one database per wiki"; spec names cross-repo sharing as a goal

## Summary
`ArangoDBWikiStore.__init__` (arango_store.py:160-175): `self._database = database or
f"wiki_{wiki_name or 'codebase'}"` (172). The backend spec's Problem Statement lists "Shared
knowledge graphs: multiple repos/agents pointing at the same wiki instance" and "cross-repository
knowledge retrieval" (spec:24-31). A namespace entry `{"backend": "arangodb", "database": "wiki_legal"}`
therefore maps 1:1 onto an existing constructor argument; credentials keep coming from the
`ARANGODB_*` env prefix (F009).

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py`
  lines: 160-175
  symbol: `ArangoDBWikiStore.__init__`
  excerpt: |
    database: str = "",
    self._database = database or f"wiki_{wiki_name or 'codebase'}"
- path: `sdd/specs/wikitoolkit-arangodb-backend.spec.md`
  lines: 18-34
  excerpt: |
    - **Shared knowledge graphs**: multiple repos/agents pointing at the same wiki instance
    - **Graph-native queries**: ... for cross-repository knowledge retrieval.
