---
id: F009
query_id: Q009
type: grep
intent: "What is the wikitoolkit storage-backend abstraction (sqlite vs arango) that a SurrealDB KnowledgeStore would replace or implement?"
executed_at: 2026-11-06T13:41:00Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-009, FW-002]
---

# F009 — wikitoolkit already has a backend registry with FOUR planes, one of them Postgres (FEAT-520)

## Summary

The wiki plane is behind `BaseWikiStore(ABC)` (`wiki/store.py:870`) with a registry `_BUILTIN_WIKI_BACKENDS` of `WikiBackendSpec(name, kind: local|server, factory, resolve_options, ...)`: **`sqlite`** (local, `wiki.db`), **`memory`** (local, OKF markdown dir), **`arangodb`** (server) and **`postgres`** (server, `PostgresWikiStore`, FEAT-520). Satellites add backends through `register_wiki_backend(name, factory, kind=, resolve_options=)`; `create_wiki_store(backend, ...)` dispatches. `PostgresWikiStore` (1113 lines) implements the full contract over the **shared `graphindex.*` schema** (bitemporal `nodes`/`node_versions`/`edges`, tsvector FTS, native pgvector KNN) — "one shared bitemporal plane serves both the graph and wiki contracts". So a non-Arango **server** plane for the wiki already ships; a SurrealDB store would be a *fifth* `BaseWikiStore` backend, not the first replacement. The Arango-specific residue is in callers: `config.backend == "arangodb"` branches in `cli.py`, `sync.py`, `mcp_server.py`, `entity_cli.py`, `standup/cli.py`, `obsidian_sync.py`, `federation.py`, the source-manifest backend (`arango_sources.py`), and `wikitoolkit serve`, which **refuses any backend other than `arangodb`**.

