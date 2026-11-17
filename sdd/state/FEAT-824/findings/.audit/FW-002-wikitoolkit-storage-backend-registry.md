---
id: FW-002
query_id: Q202
type: wiki_query
intent: "Orientation: wikitoolkit storage backend"
executed_at: 2026-11-06T13:29:04Z
duration_ms: 3000
parent_id: null
depth: 0
---

# FW-002 — The wiki retrieval plane is already pluggable through `BaseWikiStore` + `WikiBackendSpec`; four built-ins exist (sqlite, memory, arangodb, postgres) and config still carries `arango_*` fields

## Summary

`wiki/store.py` holds the retrieval-plane seam: the `BaseWikiStore` ABC, a `WikiBackendSpec` table with built-ins `sqlite`/`memory` (kind `local`) and `arangodb`/`postgres` (kind `server`), `register_wiki_backend(...)` for extras, `resolve_wiki_backend`, `is_server_backend`, and the `create_wiki_store(storage_dir, wiki_name, backend="sqlite", **kwargs)` factory. Selection is explicit with no silent fallback. A PostgreSQL wiki store over the `graphindex.*` schema is **already shipped** (FEAT-520). `WikiProjectConfig` (`.parrot/wiki.json`) still documents the backend as `sqlite | memory | arangodb` and carries three Arango-specific fields. A SurrealDB wiki store is one more `register_wiki_backend("surrealdb", ..., kind="server")` entry, not a new store hierarchy.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 3288-3332
  symbol: `create_wiki_store`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#create_wiki_store
  score: 0.52 (Q202), 1.00 (Q203)
  excerpt: |
    backend: ``"sqlite"`` (single-file SQLite plane), ``"memory"``
        (in-memory indexes + OKF markdown directory), ``"arangodb"``
        (server-hosted, shared retrieval plane), or ``"postgres"``
        (server-hosted, shared ``graphindex.*`` schema — FEAT-520).
    ...
    Selection is explicit (``WikiConfig.storage_backend``) — there is no
    silent fallback: a broken/unavailable backend is a hard error.
    ...
    factory = resolve_wiki_backend(backend)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 782-786
  symbol: `_BUILTIN_WIKI_BACKENDS`
  excerpt: |
    _BUILTIN_WIKI_BACKENDS: dict[str, WikiBackendSpec] = {
        "sqlite": WikiBackendSpec(name="sqlite", kind="local", factory=_make_sqlite, resolve_options=_no_options),
        "memory": WikiBackendSpec(name="memory", kind="local", factory=_make_memory, resolve_options=_no_options),
        "arangodb": WikiBackendSpec(name="arangodb", kind="server", factory=_make_arangodb),
        "postgres": WikiBackendSpec(name="postgres", kind="server", factory=_make_postgres, resolve_options=_no_options),

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 712-712
  symbol: `WikiBackendSpec`
  excerpt: |
    class WikiBackendSpec(BaseModel):

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 794-794
  symbol: `register_wiki_backend`
  excerpt: |
    def register_wiki_backend(

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 856-870
  symbol: `resolve_wiki_backend`
  excerpt: |
    def resolve_wiki_backend(name: str) -> Callable[..., BaseWikiStore]:
    def is_server_backend(name: str) -> bool:
    class BaseWikiStore(ABC):

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
  lines: 589-831
  symbol: `WikiProjectConfig`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig
  score: 0.58 (Q202), 1.00 (Q204)
  excerpt: |
    backend: Retrieval-plane backend (``sqlite``, ``memory``, or ``arangodb``).
    arango_database: ArangoDB database name for the ``arangodb`` backend; defaults to ``wiki_{wiki_name}``.
    arango_credentials_env: Env var prefix used to resolve ArangoDB credentials (e.g. ``ARANGODB`` -> ``ARANGODB_HOST``, ...).
    arango_text_analyzer: ArangoSearch text analyzer used for the pages view's full-text search (e.g. ``"text_en"``).

- path: `sdd/tasks/completed/TASK-4323-wiki-backend-registry.md`
  symbol: `TASK-4323` (FEAT-540, status done)
  wiki_page_id: file:sdd/tasks/completed/TASK-4323-wiki-backend-registry.md
  score: 0.99
  excerpt: |
    Add `WikiBackendSpec`, built-in table (sqlite/memory local; arangodb/postgres server), `wiki_backend_names`,
    `wiki_backend_spec`, `resolve_wiki_backend`, `is_server_backend`; extend
    `register_wiki_backend(name, factory, *, kind='server', resolve_options=None)`.
    `parrot_tools/legal/__init__.py:16-20 register_wiki_backend('ontology_legal', OntologyLegalWikiStore.factory)`
    `parrot_tools.legal` registers with the old two-arg signature — keep it valid (default kind='server',
    resolve_options falls back to Arango params for backward compatibility of that one satellite).

## Notes

- Line numbers for `WikiBackendSpec` / `_BUILTIN_WIKI_BACKENDS` / `register_wiki_backend` / `resolve_wiki_backend` / `is_server_backend` / `BaseWikiStore` come from one confirming grep over `wiki/store.py`.
- Removing Arango from the wiki plane touches: the `arangodb` built-in entry, `WikiProjectConfig.arango_*` fields, `resolve_arango_params` (named in the `create_wiki_store` docstring), the `SourceCollectionManager` Arango branch (see FW-006) and the satellite `parrot_tools.legal` backend `ontology_legal` whose `resolve_options` default falls back to Arango params.
- The wiki's own data model is pages / edges / symbols / attrs / meta (see FW-005), not the draft's `bundle / document / section / chunk` SurrealQL schema — the draft's §5.2 schema does not correspond to the `BaseWikiStore` contract.
- [cross-lane: type=grep, intent=count BaseWikiStore abstract methods and list those a SurrealDB store must implement (wiki/store.py:870+), and check OntologyLegalWikiStore in parrot_tools/legal/wiki_store.py for its Arango dependency]
