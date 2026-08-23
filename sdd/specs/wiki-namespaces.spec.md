---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# FEAT-450 was reserved by /sdd-proposal via reserve_ids.py (ledger commit de08ac3e2,
# label wiki-namespaces) — reused here intentionally; no second reservation.
reuse_feature_id: FEAT-450
---

# Feature Specification: Namespaces for `wikitoolkit` (multi-wiki federation)

**Feature ID**: FEAT-450
**Date**: 2026-08-23
**Author**: Jesus Lara (spec: Claude session 2026-08-23)
**Status**: draft
**Target version**: next minor
**Input**: `sdd/proposals/wiki-namespaces.proposal.md` (status `accepted`, research audit `sdd/state/FEAT-450/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

Today each LLM Wiki is a single plane per repo (`.parrot/wiki.json` → `storage_dir/wiki.db`);
`wikitoolkit query` / `page` / `related` / `status`, the six `AbstractTool` wrappers and the MCP
server read exactly one store (`cli.py:_resolve_read_store` 199-251, `tools.py:create_wiki_tools`
399-428, `mcp_server.py:create_wiki_mcp_server` 66-146). ai-parrot depends on sibling personal
repos (navigator, asyncdb, navconfig, querysource) whose knowledge is invisible to the wiki. Beyond
code, the same mechanism should let a user compose multiple "brains" — a lawyer with planes for
legislation, jurisprudence and own cases built via `wikitoolkit ingest`; an Obsidian vault built via
the existing vault-aware `wikitoolkit build` — and query all of them or a specific one.

`--store DIR` / `WIKI_STORE` already prove that reading a plane from another directory works, but
only one at a time, unnamed, and with ids (`file:<relpath>`, `dir:<relpath>`,
`repo_scan.py:249-256`) that collide across corpora.

### Goals

- **G1** Register named namespaces, each resolving to one `BaseWikiStore` of any backend
  (`sqlite` / `memory` / `arangodb`), from four entry kinds: `path` (another wiki project root),
  `store` (+`backend`), `database` (ArangoDB), `vault` (Obsidian vault).
- **G2** Configuration in **both** `.parrot/wiki.json` (`namespaces`) and a global user registry
  `~/.parrot/wikis.json`; repo entries override global entries on name clash. Entries enter
  either registry **only** through `wikitoolkit ns add` (U1).
- **G3** Stable qualified ids `ns::id` for foreign pages; **local ids stay unprefixed** (U3).
  Underlying stores never see the prefix.
- **G4** v1 routing: explicit (`--ns <name>` / `namespace` tool argument) and broadcast
  (`--ns all`, the default when ≥1 namespace resolves), with per-namespace min-max normalisation,
  weight and dedup before merging.
- **G5** Reads of foreign namespaces never mutate them (explicit read-only open for SQLite).
- **G6** Writes target exactly one namespace: local by default, or the single namespace named by
  `--ns <name>` on `remember` / `note` / `link`, opened read-write for that call (U2 — required).
- **G7** CLI, `AbstractTool` wrappers and the MCP server inherit namespaces through one injected
  `FederatedWikiStore`; no per-tool rewrite beyond an optional `namespace` argument.
- **G8** A vault namespace needs no new scanner or build path; its plane is resolved through
  `load_project_config(<vault>)` like `path` (Delta 2) and the two shared-store hazards
  (`_prune_removed` blast radius, `.parrot` self-ingestion) are fixed in this feature (D4.2/D4.4).
- **G9** An unbuilt or unreachable namespace is skipped with a note — never fails a broadcast.

### Non-Goals (explicitly out of scope)

- Automatic / LLM intent routing over namespace descriptions (`IntentRouterMixin`,
  `parrot/bots/mixins/intent_router.py:123`) — **v2 follow-up**, documented only.
- RRF or any ranking beyond per-namespace min-max + weight — v2.
- Cross-namespace edges; broadcast/multi-target writes; Obsidian write-back of `remember` output
  as vault notes — v2.
- Auto-promoting `vault_dir` to a namespace (D4.3) or `build` self-registering a project (U1).
- Changing `repo_scan.py` id builders, the SQLite schema, or backend internals.
- `MultiStoreSearchToolkit` (FEAT-379) and FEAT-449 GraphIndex namespaces — different layers;
  untouched. SQLite `ATTACH DATABASE` was rejected in the proposal (sqlite-only, no id fix).
- A `WIKI_NS` environment default — not in v1.

---

## 2. Architectural Design

### Overview

A new `FederatedWikiStore(BaseWikiStore)` composes `{name: BaseWikiStore}` plus the local plane.
Every read fans out with `asyncio.gather`, qualifies foreign ids with `<ns>::`, min-max-normalises
each namespace's `-bm25` scores (they are corpus-relative, `store.py:997-1043`), applies the
namespace weight, dedups and sorts. `get_page` / `neighbors` split the id on the first `::`,
route to that namespace, and re-qualify the ids they return. Write methods delegate to the local
plane; a qualified foreign id on a write path is a `ValueError` (writes to a foreign namespace go
through `--ns` in the CLI, which opens that one store directly — never through the federation).

Namespace **declaration** lives in `project.py` (dependency-light — stdlib + pydantic — because the
PreToolUse hook imports it, `project.py:1-40`): a `WikiNamespaceConfig` model, a `namespaces` map
on `WikiProjectConfig`, and loader/saver for the global registry. Namespace **resolution into
stores** lives in `federation.py` (it imports `store.py` / backends). `cli.py:_resolve_read_store`
returns the federated store whenever the merged map resolves to ≥1 namespace and `--store` was not
given; `mcp_server.py` performs the same injection, so `wiki_query` / `wiki_page` / `wiki_related`
/ `wiki_status` become namespace-aware through the store they already hold.

Resolution rules per kind (exactly one of `path` / `store` / `database` / `vault` per entry):

| kind | resolves to | read open |
|---|---|---|
| `path` | `load_project_config(path)` → `config.storage_path(path)` + `config.backend` (+ arango params from that config) | read-only |
| `store` | `create_wiki_store(store, backend=backend)` (default `sqlite`) | read-only |
| `database` | `ArangoDBWikiStore(resolve_arango_params(...), database=database)` with optional `credentials_env` prefix; eager `initialize()` under a timeout | server-side (no local mutation) |
| `vault` | **same as `path`** (Delta 2): `load_project_config(vault)`; defaults → `<vault>/.parrot/wiki`, sqlite. Registration additionally requires `(<vault>/.obsidian).is_dir()` | read-only |

Precedence is unchanged: `--store > --path project > WIKI_STORE env > auto-detected project`; `--ns`
only selects within the resolved namespace set. Reserved names: `all`, `local`; names match
`^[A-Za-z0-9][A-Za-z0-9_.:-]*$` and may contain single `:` (so `legal:civil` can mirror a
GraphIndex namespace) but never `::`.

### Component Diagram

```
.parrot/wiki.json (namespaces)  ~/.parrot/wikis.json
            │                           │
            └────── merge (repo wins) ──┘
                         │
            federation.resolve_namespaces(root, config)
                         │   opens each entry (read-only) → NamespaceHandle | NamespaceSkip
                         ▼
     ┌──────────── FederatedWikiStore(BaseWikiStore) ────────────┐
     │ local: SQLiteWikiStore (rw)          weight 1.0, no prefix │
     │ asyncdb:   SQLiteWikiStore(read_only=True)   "asyncdb::"   │
     │ legal:     ArangoDBWikiStore(database=...)   "legal::"     │
     │ notes:     SQLiteWikiStore(read_only=True)   "notes::"  (vault kind) │
     └───────┬───────────────────────┬───────────────────┬────────┘
             │                       │                   │
   cli.py query/page/related/   tools.py Wiki*Tool    mcp_server.py
   status (--ns) · ns add/list/  (namespace arg)      (same injection)
   remove · remember/note/link --ns <name>  ──► opens ONE store rw (bypasses federation)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BaseWikiStore` (`store.py:289`) | implements | `FederatedWikiStore` satisfies all 15 abstract methods |
| `create_wiki_store` (`store.py:1217`) | uses | opens each namespace; `SQLiteWikiStore` gains `read_only` |
| `cli.py:_resolve_read_store` (199-251) | modifies | returns federated store when namespaces resolve |
| `cli.py:_resolve_write_store` (1470-1495) | modifies | `--ns <name>` → single store, read-write |
| `cli.py:query/page/related/status` | extends | `--ns` option; status prints per-namespace block |
| `cli.py` `wiki` group (696) | extends | new `ns` sub-group (`list` / `add` / `remove`) |
| `cli.py:_prune_removed` (390-423) | modifies | `scope` argument (D4.4) |
| `search.py:_apply_weight` (497-530) | reuses semantics | min-max + weight; federation re-implements over plain dicts (search.py works on `WikiSearchResult`) |
| `context.py:_ID_PREFIX_RE` (30) | modifies | tolerate leading `<ns>::`; new id helpers |
| `project.py:WikiProjectConfig` (125) | extends | `namespaces` field + registry helpers |
| `tools.py:Wiki*Input` / `create_wiki_tools` (23-64, 399-428) | extends | optional `namespace` |
| `mcp_server.py:create_wiki_mcp_server` (66-146) | modifies | inject federated store at 105/108 |
| `vault_scan.py:VAULT_EXCLUDE_DIRS` (50-52) | modifies | add `.parrot` (D4.2) |
| `tools.py:VaultIngestTool` (288-368) | modifies | calls `_prune_removed(..., scope="root")` |
| `claude_code/hook.py` | unchanged | only `is_built` / `storage_path`; config keeps defaults |
| `toolkit.py:LLMWikiToolkit` | optional | may accept an injected federated store; not required for AC |

### Data Models

```python
# parrot/knowledge/wiki/project.py  (stdlib + pydantic only)
class WikiNamespaceConfig(BaseModel):
    """One federated namespace. Exactly one of path / store / database / vault is set."""
    path: Optional[str] = None        # another wiki project root (load_project_config there)
    store: Optional[str] = None       # pre-built store dir (wiki.db inside for sqlite)
    backend: Literal["sqlite", "memory", "arangodb"] = "sqlite"   # for `store`
    database: Optional[str] = None    # ArangoDB database name (backend forced to arangodb)
    credentials_env: str = "ARANGODB" # env prefix for `database`
    vault: Optional[str] = None       # Obsidian vault root (resolved like `path`, Delta 2)
    description: str = ""             # shown by `ns list`; reserved for v2 routing
    weight: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def kind(self) -> Literal["path", "store", "database", "vault"]: ...
    # validator: exactly one source field set; paths may be absolute or relative to the
    # declaring file's directory (repo root for wiki.json, ~/.parrot for wikis.json)

class WikiProjectConfig(BaseModel):
    ...existing fields...
    namespaces: dict[str, WikiNamespaceConfig] = Field(default_factory=dict)

# ~/.parrot/wikis.json
class GlobalWikiRegistry(BaseModel):
    version: int = 1
    namespaces: dict[str, WikiNamespaceConfig] = Field(default_factory=dict)

# parrot/knowledge/wiki/federation.py
class NamespaceSkip(BaseModel):
    name: str
    reason: Literal["unbuilt", "unreachable", "invalid"]
    detail: str
    hint: str = ""        # e.g. "wikitoolkit build --path /abs/vault"

@dataclass
class NamespaceHandle:
    name: str
    store: BaseWikiStore
    config: WikiNamespaceConfig
    origin: Literal["repo", "global"]
    storage_dir: Optional[Path]
    read_only: bool
```

### New Public Interfaces

```python
# parrot/knowledge/wiki/context.py
NS_SEPARATOR: str = "::"
def split_namespaced_id(page_id: str) -> tuple[Optional[str], str]: ...
def qualify_id(namespace: Optional[str], page_id: str) -> str: ...   # None/local → unchanged

# parrot/knowledge/wiki/project.py
GLOBAL_REGISTRY_PATH: Path   # Path("~/.parrot/wikis.json").expanduser(), overridable via
                             # PARROT_HOME env for tests
def load_global_registry(path: Optional[Path] = None) -> GlobalWikiRegistry: ...
def save_global_registry(registry: GlobalWikiRegistry, path: Optional[Path] = None) -> Path: ...
def merge_namespaces(repo: dict[str, WikiNamespaceConfig],
                     global_: dict[str, WikiNamespaceConfig]) -> dict[str, tuple[WikiNamespaceConfig, str]]:
    """name -> (config, origin); repo entries win on clash."""

# parrot/knowledge/wiki/federation.py
def resolve_namespaces(root: Path, config: WikiProjectConfig, *,
                       only: Optional[set[str]] = None,
                       registry_path: Optional[Path] = None,
                       arango_timeout: float = 5.0,
                       ) -> tuple[list[NamespaceHandle], list[NamespaceSkip]]: ...

def open_namespace_store(name: str, cfg: WikiNamespaceConfig, *, base_dir: Path,
                         read_only: bool = True) -> BaseWikiStore: ...
    """Single-namespace open; read_only=False is the `--ns <name>` write path (U2)."""

class FederatedWikiStore(BaseWikiStore):
    def __init__(self, local: BaseWikiStore, local_name: str,
                 handles: list[NamespaceHandle], skipped: list[NamespaceSkip]) -> None: ...
    local_name: str
    namespaces: dict[str, NamespaceHandle]
    skipped: list[NamespaceSkip]
    def scoped(self, selector: Optional[str]) -> BaseWikiStore:
        """None/'all' → self; 'local' → local store; a name → that handle's store
        wrapped so its ids are qualified; unknown → KeyError."""
    # reads (fan-out, qualified ids, merged ranking)
    async def search_fts(self, query, category=None, limit=10) -> list[dict]
    async def search_vector(self, embedding, limit=10) -> list[dict]
    async def list_pages(self, category=None, limit=100, origin=None) -> list[dict]
    async def get_page(self, concept_id, include_body=True) -> Optional[dict]
    async def neighbors(self, concept_id, rel=None, direction="both") -> list[dict]
    async def stats(self) -> dict      # local stats + {"namespaces": {...}, "skipped": [...]}
    # writes → local only; qualified foreign id → ValueError
    async def upsert_pages / add_edges / replace_source_slice / delete_page / upsert_embedding
    # lint / dump → local only (export is a local-plane operation)
    async def dump_pages / dump_edges / orphan_sources / broken_edges / missing_bodies / rebuild_from_tree

# parrot/knowledge/wiki/store.py
class SQLiteWikiStore(BaseWikiStore):
    def __init__(self, db_path, wiki_name="", *, read_only: bool = False) -> None: ...
    # read_only=True: no mkdir, no schema replay, no _migrate; _connect() goes straight to
    # _connect_readonly(); any write method raises PermissionError("read-only namespace")
```

CLI surface (exact):

```
wikitoolkit query  "<q>" [--ns NAME[,NAME...]|all|local]
wikitoolkit page   <id>  [--ns ...]        # id may already carry ns::
wikitoolkit related <id> [--ns ...]
wikitoolkit status [--ns ...]              # per-namespace block; --json adds "namespaces"
wikitoolkit remember/note/link ... --ns NAME   # exactly one name; 'all' rejected
wikitoolkit ns list [--json]
wikitoolkit ns add NAME (--path P | --store S [--backend B] | --database D [--credentials-env X] | --vault V)
                        [--description TEXT] [--weight W] [--global]
wikitoolkit ns remove NAME [--global]
```

MCP / tools: `WikiQueryInput.namespace: str | None`, `WikiPageInput.namespace`,
`WikiRelatedInput.namespace` (`None` → default/broadcast, a name, `"all"`, `"local"`);
`wiki_status` result gains `namespaces` / `skipped`.

---

## 3. Module Breakdown

### Module 1: Namespace configuration & global registry
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
- **Responsibility**: `WikiNamespaceConfig` (+ `kind`, exactly-one validator, name validation),
  `WikiProjectConfig.namespaces`, `GlobalWikiRegistry`, `GLOBAL_REGISTRY_PATH` (honours a
  `PARROT_HOME` env override), `load_global_registry` / `save_global_registry` (atomic write,
  `0o600`), `merge_namespaces`. Must stay stdlib + pydantic (hook import path).
- **Depends on**: nothing new.

### Module 2: Id helpers + read-only SQLite open
- **Paths**: `context.py`, `store.py`
- **Responsibility**: `NS_SEPARATOR`, `split_namespaced_id`, `qualify_id`; `_ID_PREFIX_RE` made
  tolerant of a leading `<ns>::` so stub title elision (`context.py:124`) still works for
  `asyncdb::file:x`. `SQLiteWikiStore(read_only=True)`: `_connect()` routes to
  `_connect_readonly()` without `mkdir` / schema replay / `_migrate`; write methods raise
  `PermissionError`. Unbuilt plane (`wiki.db` absent) in read-only mode raises
  `FileNotFoundError` at open so the resolver can classify it as `unbuilt`.
- **Depends on**: nothing new.

### Module 3: `FederatedWikiStore` + resolver
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` (new)
- **Responsibility**: `resolve_namespaces`, `open_namespace_store`, `NamespaceHandle`,
  `NamespaceSkip`, `FederatedWikiStore` per §2. Merge algorithm: per namespace `rows →
  min-max(score) × weight`; local rows unprefixed, foreign rows `concept_id = qualify_id(ns, cid)`
  and `node_id` likewise; `source_id` untouched; every row gains `"namespace": <name>`; dedup by
  qualified id; sort desc; cut to `limit`. Per-namespace fan-out uses `limit` each. Exceptions
  from one namespace are logged and turned into a `NamespaceSkip("unreachable")` for this call —
  never propagated.
- **Depends on**: Module 1, Module 2.

### Module 4: CLI — `--ns`, `ns` group, write routing
- **Path**: `cli.py`
- **Responsibility**: `--ns` option shared by `query` / `page` / `related` / `status`;
  `_resolve_read_store` returns `FederatedWikiStore.scoped(ns)` when ≥1 namespace resolves and
  `--store` is absent (existing precedence preserved; `--store` never federates);
  `_resolve_write_store(..., ns=None)` — with `ns` it calls `open_namespace_store(read_only=False)`
  and returns `(store, storage_dir, None, None)`; `all`/`local` semantics; `status` prints a
  `Namespaces:` block (`name  kind  backend  pages  status  origin`) and lists skips with hints;
  `ns list|add|remove`; `query` output prints skipped namespaces as a trailing note. Stub lines
  already show the qualified id, which carries the namespace.
- **Depends on**: Module 3.

### Module 5: Tools + MCP injection
- **Paths**: `tools.py`, `mcp_server.py`
- **Responsibility**: optional `namespace` field on the three read inputs; `_execute` calls
  `self._store.scoped(namespace)` when the store is federated (duck-typed `hasattr(store,
  "scoped")` so the mock-store tests keep passing); `WikiStatusTool` passes through the federated
  `stats`; `create_wiki_mcp_server` builds the federated store via `resolve_namespaces` and injects
  it at the existing `create_wiki_tools` call (`mcp_server.py:108`).
- **Depends on**: Module 3.

### Module 6: Vault hazards (D4.2 / D4.4)
- **Paths**: `vault_scan.py`, `cli.py:_prune_removed`, `tools.py:VaultIngestTool`, `cli.py:build`
- **Responsibility**: add `".parrot"` to `VAULT_EXCLUDE_DIRS` (mirrors `repo_scan.DEFAULT_EXCLUDE_DIRS`
  which already prunes `.parrot` by bare name, `repo_scan.py:85-89`). `_prune_removed(store,
  sources, root, scan, *, scope: Literal["plane", "root"] = "plane")`: `build` keeps `"plane"`
  (the whole plane *is* this corpus); `VaultIngestTool` passes `"root"`: only sources whose
  `source_uri` is under `root` are eligible for removal, `file:` pages are removed only through
  those sources' slices, and a `dir:` page is removed only when no surviving page id lies under
  that directory path. `ns add --vault` validates `.obsidian/` and prints the
  `wikitoolkit build --path <vault>` hint when the plane is unbuilt.
- **Depends on**: Module 1 (for `ns add --vault` only); otherwise independent.

### Module 7: Docs
- **Paths**: `documentation/parrot-wiki-cli.md` (new "Namespaces" section after "Querying an
  external / pre-built store", lines 424-451), `docs/wiki-claude-code.md` (note on `ns::` ids in
  query output and on `wiki_query.namespace`), `CLAUDE.md` wiki section (one line: ids may carry
  `ns::`).
- **Depends on**: Modules 3-6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_namespace_config_exactly_one_source` | 1 | zero or two of path/store/database/vault → `ValidationError` |
| `test_namespace_name_validation` | 1 | rejects `all`, `local`, names with `::`, empty; accepts `legal:civil` |
| `test_merge_namespaces_repo_wins` | 1 | same name in both registries → repo entry, origin `"repo"` |
| `test_global_registry_roundtrip_and_missing` | 1 | save/load under `PARROT_HOME`; absent file → empty registry |
| `test_wiki_project_config_defaults_keep_hook_compat` | 1 | loading a pre-existing `wiki.json` without `namespaces` still validates |
| `test_split_and_qualify_id` | 2 | `asyncdb::file:a/b.py` ↔ (`asyncdb`, `file:a/b.py`); inner colons preserved; `file:x` → (None, `file:x`) |
| `test_id_prefix_re_skips_namespace` | 2 | stub title elision works for qualified ids (`pack_results`) |
| `test_sqlite_read_only_never_migrates` | 2 | open a plane with an older `meta` version read-only → no schema change, no `-wal` growth, `upsert_pages` → `PermissionError` |
| `test_sqlite_read_only_unbuilt_raises` | 2 | missing `wiki.db` with `read_only=True` → `FileNotFoundError` |
| `test_resolve_namespaces_kinds` | 3 | path / store / vault entries open; `database` entry uses `resolve_arango_params` with `credentials_env` (mocked) |
| `test_resolve_namespaces_skips_unbuilt` | 3 | unbuilt sqlite namespace → `NamespaceSkip(reason="unbuilt", hint="wikitoolkit build --path ...")` |
| `test_federated_search_merges_and_qualifies` | 3 | two temp planes with colliding `file:README.md`; both returned, foreign one qualified, local unprefixed, `namespace` key present |
| `test_federated_search_minmax_per_namespace` | 3 | a 5-page plane does not dominate a 500-page plane; weights applied |
| `test_federated_get_page_and_neighbors_route` | 3 | `ns::id` routes to the right store and neighbour ids come back qualified; unknown ns → `None` / `[]` |
| `test_federated_writes_local_only` | 3 | `upsert_pages` lands in local; `delete_page("asyncdb::file:x")` → `ValueError` |
| `test_federated_namespace_failure_is_skipped` | 3 | a handle whose `search_fts` raises → results from the others, skip recorded |
| `test_federated_stats_shape` | 3 | local stats keys intact (`pages`, `edges`, …) + `namespaces` + `skipped` |
| `test_prune_removed_root_scope` | 6 | vault ingest into a plane holding repo pages removes nothing outside `root`; `dir:` survives while children exist |
| `test_vault_exclude_parrot` | 6 | a vault with `<vault>/.parrot/wiki/log.md` is scanned without that file |

### Integration Tests (CliRunner, `tests/knowledge/wiki/test_cli.py` harness: `repo` + `runner` fixtures, `_store_dir`)
| Test | Description |
|---|---|
| `test_ns_add_list_remove_repo_and_global` | `ns add` writes `wiki.json` / `wikis.json` (`--global`, `PARROT_HOME` tmp); `ns list --json` shows origin/kind/built; `ns remove` |
| `test_query_broadcast_default_and_explicit` | two built temp repos; `query` without `--ns` returns both (foreign qualified); `--ns other` only that one; `--ns local` only local; `--ns nope` exits ≠0 |
| `test_page_related_with_qualified_id` | `page other::file:pkg/store.py` and `related other::dir:pkg` succeed |
| `test_store_flag_never_federates` | `--store DIR` with namespaces configured → single store, no qualified ids |
| `test_explicit_path_beats_env_still_holds` | existing precedence test extended with namespaces configured |
| `test_remember_ns_writes_foreign_only` | `remember --ns other` lands in the other plane, not local; `--ns all` exits ≠0 |
| `test_status_lists_namespaces_and_skips` | unbuilt namespace shown as `unbuilt` with build hint; exit 0 |
| `test_mcp_server_injects_federated_store` | `create_wiki_mcp_server(tmp_root)` with a namespace configured → `wiki_query` tool result contains a qualified id (pattern of `test_mcp_server_vault.py`) |
| `test_wiki_tools_namespace_argument` | `WikiQueryTool(federated)._execute(question, namespace="other")` scopes; with `AsyncMock` store (no `scoped`) behaviour unchanged |
| `test_vault_namespace_end_to_end` | temp vault (`.obsidian/`, two notes with `[[links]]`) → `build --path vault` → `ns add notes --vault` → `query` returns `notes::file:...` with `category=document` |

### Test Data / Fixtures
```python
@pytest.fixture
def two_repos(tmp_path, runner):
    """Build two minimal wiki projects (reuse test_cli.PY_STORE/PY_UTIL) and return (local, other)."""

@pytest.fixture
def parrot_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    return tmp_path / "home"

@pytest.fixture
def vault(tmp_path):
    """<tmp>/vault/.obsidian + notes A.md ('[[B]]'), B.md ('#tag'); returns the vault path."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `pytest tests/knowledge/wiki -v` passes, including all tests in §4 and the pre-existing
  `--store` / `WIKI_STORE` precedence tests unchanged.
- [ ] `WikiProjectConfig` gains `namespaces`; every existing `.parrot/wiki.json` (no key) still
  loads; `wikitoolkit claude-hook` import path adds no new third-party import (verified by
  `python -X importtime -c "import parrot.knowledge.wiki.project"` showing no `store`/`search`).
- [ ] `~/.parrot/wikis.json` is created only by `ns add --global`; `build` never writes it (U1).
- [ ] `ns add` is the only writer of `namespaces` in `wiki.json`; it validates the entry kind,
  resolves relative paths, rejects reserved/invalid names and duplicate names in the same registry.
- [ ] With ≥1 resolvable namespace and no `--ns`, `query` broadcasts; `--ns <name>` narrows;
  `--ns all` / `--ns local` honoured; unknown name → exit ≠0 with the known names listed.
- [ ] Foreign results carry `ns::` on `concept_id` and `node_id` and a `namespace` key; local
  results are unprefixed (U3); `page` / `related` accept qualified ids and return qualified
  neighbour ids for foreign namespaces.
- [ ] A foreign SQLite namespace is opened with `read_only=True`: no `_migrate`, no `mkdir`, no
  sidecar creation on a quiescent plane; proven by the read-only tests.
- [ ] `remember` / `note` / `link --ns <name>` write into that namespace only (opened read-write),
  default writes go local, `--ns all` is rejected (U2).
- [ ] Unbuilt / unreachable namespaces are skipped with a note + hint; `query` and `status` exit 0
  and still return the other namespaces' results (G9).
- [ ] `--store DIR` never federates; precedence `--store > --path > WIKI_STORE > project` unchanged.
- [ ] `wiki_query` / `wiki_page` / `wiki_related` accept `namespace`; `wikitoolkit mcp` serves the
  federated store; `wiki_status` exposes `namespaces` and `skipped`.
- [ ] `vault` kind resolves through `load_project_config(<vault>)` (Delta 2); `ns add --vault`
  requires `.obsidian/`; `VAULT_EXCLUDE_DIRS` contains `.parrot`; `VaultIngestTool` prunes with
  `scope="root"`; `build` behaviour unchanged (`scope="plane"`).
- [ ] Scores in broadcast output are min-max-normalised per namespace and weighted before merge.
- [ ] Docs updated (§3 Module 7); `documentation/parrot-wiki-cli.md` documents every `ns` command
  and the `--ns` option with the precedence table amended.
- [ ] No breaking change to `BaseWikiStore`, `create_wiki_store`, `create_wiki_tools`,
  `create_wiki_mcp_server` signatures (only additive optional parameters).
- [ ] v2 follow-ups (intent router, RRF, cross-namespace edges, multi-target writes, Obsidian
  write-back) are listed in the docs "Namespaces" section as not implemented.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against `dev` @ `141b66f87` (2026-08-23).
> `cli.py` is a HOT file (2694 lines) also being edited by FEAT-451 in the `ingest` region
> (2093-2544) — do not touch that region. Paths below are under
> `packages/ai-parrot/src/parrot/knowledge/wiki/` unless absolute.

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord, create_wiki_store, estimate_tokens  # store.py:289,441,215,1217,163
from parrot.knowledge.wiki.file_store import InMemoryWikiStore                    # file_store.py:71
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore                  # arango_store.py (class), __init__ at 163
from parrot.knowledge.wiki.project import (                                        # project.py
    PARROT_DIR, CONFIG_FILENAME, WikiProjectConfig, WikiConfigError, ClaudeIntegrationConfig,
    config_path, find_project_root, load_project_config, save_project_config,
    resolve_arango_params, resolve_vault_dir, wiki_write_lock,
)                                                                                  # 125,319,110,291,296,323,350,217,245,47
from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS, PackedContext, pack_results, truncate_to_tokens  # context.py:40,131
from parrot.knowledge.wiki.sources import SourceCollectionManager                 # sources.py:57
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper                       # bookkeeper.py
from parrot.knowledge.wiki.vault_scan import VAULT_EXCLUDE_DIRS, is_obsidian_vault, scan_vault  # vault_scan.py:50,55,111
from parrot.knowledge.wiki.repo_scan import RepoScan, file_concept_id, dir_concept_id, scan_repository  # repo_scan.py:249,254
from parrot.knowledge.wiki.tools import (WikiQueryTool, WikiPageTool, WikiRelatedTool, WikiRememberTool,
    WikiNoteTool, WikiStatusTool, VaultIngestTool, create_wiki_tools)              # tools.py:67,90,115,137,214,272,288,399
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server               # mcp_server.py:66
from parrot.tools.abstract import AbstractTool, ToolResult                        # parrot/tools/abstract.py:235,200
from parrot.mcp.local_server import StdioMCPServer                                # lazy import inside mcp_server.py (stdout redirect!)
from parrot.mcp.server_base import LocalServerConfig                              # same
import click                                                                       # cli.py
```

### Existing Class Signatures
```python
# store.py
class BaseWikiStore(ABC):                                                   # 289
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int
    async def add_edges(self, edges: list[tuple]) -> int
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord],
                                   edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]   # 314
    async def delete_page(self, concept_id: str) -> bool
    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]      # 331
    async def list_pages(self, category: Optional[str] = None, limit: int = 100,
                         origin: Optional[list[str]] = None) -> list[dict[str, Any]]                      # 336
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict] # 344
    async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict]                  # 349
    async def neighbors(self, concept_id: str, rel: Optional[str] = None,
                        direction: str = "both") -> list[dict[str, Any]]                                 # 354
    async def dump_pages(self) -> list[dict]; async def dump_edges(self) -> list[dict]                   # 362,365
    async def stats(self) -> dict[str, Any]                                                              # 368
    async def orphan_sources(self) -> list[str]; async def broken_edges(self) -> list[dict]
    async def missing_bodies(self) -> list[str]                                                          # 372-378
    async def rebuild_from_tree(self, tree: dict, content_loader=None, source_id=None) -> dict           # 382 (concrete, not abstract)

class SQLiteWikiStore(BaseWikiStore):                                        # 441
    def __init__(self, db_path: str | Path, wiki_name: str = "") -> None     # 485 — mkdir parent (488), tolerant on EROFS/EACCES/EPERM when file exists
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]          # 514 — write-first; schema replay; self._migrate(conn) at 565; falls to _connect_readonly only on _is_readonly_env_error (573-576)
    async def _connect_readonly(self)                                        # 580 — mode=ro → immutable=1 ladder
    def _log_read_only_once(self) -> None                                    # 656
    async def search_fts(...)  # 997 — returns dicts: concept_id,node_id,title,category,summary,source_id,token_count,score(-bm25, unnormalised); excludes category 'archive' unless asked
    async def get_page(...)    # 926 — accepts concept_id or node_id
    async def neighbors(...)   # 1087 — dicts: concept_id, rel, direction ('out'|'in'), + title/category when the neighbour is a page
    async def stats(self)      # 1152 — {"pages","edges","sources","embeddings","total_tokens","categories"}

class WikiPageRecord(BaseModel):  # 215 — concept_id, node_id, title, category='concept', summary, body, source_id, token_count, origin='ingest', asserted_by

def create_wiki_store(storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs) -> BaseWikiStore  # 1217
    # sqlite → SQLiteWikiStore(storage_dir / "wiki.db"); memory → InMemoryWikiStore(storage_dir / "pages");
    # arangodb → ArangoDBWikiStore(arango_params=kwargs["arango_params"], database=kwargs.get("database",""), text_analyzer=...)

# file_store.py
class InMemoryWikiStore(BaseWikiStore):  def __init__(self, bundle_dir: str | Path, wiki_name: str = "")   # 71, 86

# arango_store.py
class ArangoDBWikiStore(BaseWikiStore):
    def __init__(self, arango_params: dict[str, Any], database: str = "", wiki_name: str = "", text_analyzer: str = "text_en")  # 163; self._database = database or f"wiki_{wiki_name or 'codebase'}" (172)
    async def initialize(self) -> None                                        # 230 (idempotent; connects)

# project.py  (stdlib + pydantic only — hook import path)
PARROT_DIR = ".parrot"; CONFIG_FILENAME = "wiki.json"; LOCK_FILENAME = "wiki.lock"
class ClaudeIntegrationConfig(BaseModel): nudge_cooldown_seconds: int = 60; nudge_tools: list[str]   # 110
class WikiProjectConfig(BaseModel):                                          # 125
    wiki_name: str = "codebase"; storage_dir: str = ".parrot/wiki"; backend: Literal["sqlite","memory","arangodb"] = "sqlite"
    include_suffixes: list[str]; exclude_dirs: list[str]; body_max_chars: int = 16_000; max_file_kb: int = 512
    claude: ClaudeIntegrationConfig; sync_graph: bool = False; arango_database: Optional[str]; arango_credentials_env: str = "ARANGODB"
    arango_text_analyzer: str = "text_en"; vault_dir: Optional[str] = None
    def graph_path(self, root) -> Path (186); def storage_path(self, root) -> Path (190; absolute-aware)
    def db_path(self, root) -> Path (195); def is_built(self, root) -> bool (199; arangodb → True)
def resolve_arango_params(config: WikiProjectConfig) -> dict   # 217 — host/port/protocol/username/password/database from f"{prefix}_*" env
def resolve_vault_dir(root, config, override=None) -> Optional[Path]   # 245 — imports vault_scan lazily (heavy)
def config_path(root: Path) -> Path                            # 291
def find_project_root(start: Optional[Path] = None) -> Optional[Path]   # 296 — nearest .parrot/wiki.json, else nearest .git
def load_project_config(root: Path) -> WikiProjectConfig       # 323 — missing file → WikiProjectConfig(wiki_name=root.name or "codebase") (347); invalid → WikiConfigError
def save_project_config(root: Path, config: WikiProjectConfig) -> Path   # 350 — json.dumps(config.model_dump(mode="json"), indent=2)
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]   # 47 — flock beside the store

# context.py
_ID_PREFIX_RE = re.compile(r"^(?:file|dir|mod|pkg|doc|func|class|concept|page):")   # 30; used at 124 for title elision
class PackedContext(BaseModel): text, stubs, tokens_used, results_packed, total_available, truncated   # 40
def pack_results(results: Iterable[Any], budget_tokens: int = DEFAULT_BUDGET_TOKENS) -> PackedContext  # 131 — id from concept_id|node_id|page_id (107), dedups ids

# search.py (reference semantics only — operates on WikiSearchResult, not dicts)
class WikiCombinedSearch:
    def _merge_groups(self, groups: list[tuple[list[WikiSearchResult], float]]) -> list[WikiSearchResult]   # 473 — dedup by node_id keep max
    def _apply_weight(self, results, weight) -> list[WikiSearchResult]                                       # 497 — min-max, all-equal → 1.0, clip [0,1]
    def _store_row_to_wiki(self, row, source) -> WikiSearchResult                                            # 249 — node_id = concept_id or node_id

# cli.py
path_option = click.option("--path", "path_", ...)                                      # ~82
def _resolve_project(path: str | None) -> tuple[Path, WikiProjectConfig]                # 87 — ClickException when no project
def _require_built(root, config) -> BaseWikiStore                                       # 108
def _open_store(root, config) -> BaseWikiStore                                          # 118 — mkdir storage (132) for non-arango!
def _open_sources(root, config, store=None) -> SourceCollectionManager                  # 138 — sqlite: SourceCollectionManager(storage/"sources", db_path=storage/"wiki.db")
def _normalize_scores(rows: list[dict]) -> list[dict]                                   # 164 — min-max over one result list
def _run(coro) -> Any                                                                   # 176 — asyncio.run
def _env_setting(name: str) -> str | None                                               # 181 — navconfig then os.environ
def _resolve_read_store(path_, store_opt, backend_opt) -> BaseWikiStore                 # 199-251 — precedence --store > --path > WIKI_STORE > project; arangodb eager initialize()
def _store_options(func)                                                                # 255 — adds --backend, --store
async def _ingest_files(store, sources, root, scan, force) -> dict                      # 327
async def _prune_removed(store, sources, root: Path, scan) -> int                       # 390-423 — GLOBAL over the store (list_pages(limit=1_000_000); deletes file:/dir: not in scan)
@click.group(name="wiki") def wiki(ctx, verbose)                                        # 696/704
@wiki.command() def mcp()                                                               # 716 — lazy-imports mcp_server.main
build(...)  # 730-; vault auto-detect 810-815 (scan_vault(root, config.body_max_chars, config.max_file_kb*1024)); scan_repository(..., exclude_dirs=config.exclude_dirs) 823-826; _prune_removed at 842
query(question, path_, top_k, budget, category, store_opt, backend_opt, as_table, show_body, as_json)   # 1075-1158 — store.search_fts → _normalize_scores → pack_results
page(page_id, path_, max_tokens, store_opt, backend_opt, as_json)                       # 1160-1200
related(page_id, path_, rel, direction, store_opt, backend_opt, as_json)                # 1203-1239
status(path_, as_json)                                                                  # 1241-1288 — _open_store + _open_sources + store.stats()
def _resolve_write_store(path_, store_opt, backend_opt) -> tuple[BaseWikiStore, Path, Path | None, WikiProjectConfig | None]   # 1470-1495
remember(...) 1647/1676; note(...) 1802/1809; link(...) 1866/1874; memories 1917; audit 1954; ground 2013; ingest 2280 (FEAT-451 region); claude-hook 2645
def _register_agent_command(name: str) -> None   # 2674 — pattern for adding commands dynamically to `wiki`

# tools.py
class WikiQueryInput(BaseModel): question: str; budget_tokens: int            # 23
class WikiPageInput(BaseModel): page_id: str                                  # 28
class WikiRelatedInput(BaseModel): page_id: str                               # 32
class WikiStatusInput(BaseModel): pass                                        # 63
class WikiQueryTool(AbstractTool): name="wiki_query"; args_schema=WikiQueryInput
    def __init__(self, store: BaseWikiStore)                                  # 80 — super().__init__(name=..., description=...)
    async def _execute(self, question: str, budget_tokens: int = DEFAULT_BUDGET_TOKENS) -> str   # 84 — search_fts → pack_results(...).text
class WikiPageTool:    async def _execute(self, page_id: str) -> ToolResult  # 105 — get_page(include_body=True); ToolResult(result=page)
class WikiRelatedTool: async def _execute(self, page_id: str) -> ToolResult  # 130 — neighbors(page_id); ToolResult(result={"neighbors": ...})
class WikiRememberTool: def __init__(self, store, storage_dir: Path | None = None)   # 148; _execute(fact, category="note", title=None, link_page_id=None, rel="references") 153
class WikiStatusTool:  async def _execute(self) -> ToolResult                # 283 — ToolResult(result=await store.stats())
class VaultIngestTool: def __init__(self, store, root: Path, config: WikiProjectConfig)   # 300; _execute(vault_path=None, force=False) 311; calls scan_vault (355), _open_sources (361), _ingest_files (362), _prune_removed(self._store, sources, vault, scan) (367)
def create_wiki_tools(store: BaseWikiStore, root: Path | None = None, config: WikiProjectConfig | None = None) -> list[AbstractTool]   # 399

# parrot/tools/abstract.py
class ToolResult(BaseModel): success: bool = True; status: str = "success"; result: Any; error: Optional[str]; metadata: dict   # 200
class AbstractTool(EventEmitterMixin, ABC): name: str; description: str; args_schema: Type[BaseModel]   # 235

# mcp_server.py
def create_wiki_mcp_server(root: Path) -> StdioMCPServer   # 66 — config=load_project_config(root); store=create_wiki_store(...) at 95 (arango) / 105; tools=create_wiki_tools(store, root=root, config=config) 108; vault tools 111-144; server.register_tools(tools) 142
def main() -> None                                         # 148 — find_project_root(_INVOCATION_CWD); is_built check; asyncio.run(server.start())
# parrot/mcp/server_base.py: def register_tools(self, tools: list[AbstractTool])   # 45

# vault_scan.py
VAULT_EXCLUDE_DIRS = frozenset({".obsidian", ".trash", ".git", ".hg", ".svn"})   # 50-52 — NO ".parrot"
def is_obsidian_vault(root: Path) -> bool                                          # 55 — (root/".obsidian").is_dir(); module imports parrot.interfaces.obsidian.* (33-35) → do NOT import from project.py
def scan_vault(root: Path, body_max_chars: int = ..., max_file_bytes: int = ...) -> tuple[RepoScan, VaultScanStats]   # 111 — rglob *.md, filters only VAULT_EXCLUDE_DIRS (137); no exclude arg
# notes category="document" (159); edges "embeds"/"references" (179); tag pages category="tag" (203); ("tagged") edges (211)

# repo_scan.py
DEFAULT_EXCLUDE_DIRS includes ".parrot", ".claude", ".worktrees", ".graphindex"   # 85-89; pruned by bare name at any depth (239)
def file_concept_id(rel_path) -> f"file:{...}"; def dir_concept_id(rel_path) -> f"dir:{... or '.'}"   # 249-256

# sources.py
class SourceCollectionManager:  def __init__(self, sources_dir: Path, db_path: Optional[Path] = None, backend: Literal["sqlite","json","arangodb"] = "sqlite", arango_db=None, arango_store=None)   # 57/82
    def list_sources(self) -> list[SourceManifestEntry] (213); def get_source(id) (230); def is_stale(id) -> bool (250); def remove_source(id) -> bool (428)
    # SourceManifestEntry has .source_id and .source_uri (absolute path string) — used by _prune_removed (cli.py:404-411)

# bookkeeper.py
class WikiBookkeeper: INDEX_FILENAME="index.md" (44); LOG_FILENAME="log.md" (45)
    def write_index(self, wiki_dir: Path, tree=None, tree_name="wiki", sources=None, categories=None, ...)   # 122 — writes wiki_dir/index.md (142)
    def log_operation(self, wiki_dir: Path, operation: str, details: str, timestamp=None) -> None         # 175 — appends wiki_dir/log.md (201)

# tests (patterns to extend)
tests/knowledge/wiki/test_cli.py: fixtures `repo` (42, builds a temp repo with PY_STORE/PY_UTIL), `runner` (55, CliRunner); `--store` tests 197-245; precedence test 212-214
packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py: `mock_store = AsyncMock()` fixture (17) — tools must keep working with a plain AsyncMock store
packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py: `create_wiki_mcp_server(tmp_path)` pattern (25-44)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FederatedWikiStore` | `BaseWikiStore` ABC | subclass, all abstract methods | `store.py:289-378` |
| `resolve_namespaces` | `load_project_config`, `create_wiki_store`, `resolve_arango_params` | function calls | `project.py:323,217`; `store.py:1217` |
| `open_namespace_store(read_only=True)` | `SQLiteWikiStore(read_only=...)` (new kwarg) | constructor | `store.py:485` |
| `cli._resolve_read_store` | `FederatedWikiStore.scoped(ns)` | return value | `cli.py:199-251` |
| `cli._resolve_write_store(ns=...)` | `open_namespace_store(read_only=False)` | function call | `cli.py:1470-1495` |
| `cli.status` | `FederatedWikiStore.stats()["namespaces"]` | dict key | `cli.py:1260` |
| `ns add/remove` | `save_project_config` / `save_global_registry` | file writes | `project.py:350` |
| `Wiki*Tool._execute(namespace=...)` | `store.scoped(namespace)` (duck-typed) | method call | `tools.py:84,105,130` |
| `create_wiki_mcp_server` | `resolve_namespaces` → `FederatedWikiStore` | replaces store at line 105, passed at 108 | `mcp_server.py:105-108` |
| `VaultIngestTool._execute` | `_prune_removed(..., scope="root")` | kwarg | `tools.py:367` |
| `build` | `_prune_removed(..., scope="plane")` (default) | unchanged call | `cli.py:842` |
| `scan_vault` | `VAULT_EXCLUDE_DIRS` (+ `.parrot`) | constant | `vault_scan.py:50-52,137` |
| `pack_results` stub lines | `_ID_PREFIX_RE` (ns-aware) | regex | `context.py:30,124` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot/knowledge/wiki/federation.py`~~, ~~`FederatedWikiStore`~~, ~~`NamespaceHandle`~~,
  ~~`NamespaceSkip`~~, ~~`resolve_namespaces`~~, ~~`open_namespace_store`~~ — to be created (Module 3).
- ~~`WikiNamespaceConfig`~~, ~~`GlobalWikiRegistry`~~, ~~`WikiProjectConfig.namespaces`~~,
  ~~`load_global_registry`~~, ~~`GLOBAL_REGISTRY_PATH`~~ — to be created (Module 1). Nothing in the
  wiki package reads `~/.parrot` today (only `expanduser()` on `vault_dir`, `project.py:270-274`).
- ~~`SQLiteWikiStore(read_only=True)`~~ — no such kwarg today (`store.py:485`); `_warned_read_only`
  / `_log_read_only_once` (500, 656) are the *fallback* path, not an opt-in.
- ~~`BaseWikiStore.search()`~~ — the lexical entry point is `search_fts`; `search()` exists only on
  `WikiCombinedSearch` (search.py) and `LLMWikiToolkit` (toolkit.py:991).
- ~~`context.split_namespaced_id` / `qualify_id` / `NS_SEPARATOR`~~ — to be created (Module 2).
- ~~`wikitoolkit ns ...`~~ command group, ~~`--ns`~~ option, ~~`WikiQueryInput.namespace`~~ — to be created.
- ~~`_prune_removed(..., scope=...)`~~ — current signature is `(store, sources, root, scan)` (cli.py:390).
- ~~`scan_vault(exclude_dirs=...)`~~ — no such parameter (vault_scan.py:111-115).
- ~~`KnowledgeRouter`~~ (cited by FEAT-449 design text) — not in source anywhere.
- ~~`WikiStore`~~ as a concrete class — it is an alias export in `parrot.knowledge.wiki.__init__`
  (`_EXPORT_MODULES`), use `SQLiteWikiStore` / `BaseWikiStore` explicitly.
- ~~`MultiStoreSearchToolkit` namespaces~~ — FEAT-379 is an agent-level origin toolkit
  (`packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:39`); not touched here.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Keep `project.py` importable by the hook with **no** `store`/`search`/`vault_scan` imports
  (`project.py:1-40`; `resolve_vault_dir` shows the lazy-import discipline at 245-289). The
  `.obsidian/` probe in `ns add --vault` is an inlined `Path.is_dir()` check, not
  `vault_scan.is_obsidian_vault`.
- `_resolve_read_store` precedence + `ClickException` messages (`cli.py:199-251`); `--store`
  targets keep `root`/`config = None` (`cli.py:1493`).
- Per-group min-max + weight + dedup exactly as `search.py:497-530` / `cli.py:164` (all-equal
  scores → 1.0; clip to [0, 1]); the federation operates on the plain dicts `search_fts` returns.
- Graceful per-origin degradation (log + note, never fail the whole search) — the discipline of
  `MultiStoreSearchToolkit` (`return_exceptions=True` style) and of the ArangoDB eager
  `initialize()` error handling in `_resolve_read_store` (`cli.py:214-224`).
- Lazy, stdout-redirected imports in `mcp_server.py` (`contextlib.redirect_stdout(sys.stderr)`):
  namespace resolution must run inside the same discipline — nothing may print to stdout before
  the JSON-RPC loop.
- Atomic JSON writes for registries (`write_text` of `json.dumps(model_dump(mode="json"))`,
  `project.py:362-363`); `~/.parrot/wikis.json` created with mode `0o600`.
- Google-style docstrings, strict typing, Pydantic models, `self.logger` — project rules.
- Tests: CliRunner harness (`tests/knowledge/wiki/test_cli.py:42-60`), `AsyncMock` store for tools
  (`test_wiki_tools.py:17`), `create_wiki_mcp_server(tmp_path)` for MCP.

### Known Risks / Gotchas
- **`_open_store` mkdirs the storage dir** (`cli.py:132`) and `SQLiteWikiStore.__init__` mkdirs
  the parent (`store.py:488`) — a read-only foreign open must bypass both (construct
  `SQLiteWikiStore(db_path, read_only=True)` directly; never via `_open_store`).
- **Large planes**: ai-parrot's `wiki.db` is ~311 MB; N namespaces × FTS5 is still ms-scale, but
  open lazily, `gather` concurrently and never `list_pages(limit=1_000_000)` across namespaces on
  the read path.
- **Qualified ids in write paths**: `remember --link` / `link` accept page ids; a qualified id
  there must be rejected with a clear message unless `--ns` names that same namespace.
- **`pack_results` dedups by id** (`context.py:139`): local `file:README.md` and
  `asyncdb::file:README.md` are distinct ids — intended.
- **Vault inside a repo**: `repo_scan` already prunes `.parrot` at any depth (`repo_scan.py:239`),
  so a nested vault's plane is never scanned by the host repo; `find_project_root` from inside the
  vault resolves the vault's own project — expected.
- **Synced vaults**: `.parrot/` under a Dropbox/iCloud/Obsidian-Sync vault is carried along;
  documented as an accepted cost (D4.2); users may register the vault with `--store` elsewhere.
- **ArangoDB namespaces**: credentials from env prefix only (`resolve_arango_params`); eager
  `initialize()` under `arango_timeout` so an unreachable server becomes a skip, not a hang.
- **Rebase risk**: FEAT-451 edits `cli.py` (ingest region) concurrently; keep FEAT-450's edits to
  the helper block (87-272), read commands (1075-1288), `_prune_removed` (390-423),
  `_resolve_write_store` (1470-1495) and the authoring commands' option lists.
- **`_ID_PREFIX_RE` consumers**: only `context.py:124` and the build-time prune (`cli.py:417-420`,
  local plane only) parse prefixes — the regex change is contained.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | No new dependencies. `aiosqlite`, `click`, `pydantic`, `asyncdb` (arangodb extra) already in use. |

---

## 8. Open Questions

> All design questions were resolved in the accepted proposal; echoed here for the audit trail.

- [x] Id scheme for namespaced pages — *Resolved in proposal*: `ns::id`; local unprefixed (U3).
- [x] Where namespaces are declared — *Resolved in proposal*: both `.parrot/wiki.json` and
  `~/.parrot/wikis.json`; repo wins on clash.
- [x] v1 routing — *Resolved in proposal*: explicit `--ns` + broadcast; intent router is v2.
- [x] U1 How entries reach the global registry — *Resolved*: only `wikitoolkit ns add [--global]`;
  `build` never self-registers.
- [x] U2 Writes to a foreign namespace — *Resolved*: **required in v1** via explicit `--ns <name>`
  (single namespace, opened read-write); default writes local; `--ns all` rejected.
- [x] U3 Local ids unprefixed in broadcast output — *Resolved*: yes.
- [x] D4.1 Obsidian as a namespace kind — *Resolved*: yes, `vault` kind.
- [x] D4.2 Vault plane location — *Resolved*: inside the vault, resolved via
  `load_project_config(<vault>)` like `path` (Delta 2); default `<vault>/.parrot/wiki`.
- [x] D4.3 `vault_dir` auto-registration — *Resolved*: no; `ns add --vault` only.
- [x] D4.4 `_prune_removed` fix location — *Resolved*: inside FEAT-450 (`scope="root"` for
  `VaultIngestTool`).
- [ ] Whether `LLMWikiToolkit` (toolkit.py) should accept an injected `FederatedWikiStore` in this
  feature or in a follow-up — *Owner: Jesus* (non-blocking; not in AC; decide at `/sdd-task`).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — one worktree
  `.claude/worktrees/feat-450-wiki-namespaces`, tasks sequential.
- **Parallelizable inside the worktree** (if split across agents): Module 1 ‖ Module 2 ‖ Module 6
  are independent; Module 3 needs 1+2; Modules 4 and 5 need 3; Module 7 last.
- **Cross-feature dependencies**: none to merge first. **Concurrent**: FEAT-451
  (`wikitoolkit-ingest-documents`) edits `cli.py` lines ~2093-2544 — disjoint from this feature's
  regions; expect a trivial rebase. FEAT-449 (legal wiki) has no code yet; its GraphIndex
  namespaces (`legal:civil`) are compatible with the `::` separator by design.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-23 | Jesus Lara / Claude | Initial draft from accepted proposal (U1–U3, D4.1–D4.4, Delta 2) |
