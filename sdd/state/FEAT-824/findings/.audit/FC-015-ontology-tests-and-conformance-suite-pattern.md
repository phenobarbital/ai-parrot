---
id: FC-015
query_id: Q015
type: glob
intent: "Which tests pin the ontology graph-store behaviour (reusable as a contract suite)?"
executed_at: 2026-11-06T13:48:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-015 — 21 ontology test modules exist (16 for the subsystem, 5 domain/routing); the reusable "one suite, every backend" pattern exists for GraphIndex, not for the ontology store

## Summary

`find packages/*/tests -iname "*ontology*" -o -iname "*graph_store*" -o -iname "*conformance*"`. The ontology subsystem has 16 test modules under `packages/ai-parrot/tests/knowledge/` (`test_ontology_{graph_store,integration,mixin,intent,intent_demotion,merger,parser,refresh,schema,schema_extensions,tenant,validators,discovery,cache_key}.py`, `test_employee_ontology_smoke.py`, `ontology/test_legal_ontology.py`) plus domain ones (`contracts/test_ontology_domain.py`, `okf/test_ontology.py`, `pageindex/test_okf_ontology.py`, `graphindex/test_meta_ontology.py`, `unit/registry/routing/test_ontology_signal.py`). `test_ontology_graph_store.py` is the store's own test file (contents not opened — whether it mocks AsyncDB or needs a live server is unverified). The draft's "shared contract suite, same cases against every backend" already has a house pattern: `tests/knowledge/graphindex/persistence_conformance.py` exports backend-agnostic `case_*` coroutines derived from the `GraphPersistence` docstring semantics. No equivalent conformance module exists for `GraphDocumentStore` / `OntologyTraversalStore`.

## Citations

- path: `packages/ai-parrot/tests/knowledge/graphindex/persistence_conformance.py`
  lines: 1-45
  symbol: `case_apply_and_revert` (+ `ALL_CASES` / `STATELESS_CASES`)
  excerpt: |
    """Reusable GraphPersistence conformance cases (FEAT-540 M7).
    Import the ``case_*`` coroutines (or ``ALL_CASES`` / ``STATELESS_CASES``) from a per-backend test and call each
    with a fresh ``persistence`` and a ``ctx`` that has a ``tenant_id``. Every case derives its expectations from the
    semantics documented on ``parrot.knowledge.graphindex.protocols.GraphPersistence``.
    Case = Callable[[Any, Any], Awaitable[None]]
    async def case_apply_and_revert(persistence: Any, ctx: Any) -> None:

- path: `packages/ai-parrot/tests/knowledge/test_ontology_graph_store.py`
  lines: 1-1
  symbol: ontology graph store tests (file listed, not opened)
  excerpt: |
    packages/ai-parrot/tests/knowledge/test_ontology_graph_store.py

- path: `packages/ai-parrot/tests/knowledge/test_ontology_integration.py`
  lines: 1-1
  symbol: `TestGracefulDegradation.test_arango_unavailable` (from wiki query result, file not opened)
  excerpt: |
    TestGracefulDegradation.test_arango_unavailable — ArangoDB down → degrades to vector_only without error.

## Notes

Files returned by the find (ontology-related):
`packages/ai-parrot/tests/knowledge/contracts/test_ontology_domain.py`, `.../graphindex/persistence_conformance.py`, `.../graphindex/test_meta_ontology.py`, `.../okf/test_ontology.py`, `.../ontology/test_legal_ontology.py`, `.../pageindex/test_okf_ontology.py`, `.../test_employee_ontology_smoke.py`, `.../test_ontology_cache_key.py`, `.../test_ontology_discovery.py`, `.../test_ontology_graph_store.py`, `.../test_ontology_integration.py`, `.../test_ontology_intent_demotion.py`, `.../test_ontology_intent.py`, `.../test_ontology_merger.py`, `.../test_ontology_mixin.py`, `.../test_ontology_parser.py`, `.../test_ontology_refresh.py`, `.../test_ontology_schema_extensions.py`, `.../test_ontology_schema.py`, `.../test_ontology_tenant.py`, `.../test_ontology_validators.py`, `packages/ai-parrot/tests/unit/registry/routing/test_ontology_signal.py`. Unrelated conformance hits: `packages/ai-parrot-semantic/tests/sink_conformance.py`, `tests/outputs/a2ui/conformance/`, `tests/voice/test_provider_conformance.py`, `packages/parrot-formdesigner/tests/unit/test_snippet_conformance.py`.

- An integration test also exists at `packages/ai-parrot/tests/integration/rag/test_store_router_integration.py::test_router_with_real_arango` (seen in the parent's wiki query, not opened).
- The draft mentions `testcontainers` for Postgres and SurrealDB; whether `testcontainers` is already a dev dependency was not checked.
- [cross-lane: type=wiki_query, intent=how do existing Postgres-backed tests (graphindex postgres persistence, PostgresWikiStore) obtain a database in CI — testcontainers, local DSN env var, or skip-if-unreachable]
