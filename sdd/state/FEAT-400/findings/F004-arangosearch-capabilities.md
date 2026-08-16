---
id: F004
slug: arangosearch-capabilities
query: "ArangoSearch views, analyzers, asyncdb search methods"
type: read
---

# F004: ArangoSearch Capabilities in the Codebase

## asyncdb Driver (v2.15.9) — ArangoSearch Methods

Located at `.venv/.../asyncdb/drivers/arangodb.py`:

### View Management
- `create_arangosearch_view(view_name, links, primary_sort, stored_values)`
- `update_arangosearch_view(view_name, links)`
- `drop_arangosearch_view(view_name)`
- `create_vector_index(collection, field)` — convenience wrapper with `identity` analyzer

### Search Methods
- `fulltext_search(view_name, query_text, fields, analyzer, top_k, min_score)` — BM25-based FTS using `ANALYZER(doc.field IN TOKENS(...), ...)` + `BM25(doc)` scoring
- `vector_search(view_name, collection, query_vector, vector_field, top_k, filter_conditions)` — cosine via manual dot-product AQL (not native vector index)
- `hybrid_search(view_name, collection, query_text, query_vector, text_fields, vector_field, text_weight, vector_weight, analyzer, top_k)` — weighted BM25 + cosine in single AQL
- `arangosearch(view_name, search_expression, filter_conditions, sort_by, limit, offset, bind_vars)` — generic ArangoSearch query builder

### Graph Traversal
- `traverse()`, `shortest_path()`, `find_related_nodes()`, `semantic_search_with_context()`, `get_subgraph()`

## ArangoDBStore (ai-parrot-embeddings, stores/arango.py)

Existing `AbstractStore` implementation:
- Auto-creates ArangoSearch views on connect
- `similarity_search()`, `fulltext_search()`, `hybrid_search()`, `document_search()`
- View naming convention: `{collection_name}_view`
- Default analyzer: `text_en`
- Graph-enhanced retrieval via `_enrich_with_graph_context()`

## Gap: No ArangoSearch Views in Knowledge Subsystem

- Zero ArangoSearch views defined in ontology/ or graphindex/
- OntologyGraphStore only uses `_key` index and AQL traversals
- The wiki ArangoDB backend would be the FIRST user of ArangoSearch in the knowledge layer
- But all building blocks exist in asyncdb driver + ArangoDBStore patterns