`wiki/store.py` holds the retrieval-plane seam: the `BaseWikiStore` ABC, a `WikiBackendSpec` table with built-ins `sqlite`/`memory` (kind `local`) and `arangodb`/`postgres` (kind `server`), `register_wiki_backend(...)` for extras, `resolve_wiki_backend`, `is_server_backend`, and the `create_wiki_store(storage_dir, wiki_name, backend="sqlite", **kwargs)` factory. Selection is explicit with no silent fallback. A PostgreSQL wiki store over the `graphindex.*` schema is **already shipped** (FEAT-520). `WikiProjectConfig` (`.parrot/wiki.json`) still documents the backend as `sqlite | memory | arangodb` and carries three Arango-specific fields. A SurrealDB wiki store is one more `register_wiki_backend("surrealdb", ..., kind="server")` entry, not a new store hierarchy.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 712-735
  symbol: `WikiBackendSpec`
  excerpt: |
    class WikiBackendSpec(BaseModel):
        """One wiki backend entry of the registry (FEAT-540 M7).
        name: str
        kind: Literal["local", "server"]
        factory: Any
        resolve_options: Any = None
        is_built: str | None = None
        extra: str | None = None

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 764-787
  symbol: `_BUILTIN_WIKI_BACKENDS`
  excerpt: |
    def _make_postgres(*, wiki_name: str = "", **kwargs: Any) -> BaseWikiStore:
        """Build the server-hosted PostgreSQL plane (FEAT-520)."""
        from parrot.knowledge.graphindex.pg_schema import GRAPHINDEX_PG_DSN
        from parrot.knowledge.wiki.postgres_store import PostgresWikiStore
    _BUILTIN_WIKI_BACKENDS: dict[str, WikiBackendSpec] = {
        "sqlite": WikiBackendSpec(name="sqlite", kind="local", factory=_make_sqlite, resolve_options=_no_options),
        "memory": WikiBackendSpec(name="memory", kind="local", factory=_make_memory, resolve_options=_no_options),
        "arangodb": WikiBackendSpec(name="arangodb", kind="server", factory=_make_arangodb),
        "postgres": WikiBackendSpec(name="postgres", kind="server", factory=_make_postgres, resolve_options=_no_options),
    }

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 794-818
  symbol: `register_wiki_backend`
  excerpt: |
    def register_wiki_backend(
        name: str,
        factory: Callable[..., BaseWikiStore],
        *,
        kind: Literal["local", "server"] = "server",
        resolve_options: Callable[[Any], dict[str, Any]] | None = None,
    ) -> None:
        """Register a satellite-provided wiki backend (FEAT-449 M7, FEAT-540 M7).

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 870-1247
  symbol: `BaseWikiStore`
  excerpt: |
    @abstractmethod: upsert_pages (L917), add_edges (L920), replace_source_slice (L923), delete_page (L931),
      upsert_embedding (L934), get_page (L938), list_pages (L941), search_fts (L949), search_vector (L952),
      neighbors (L955), dump_pages (L963), dump_edges (L966), stats (L969), orphan_sources (L973),
      broken_edges (L976), missing_bodies (L993)
    concrete/optional: get_attrs (L891), list_by_attrs (L895), upsert_attrs (L907), rebuild_index (L978),
      index_drift (L988), compare_and_swap_page (L997), get_meta (L1031), set_meta (L1045),
      rebuild_from_tree (L1062), upsert_symbols (L1131), symbols_for (L1151), find_symbols (L1178),
      search_symbols_fts (L1226), page_hashes (L1247)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py`
  lines: 1-50
  symbol: module docstring
  excerpt: |
    Fourth :class:`~parrot.knowledge.wiki.store.BaseWikiStore` backend
    (alongside SQLiteWikiStore, InMemoryWikiStore, ArangoDBWikiStore), and the SECOND contract implemented
    over the SAME ``graphindex.*`` schema as PostgresPersistence
    (spec U1 — one shared bitemporal plane serves both the graph and wiki contracts).
    ...
    FEAT-520 Module 6 (TASK-2769) upgrades :meth:`search_vector` ... to a native pgvector KNN query
    (``<=>`` cosine distance, joined to CURRENT versions only)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py`
  lines: 127-160
  symbol: `PostgresWikiStore`
  excerpt: |
    class PostgresWikiStore(BaseWikiStore):
        """Postgres-backed wiki retrieval plane over the shared ``graphindex.*`` schema.
        def __init__(self, dsn: Optional[str] = None, *, wiki_name: str = "", schema: str = "graphindex",
                     pool: Optional[asyncpg.Pool] = None) -> None:

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py`
  lines: 137-335
  symbol: `ArangoDBWikiStore`
  excerpt: |
    137:class ArangoDBWikiStore(BaseWikiStore):
    294:            self._db = AsyncDB("arangodb", params={**self._params, "database": self._database})
    324:        probe = AsyncDB("arangodb", params={**self._params, "database": "_system"})

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/serve.py`
  lines: 137-141
  symbol: `build_server_app`
  excerpt: |
    for name, entry in config.wikis.items():
        effective_config = load_effective_config(entry.root, env=entry.env).config
        if effective_config.backend != "arangodb" and not config.allow_sqlite_for_tests:
            raise click.ClickException(f"wiki {name!r}: backend must be arangodb (got {effective_config.backend})")

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py`
  lines: 50-380
  symbol: `SourceManifestBackend` / `create_source_backend`
  excerpt: |
    50:class SourceManifestBackend(Protocol):
    67:class AsyncSourceManifestBackend(Protocol):
    98:def create_source_backend(name: str, **options: Any) -> SourceManifestBackend:
    119:class SqliteSourceBackend:
    213:class JsonSourceBackend:
    380:register_source_backend("arangodb", _create_arango_backend)

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

- Sizes: `store.py` 3332 lines (contract + SQLite reference), `arango_store.py` 1350, `postgres_store.py` 1113, `file_store.py` 909, `federation.py` 1777.
- `PostgresWikiStore` documents two gaps versus SQLite: `orphan_sources()` always `[]` (no `sources` registry table in the shared schema) and `dump_edges()` not namespace-scoped. There is no Postgres source-manifest backend (`sources_backend.py` registers `sqlite`, `json`, `arangodb` only — as seen in the grep; the registration lines for sqlite/json were not opened).
- `config.backend == "arangodb"` branch sites seen: `entity_cli.py:107`, `sync.py:116,148`, `obsidian_sync.py:471`, `federation.py:203,243,403,417`, `mcp_server.py:174`, `standup/cli.py:55`, `cli.py:510,574,641,2326`, `project.py:269`.
- The draft's premise "wiki = SQLite per-repo (local) / ArangoDB (remote)" is out of date: a Postgres server plane exists, with hybrid FTS + vector. The draft's D4 argument ("Postgres plano" discarded for the wiki) is in tension with shipped code.
- [cross-lane: type=wiki_page, intent=FEAT-520 graphindex-postgres-backend spec — is the postgres wiki plane considered production-ready, and what did it defer (sources registry, serve gate)]
- [cross-lane: type=git_log, intent=when did postgres_store.py land and has `wikitoolkit serve` ever been relaxed to accept postgres]
- Line numbers for `WikiBackendSpec` / `_BUILTIN_WIKI_BACKENDS` / `register_wiki_backend` / `resolve_wiki_backend` / `is_server_backend` / `BaseWikiStore` come from one confirming grep over `wiki/store.py`.
- Removing Arango from the wiki plane touches: the `arangodb` built-in entry, `WikiProjectConfig.arango_*` fields, `resolve_arango_params` (named in the `create_wiki_store` docstring), the `SourceCollectionManager` Arango branch (see F026) and the satellite `parrot_tools.legal` backend `ontology_legal` whose `resolve_options` default falls back to Arango params.
- The wiki's own data model is pages / edges / symbols / attrs / meta (see F025), not the draft's `bundle / document / section / chunk` SurrealQL schema — the draft's §5.2 schema does not correspond to the `BaseWikiStore` contract.
- [cross-lane: type=grep, intent=count BaseWikiStore abstract methods and list those a SurrealDB store must implement (wiki/store.py:870+), and check OntologyLegalWikiStore in parrot_tools/legal/wiki_store.py for its Arango dependency]
