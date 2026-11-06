---
id: FC-003
query_id: Q003
type: grep
intent: "Who constructs or calls the ontology graph store (blast radius of swapping the backend)?"
executed_at: 2026-11-06T13:34:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-003 — Only half the callers use the neutral contract; the rest import the concrete Arango class

## Summary

`grep -rnE "create_ontology_graph_store|OntologyGraphStore|register_ontology_backend|GraphDocumentStore|OntologyTraversalStore" packages/*/src` (excluding `graph_store.py` itself). Query-time ontology callers (`mixin.py`, `entity_resolver.py`, `authorization.py`) are typed against `OntologyTraversalStore`; GraphIndex's `persist_arango.py` is typed against `GraphDocumentStore`. But the ingestion/sync side and the whole legal domain import **`ArangoOntologyGraphStore` directly**: `refresh.py`, `concept_catalog/reconcile.py`, `concept_catalog/worker.py`, and in `ai-parrot-tools` `legal/boe/queries.py`, `legal/boe/sync.py`, `legal/wiki_store.py`, `legal/librarian/suppression.py`. The factory `create_ontology_graph_store` has exactly **one** production call site (`parrot/loaders/graphindex.py:242`), hard-coding `"arangodb"`. `register_ontology_backend` has no callers in `src`.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py`
  lines: 78-124
  symbol: `OntologyRAGMixin` (graph_store parameter)
  excerpt: |
    78:    from .contracts import OntologyTraversalStore
    124:        graph_store: OntologyTraversalStore | None = None,

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py`
  lines: 29-115
  symbol: `graph_store: OntologyTraversalStore`
  excerpt: |
    29:    from .contracts import OntologyTraversalStore
    115:        graph_store: OntologyTraversalStore,

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py`
  lines: 44-84
  symbol: `graph_store: OntologyTraversalStore`
  excerpt: |
    44:    from .contracts import OntologyTraversalStore
    84:        graph_store: OntologyTraversalStore,

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py`
  lines: 22-80
  symbol: `graph_store: ArangoOntologyGraphStore`
  excerpt: |
    22:from .graph_store import ArangoOntologyGraphStore, UpsertResult
    80:        graph_store: ArangoOntologyGraphStore,

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/reconcile.py`
  lines: 26-92
  symbol: `graph_store: ArangoOntologyGraphStore`
  excerpt: |
    26:from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore
    92:        graph_store: ArangoOntologyGraphStore,

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py`
  lines: 7-18
  symbol: `ArangoOntologyGraphStore` (public lazy export)
  excerpt: |
    7:    "ArangoOntologyGraphStore": "parrot.knowledge.ontology.graph_store",
    18:    "ArangoOntologyGraphStore",

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_arango.py`
  lines: 52-884
  symbol: `ArangoPersistence` (takes `GraphDocumentStore`)
  excerpt: |
    52:    from parrot.knowledge.ontology.contracts import GraphDocumentStore
    210:    def __init__(self, store: "GraphDocumentStore") -> None:
    876:        from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore
    884:        graph_store = ArangoOntologyGraphStore(arango_client=client)

- path: `packages/ai-parrot/src/parrot/loaders/graphindex.py`
  lines: 227-248
  symbol: `_make_persistence`
  excerpt: |
    elif self._backend == "arangodb":
        from asyncdb import AsyncDB
        db = AsyncDB("arangodb", params=self._arango_params)
        ...
        self.graph_store = create_ontology_graph_store("arangodb", arango_client=db)
        ...
        options.update(graph_store=self.graph_store, arango_params=self._arango_params, tenant_ctx=self.ctx)
    return await create_graph_persistence(self._backend, **options)

- path: `packages/ai-parrot-tools/src/parrot_tools/legal/boe/queries.py`
  lines: 8-152
  symbol: `store: ArangoOntologyGraphStore`
  excerpt: |
    8:``ArangoOntologyGraphStore.execute_pattern``, and deserialising the result. It
    23:from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore
    33:    store: ArangoOntologyGraphStore,

- path: `packages/ai-parrot-tools/src/parrot_tools/legal/boe/sync.py`
  lines: 17-119
  symbol: `graph_store = ArangoOntologyGraphStore()`
  excerpt: |
    17:from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore
    62:    graph_store = ArangoOntologyGraphStore()
    108:    graph_store: ArangoOntologyGraphStore,

- path: `packages/ai-parrot-tools/src/parrot_tools/legal/wiki_store.py`
  lines: 25-210
  symbol: `self._store = ArangoOntologyGraphStore(arango_client=client)`
  excerpt: |
    25:from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore
    77:        store: ArangoOntologyGraphStore | None = None,
    210:            self._store = ArangoOntologyGraphStore(arango_client=client)

- path: `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/suppression.py`
  lines: 16-34
  symbol: `__init__(self, store: ArangoOntologyGraphStore, ctx: TenantContext)`
  excerpt: |
    16:from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore
    34:    def __init__(self, store: ArangoOntologyGraphStore, ctx: TenantContext) -> None:

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py`
  lines: 14-47
  symbol: `ConceptCatalogSyncWorker.__init__`
  excerpt: |
    14:from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore
    47:        graph_store: ArangoOntologyGraphStore,

## Notes

- Docstring-only mentions (no import): `knowledge/graphindex/assemble.py:9`, `knowledge/wiki/arango_store.py:19`, `knowledge/contracts/graph_loader.py:187`, `parrot_tools/legal/ids.py:103`, `parrot_tools/legal/boe/datasource.py:143`, `parrot_tools/contracts/retrieval.py:252`, `parrot_tools/graphindex/flowtask.py:198`.
- Blast radius of deleting the Arango module = 7 importing modules across two distributions (`ai-parrot`, `ai-parrot-tools`) + the public `parrot.knowledge.ontology.ArangoOntologyGraphStore` export.
