# GraphIndex core seams (FEAT-540)

FEAT-540 makes the graph tree (`parrot.knowledge.wiki`, `parrot.knowledge.graphindex`, and the
`ontology/{contracts,schema,validators}` modules) importable without the framework. Four seams keep
framework classes out of the core; each has a registry or Protocol so a new graph database plugs in by
registration, never by editing the core.

Gates that enforce this: `tests/knowledge/test_import_ceilings.py` (module-count ceilings, fresh
interpreter), `tests/knowledge/test_graph_tree_imports.py` (AST scan + `sys.meta_path` blocker),
`tests/knowledge/wiki/test_cli_surface.py` (CLI inventory; regenerate the baseline deliberately with
`UPDATE_GOLDEN=1`).

## 1. Lazy package roots and provider Protocols

* `parrot.knowledge.graphindex.__init__` resolves its exports through a module-level `__getattr__`
  (`GraphPublisher` and friends load on first access), so `import parrot.knowledge.graphindex` stays cheap.
* `graphindex/protocols.py` is stdlib-only. Framework classes satisfy these Protocols structurally and never
  inherit from them: `Embedder`, `LLMCaller`, `PageIndexer`, and the persistence family below.
  `ProviderNotAvailable` is raised when a provider cannot be resolved (the CLI `main()` maps it to exit code 2);
  `CapabilityUnavailable(backend, capability)` is raised when a backend lacks an optional capability.
* Framework-bound code (toolkits, LLM clients, embedding models, loaders) is imported function-locally behind
  the provider seam; the residual cases are listed in `sdd/state/FEAT-540/handoff-541.md`.

## 2. Plain operations and transports (wiki)

* `wiki/operations.py` holds transport-neutral operations (`op_query`, `op_page`, `op_related`, `op_remember`,
  `op_note`, `op_status`, `op_lint`, `op_standup`, bulk/sync ops) returning `OperationResult`, with plain
  Pydantic inputs (`WikiQueryInput`, ...).
* `wiki/transport.py` defines `OperationDescriptor` (name, description, input model, schema fingerprint, mount,
  `invoke`) and `build_operation_descriptors(bundle)`. `_MOUNTS` assigns each operation to a mount
  (`core`, `structural`, `decisions`, `schema`, `ledger`, `bulk`, `vault`).
* `wiki/mcp_server.py` consumes descriptors: `create_wiki_mcp_server(root, transport="auto"|"framework"|"sdk")`
  and `create_proxy_mcp_server(remote, transport=...)`. The `sdk` transport needs no framework; the `framework`
  transport lazily imports `parrot_tools.wiki` / `parrot.tools.abstract` only when selected.
* CLI: `wiki/cli.py` (`@click.group(name="wiki")`, function `wiki`, console script `main`) registers heavy
  command trees lazily through `wiki/lazy_commands.py` (`LazyGroup`, `LazyAdrGroup`).

## 3. Graph persistence registry (`graphindex/backends.py`)

* `GraphPersistence` Protocol (`persist_graph`, `replace_document_slice`, `load_graph`, `apply_update`,
  `get_commit`, `list_commits`, `revert_commit`, `close`) plus optional capability Protocols:
  `IncrementalPersistence` (`incremental`), `TemporalGraphPersistence` (`temporal`),
  `EmbeddingPersistence` (`embeddings`), `HybridRetrievalPersistence` (`hybrid`),
  `SourceCoherencePersistence` (`source_coherence`).
* `GraphBackendSpec(name, factory="module:callable", required_options, capabilities, extra, project_options)`;
  `register_graph_backend(spec)`, `graph_backend_names()`, `graph_backend_spec(name)`.
* `await create_graph_persistence(backend, **options)` is the only composition root: it validates
  `required_options`, imports the factory lazily (a missing third-party driver becomes an install hint naming
  `spec.extra`), and awaits the result when the factory is async.
* Built-ins: `sqlite` (incremental, source_coherence), `null` (`NullPersistence`), `postgres`
  (temporal, embeddings, hybrid, incremental, source_coherence), `arangodb`.
* `wiki/runtime.py:persistence_for_project(config, root, tenant_id=None)` maps a wiki project to a persistence:
  a backend whose spec declares `project_options` (`"module:callable"` taking `(config, root, tenant_id)` and
  returning factory options) is used when it matches `config.backend`; otherwise the SQLite graph plane.

## 4. Wiki store and source-manifest registries

* `wiki/store.py`: `register_wiki_backend(name, factory, *, kind="server"|"local", resolve_options=None)`,
  `wiki_backend_names()`, `wiki_backend_spec(name)`, `resolve_wiki_backend(name)`, `is_server_backend(name)`;
  built-ins (`sqlite`, `memory`, `arangodb`, `postgres`) live in `_BUILTIN_WIKI_BACKENDS` (`WikiBackendSpec`).
  A satellite cannot reuse a built-in name.
* `wiki/sources_backend.py`: `SourceManifestBackend` Protocol, `register_source_backend(name, factory)`,
  `create_source_backend(name, **options)`; built-ins `SqliteSourceBackend`, `JsonSourceBackend`, and an
  Arango factory.

## 5. Ontology contracts (`ontology/contracts.py`, `ontology/validators.py`, `ontology/schema.py`)

* `GraphDocumentStore` (ABC): document/edge CRUD plus `execute_query(ctx, DynamicQuery)`.
* `OntologyTraversalStore` (ABC): `dialect: ClassVar[str]`, `is_reachable`, `get_document_by_id`,
  `find_by_field`, ... The built-in `ArangoOntologyGraphStore(GraphDocumentStore, OntologyTraversalStore)`
  lives in `ontology/graph_store.py`.
* `register_ontology_backend(name, factory)` / `create_ontology_graph_store(backend, **options)`; the ArangoDB
  store is imported only when requested.
* `register_query_validator(dialect, validator)` / `validate_query(dialect, text, max_depth)` in
  `validators.py`.
* `TraversalPattern.query_templates: dict[str, str]` (`ontology/schema.py`) holds per-dialect query text;
  `intent.py` selects `query_templates[dialect]` before falling back to `query_template`.

## Recipe: plugging a new graph backend (FEAT-670)

1. Implement `GraphPersistence` (and any capability Protocols you can honour) in a satellite module. Do not
   import the framework at module level; do not inherit from the Protocols.
2. Expose a factory `module:callable` (sync or async) accepting the options you declare as required.
3. Register it at import of the satellite's entry point:
   `register_graph_backend(GraphBackendSpec(name="helix", factory="pkg.mod:create", required_options=(...),
   capabilities=(...), extra="helixdb", project_options="pkg.mod:project_options"))`.
4. Wiki store (if the backend also stores pages): `register_wiki_backend("helix", factory, kind="server",
   resolve_options=...)`; source manifests: `register_source_backend("helix", factory)`.
5. Ontology: implement `GraphDocumentStore` and `OntologyTraversalStore` with a `dialect`, call
   `register_ontology_backend(...)` and `register_query_validator(dialect, validator)`, and ship patterns with
   `query_templates["<dialect>"]`.
6. Run the persistence conformance suite against the new name (it asserts every Protocol bullet for every
   registered backend), then the three gates listed at the top.

Note: `docs/architecture/09-ontologic-rag.md` still describes the removed `OntologyGraphStore` /
`execute_traversal`; it was intentionally not edited here (see the FEAT-541 handoff).
