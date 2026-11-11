---
kind: inline
jira_key: null
fetched_at: 2026-11-11T22:03:39Z
summary_oneline: "DatasetManager add_semantic(): register a dataset whose data comes from a Semantic Layer YAML model, compiled to SQL and run by DatasetManager"
---

# Source (inline, user request)

Could the DatasetManager toolkit support the Semantic Layer? An `add_semantic(<yaml file>, driver)`
registration so a dataset's data does not come from a raw SQL query (or a Query slug) but from a
Semantic Layer YAML definition. The dataset is compiled (native sqlglot compiler), producing SQL that
is then executed by DatasetManager itself with its internal execution capabilities.

Questions to verify:

1. How DatasetManager registers and fetches sources today (add_query / query slug / table sources,
   lazy fetch, caching) and where a semantic source type would plug in.
2. What the semantic layer exposes for compile-only use (SemanticModelLoader, NativeCompiler /
   engines.compile, SemanticQuery, GovernancePipeline) and the existing opposite-direction hand-off
   (`dataset_manager_factory`, `GovernedDatasetSink`, handoff.py).
3. Governance: must compiled SQL executed by DatasetManager still go through PBAC / RLS / masking /
   audit, or is this limited to `governed: false` models? It must not become a governance bypass.
4. Does the dataset pin a SemanticQuery (metrics / dimensions / filters) at registration, or compile
   per fetch with parameters?
5. Driver / dialect and connection resolution (toolkit `dialect`, policy `connection`,
   `PARROT_SEMANTIC_CONN_*` env) versus DatasetManager's own credentials / driver handling.
6. Secondary, possibly its own spec: at operation time, keep data extracted through the semantic
   source in a DuckDB database instead of in-memory DataFrames - how DatasetManager holds data today
   and what a DuckDB-backed store would touch.

Expected output: verify possibility and scope, and say whether this fits one spec or should be split.
