---
id: FC-014
query_id: Q014
type: grep
intent: "Full inventory of ArangoDB consumers OUTSIDE ontology/wiki/graphindex (vector store, legal/BOE, formdesigner sinks, manuals, contracts, routing, multistoresearch) — the part of 'remove ArangoDB' the draft does not cover"
executed_at: 2026-11-06T13:47:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-014 — 43 source files outside ontology/wiki/graphindex mention ArangoDB, across four distributions; the draft covers none of them

## Summary

`grep -rciE "arango" packages/*/src --include="*.py"` minus `knowledge/(ontology|wiki|graphindex)/` lists **43 files** in `ai-parrot`, `ai-parrot-embeddings`, `ai-parrot-tools` and `parrot-formdesigner`. The heavy ones are real ArangoDB code, not mentions: the GraphIndex loader (`parrot/loaders/graphindex.py`, 46 matches — builds the Arango client and store), the **Arango vector store** (`ai-parrot-embeddings/.../stores/arango.py`, 30), the **`arangodbsearch` tool** (27), the **employee hierarchy interface** (`parrot/interfaces/hierarchy.py`, 24), the **legal wiki store** (`parrot_tools/legal/wiki_store.py`, 22), the **wiki toolkit** tools (19), a **formdesigner asyncdb sink** (15) and **registry routing rules** (15). The legal/BOE domain (`legal/boe/{sync,queries,datasource,models}.py`, `legal/ids.py`, `legal/librarian/*`) and the contracts and manuals graph loaders write/read instance graphs through `ArangoOntologyGraphStore` (FC-003). "ArangoDB must be removed" therefore reaches well beyond ontology + wiki + L1: a vector-store backend, an agent tool, an HR hierarchy interface, a form-submission sink and two domain packs.

## Citations

- path: `packages/ai-parrot/src/parrot/loaders/graphindex.py`
  lines: 227-248
  symbol: `_make_persistence` (46 matches in file)
  excerpt: |
    elif self._backend == "arangodb":
        from asyncdb import AsyncDB
        db = AsyncDB("arangodb", params=self._arango_params)
        ...
        self.graph_store = create_ontology_graph_store("arangodb", arango_client=db)

- path: `packages/ai-parrot-embeddings/src/parrot/stores/arango.py`
  lines: 1-1
  symbol: Arango vector store module (30 matches; not opened)
  excerpt: |
    packages/ai-parrot-embeddings/src/parrot/stores/arango.py:30

- path: `packages/ai-parrot-tools/src/parrot_tools/arangodbsearch.py`
  lines: 171-171
  symbol: `arangodbsearch` tool (27 matches)
  excerpt: |
    171:            "host": config.get('ARANGODB_HOST', 'localhost'),

- path: `packages/ai-parrot/src/parrot/interfaces/hierarchy.py`
  lines: 1-1
  symbol: hierarchy interface (24 matches; not opened)
  excerpt: |
    packages/ai-parrot/src/parrot/interfaces/hierarchy.py:24

- path: `packages/ai-parrot-tools/src/parrot_tools/legal/wiki_store.py`
  lines: 25-210
  symbol: legal wiki store (22 matches)
  excerpt: |
    25:from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore
    210:            self._store = ArangoOntologyGraphStore(arango_client=client)

- path: `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py`
  lines: 1-1
  symbol: wiki toolkit (19 matches; not opened)
  excerpt: |
    packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py:19

- path: `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/asyncdb_store.py`
  lines: 1-1
  symbol: formdesigner asyncdb sink (15 matches; not opened)
  excerpt: |
    packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/asyncdb_store.py:15

- path: `packages/ai-parrot/src/parrot/registry/routing/rules.py`
  lines: 1-1
  symbol: routing rules (15 matches; not opened)
  excerpt: |
    packages/ai-parrot/src/parrot/registry/routing/rules.py:15

- path: `packages/ai-parrot-tools/src/parrot_tools/legal/boe/sync.py`
  lines: 17-62
  symbol: BOE sync (6 matches)
  excerpt: |
    17:from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore
    62:    graph_store = ArangoOntologyGraphStore()

## Notes

Full list (file: case-insensitive match count), exactly as returned:

- **ai-parrot (core)** — `loaders/graphindex.py` 46 · `interfaces/hierarchy.py` 24 · `registry/routing/rules.py` 15 · `bots/abstract.py` 6 · `knowledge/manuals/models.py` 4 · `knowledge/contracts/graph_loader.py` 3 · `models/stores.py` 2 · `conf.py` 2 · `stores/__init__.py` 1 · `security/query_validator.py` 1 · `registry/routing/cache.py` 1 · `knowledge/retrieval/policies/vector_seed.py` 1 · `knowledge/pageindex/okf/graph.py` 1 · `knowledge/okf/uri.py` 1 · `knowledge/manuals/__init__.py` 1 · `knowledge/manuals/graph_loader.py` 1 · `knowledge/contracts/__init__.py` 1 · `knowledge/contracts/catalog.py` 1 · `flows/dev_loop/graph_memory.py` 1
- **ai-parrot-embeddings** — `stores/arango.py` 30
- **ai-parrot-tools** — `arangodbsearch.py` 27 · `legal/wiki_store.py` 22 · `wiki/toolkit.py` 19 · `wiki/structural.py` 6 · `wiki/decisions.py` 6 · `legal/ids.py` 6 · `legal/boe/sync.py` 6 · `legal/boe/queries.py` 6 · `graphindex/flowtask.py` 6 · `multistoresearch/origins/vector.py` 4 · `legal/librarian/suppression.py` 2 · `graphindex/toolkit.py` 2 · `contracts/retrieval.py` 2 · `legal/librarian/flow.py` 1 · `legal/boe/models.py` 1 · `legal/boe/datasource.py` 1 · `__init__.py` 1 · `contracts/jobs.py` 1
- **parrot-formdesigner** — `services/sinks/asyncdb_store.py` 15 · `core/persistence.py` 3 · `core/schema.py` 2 · `services/sinks/mapper.py` 1 · `services/sinks/base.py` 1

Caveats:
- Counts include comments/docstrings. Only `loaders/graphindex.py` (L222-251), and the grep-line evidence from FC-003/FC-013 for `legal/*` and `arangodbsearch.py`, were inspected; the role labels for `stores/arango.py`, `interfaces/hierarchy.py`, `wiki/toolkit.py`, `asyncdb_store.py` and `routing/rules.py` are inferred from path + match density and are **unverified**.
- Inside the three excluded packages the parent's planning grep counted 17 (wiki) + 11 (graphindex) + 10 (ontology) + 2 (wiki/standup) + 2 (concept_catalog) + 1 (schema_overlay) files.
- Tests were not counted (`packages/*/tests`).
- [cross-lane: type=wiki_query, intent=what do parrot.interfaces.hierarchy (employee hierarchy) and parrot.stores.arango (vector store) use ArangoDB for, and is either scheduled for removal by an existing spec]
