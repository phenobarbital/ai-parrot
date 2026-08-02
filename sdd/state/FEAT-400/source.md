---
kind: inline
jira_key: null
fetched_at: "2026-08-01T12:00:00Z"
summary_oneline: "ArangoDB as configurable backend for LLM Wiki (WikiToolkit)"
---

# ArangoDB as Configurable Backend for LLM Wiki (WikiToolkit)

Currently the wiki retrieval plane is SQLite-only (with an InMemoryWikiStore
for testing). The goal is to make the database backend configurable via
`.parrot/wiki.json` so teams can point their wiki at a centralized ArangoDB
instance instead of local SQLite.

## Key Context

- `BaseWikiStore` already defines 15 abstract methods with two working
  backends (`SQLiteWikiStore`, `InMemoryWikiStore`).
- `OntologyGraphStore` in `parrot/knowledge/ontology/graph_store.py` already
  provides a mature async ArangoDB wrapper.
- The `create_wiki_store()` factory is the single construction point.
- `WikiProjectConfig.backend` is `Literal["sqlite", "memory"]`.
- `SourceCollectionManager` has its own separate SQLite persistence for source
  tracking.

## Scope Areas

1. New `ArangoDBWikiStore(BaseWikiStore)` class.
2. Extending `WikiProjectConfig` with ArangoDB connection fields.
3. Extending the `create_wiki_store()` factory.
4. Handling `SourceCollectionManager` for the new backend.
5. ArangoSearch strategy for FTS and vector search.
6. Reusing `OntologyGraphStore`.
7. Credentials management (env vars, never hardcoded).
