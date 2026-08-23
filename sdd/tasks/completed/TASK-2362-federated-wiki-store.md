# TASK-2362: `federation.py` — `FederatedWikiStore` + namespace resolver

**Feature**: FEAT-450 — Namespaces for `wikitoolkit` (multi-wiki federation)
**Spec**: `sdd/specs/wiki-namespaces.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2359, TASK-2360, TASK-2361
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview + §3 Module 3 — the core of the feature. One `BaseWikiStore` implementation
composes the local plane with N foreign namespaces: reads fan out and merge with per-namespace
min-max + weight (scores from `search_fts` are raw `-bm25`, corpus-relative — `store.py:997-1043`),
foreign ids are qualified `ns::` (local unprefixed, U3), `get_page`/`neighbors` route by prefix,
writes go to the local plane only, and failing/unbuilt namespaces are skipped with a note (G9).
Because CLI, tools and MCP all already hold a `BaseWikiStore`, injecting this class gives them
namespaces for free (TASK-2363/2364/2365/2367).

---

## Scope

Create `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` with:

- `NamespaceSkip(BaseModel)`: `name`, `reason: Literal["unbuilt","unreachable","invalid"]`, `detail`, `hint=""`.
- `NamespaceHandle` (dataclass): `name`, `store`, `config: WikiNamespaceConfig`,
  `origin: Literal["repo","global"]`, `storage_dir: Optional[Path]`, `read_only: bool`.
- `open_namespace_store(name, cfg, *, base_dir: Path, read_only: bool = True, arango_timeout: float = 5.0) -> BaseWikiStore`
  — resolution per kind (spec §2 table): `path`/`vault` → `load_project_config(dir)` →
  `config.storage_path(dir)` + `config.backend` (+ `resolve_arango_params(config)` when arangodb);
  `store` → `storage_dir / "wiki.db"` (sqlite) or `create_wiki_store(store, backend=backend)`;
  `database` → `ArangoDBWikiStore(resolve_arango_params(WikiProjectConfig(arango_credentials_env=cfg.credentials_env, arango_database=cfg.database)), database=cfg.database)`
  then `await initialize()` under `asyncio.wait_for(..., arango_timeout)`. SQLite read-only opens use
  `SQLiteWikiStore(db_path, wiki_name=..., read_only=True)` **directly** (never `_open_store`,
  which mkdirs). `read_only=False` is the `--ns <name>` write path (U2) and uses `create_wiki_store`.
- `resolve_namespaces(root, config, *, only=None, registry_path=None, arango_timeout=5.0) -> tuple[list[NamespaceHandle], list[NamespaceSkip]]`
  — `merge_namespaces(config.namespaces, load_global_registry(registry_path).namespaces)`,
  filter by `only`, open each; `FileNotFoundError` → `unbuilt` (hint `wikitoolkit build --path <dir>`
  for path/vault kinds), connection/timeout errors → `unreachable`, validation errors → `invalid`.
- `FederatedWikiStore(BaseWikiStore)` per spec §2 New Public Interfaces: `__init__(local, local_name, handles, skipped)`,
  attributes `local_name`, `namespaces: dict[str, NamespaceHandle]`, `skipped`; `scoped(selector)`;
  reads `search_fts` / `search_vector` / `list_pages` (fan-out via `asyncio.gather(..., return_exceptions=True)`,
  per-namespace `limit`, min-max per namespace (all-equal → 1.0), `× weight`, local weight 1.0,
  rows gain `"namespace": name`, foreign `concept_id`/`node_id` qualified, dedup by qualified id,
  sort desc, cut to `limit`; a namespace whose call raises is logged and recorded as a per-call
  `NamespaceSkip("unreachable")` in `self.last_skipped`), `get_page` / `neighbors` (split id →
  route; unknown namespace → `None` / `[]`; foreign results re-qualified incl. neighbour ids),
  `stats` (local stats dict + `"local": local_name` + `"namespaces": {name: {...store.stats(),
  "kind", "backend", "origin", "read_only", "status": "ok"}}` + `"skipped": [skip.model_dump()]`),
  writes → local only (`ValueError` on a qualified foreign id), `dump_*` / lint / `rebuild_from_tree`
  → local only.
- Tests in `tests/knowledge/wiki/test_federation.py` with two temp SQLite planes.

**NOT in scope**: CLI/tool/MCP wiring; `search.py`'s `WikiSearchResult`-based merge (reference
only — federation works on the plain dicts `search_fts` returns).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | CREATE | resolver + federated store |
| `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py` | MODIFY | add `FederatedWikiStore`, `resolve_namespaces` to `_EXPORT_MODULES` (lazy map) |
| `tests/knowledge/wiki/test_federation.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord, create_wiki_store   # store.py:289,441,215,1217
from parrot.knowledge.wiki.project import (WikiProjectConfig, WikiNamespaceConfig, load_project_config,
    resolve_arango_params, load_global_registry, merge_namespaces)    # project.py:125,323,217 + TASK-2359
from parrot.knowledge.wiki.context import split_namespaced_id, qualify_id, NS_SEPARATOR   # TASK-2360
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore     # lazy import inside the arangodb branch (asyncdb optional dep — see store.py:1258-1263)
```

### Existing Signatures to Use
```python
# store.py
class BaseWikiStore(ABC):   # 289 — abstract: upsert_pages, add_edges, replace_source_slice, delete_page, upsert_embedding,
                            #   get_page(concept_id, include_body=True), list_pages(category=None, limit=100, origin=None),
                            #   search_fts(query, category=None, limit=10), search_vector(embedding, limit=10),
                            #   neighbors(concept_id, rel=None, direction="both"), dump_pages, dump_edges, stats,
                            #   orphan_sources, broken_edges, missing_bodies; concrete rebuild_from_tree (382)
# search_fts rows (997-1043): concept_id, node_id, title, category, summary, source_id, token_count, score (= -bm25, NOT normalised)
# neighbors rows (1087-1128): concept_id, rel, direction ('out'|'in'), + title/category when neighbour is a page
# stats (1152): {"pages","edges","sources","embeddings","total_tokens","categories"}
class SQLiteWikiStore: def __init__(self, db_path, wiki_name="", *, read_only=False)   # 485 + TASK-2361
def create_wiki_store(storage_dir, wiki_name="", backend="sqlite", **kwargs)          # 1217 — arangodb kwargs: arango_params, database, text_analyzer
# arango_store.py
class ArangoDBWikiStore: def __init__(self, arango_params: dict, database: str = "", wiki_name: str = "", text_analyzer: str = "text_en")  # 163
    async def initialize(self) -> None   # 230 (idempotent)
# project.py
def load_project_config(root: Path) -> WikiProjectConfig          # 323 (defaults when no wiki.json)
WikiProjectConfig.storage_path(root) -> Path (190); .backend; .wiki_name; .arango_database; .arango_text_analyzer
def resolve_arango_params(config: WikiProjectConfig) -> dict       # 217 — uses config.arango_credentials_env prefix + config.arango_database or wiki_{name}
# search.py — semantics to replicate on dicts (do NOT import; it works on WikiSearchResult models)
WikiCombinedSearch._apply_weight (497-530): span==0 → 1.0; weighted = min(max(norm*weight,0),1)
WikiCombinedSearch._merge_groups (473-495): dedup keep max; sort desc
# cli.py:164 _normalize_scores — CLI's own min-max over one list (leave it; it is idempotent on already-normalised rows)
```

### Does NOT Exist
- ~~`federation.py`~~ and everything in it — you create it.
- ~~`BaseWikiStore.search()`~~ — lexical entry point is `search_fts`.
- ~~`BaseWikiStore.scoped()`~~ on plain stores — only `FederatedWikiStore` has it; callers duck-type with `hasattr`.
- ~~`create_wiki_store(read_only=...)`~~ — not a kwarg; construct `SQLiteWikiStore(..., read_only=True)` directly.
- ~~`WikiSearchResult`~~ in federation — do not convert; keep dict rows so `pack_results`, `_normalize_scores` and the tools keep working.
- ~~`KnowledgeRouter`~~ — does not exist.

---

## Implementation Notes

### Pattern to Follow
```python
# Fan-out with isolation (spirit of MultiStoreSearchToolkit, return_exceptions=True)
results = await asyncio.gather(*(self._search_one(h, query, category, limit) for h in handles), return_exceptions=True)
for handle, res in zip(handles, results):
    if isinstance(res, BaseException):
        self.logger.warning("namespace %s failed: %s", handle.name, res)
        self.last_skipped.append(NamespaceSkip(name=handle.name, reason="unreachable", detail=str(res)))
        continue
```
Merge: normalise each group (`_minmax(rows) -> rows with score in [0,1]`), multiply by
`handle.config.weight` (local = 1.0), qualify ids with `qualify_id(name, cid)` for foreign rows only.

### Key Constraints
- `self.logger = logging.getLogger(__name__)`; async everywhere; Pydantic for `NamespaceSkip`.
- `scoped("all")`/`None` → self; `"local"` → `self._local`; `name` → a thin wrapper that qualifies
  ids of that one handle (implement as `FederatedWikiStore(local=handle.store, local_name=name,
  handles=[], skipped=[])` **plus** a `qualify` flag so its results carry `name::`) — keep it simple.
- `stats()` must keep the local top-level keys intact (existing `status` / `WikiStatusTool` consumers).
- Writes with a qualified id → `ValueError("write to namespace 'x' requires --ns x")`.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py:268-334` `_run_origins` / `_skipped_section` — degradation pattern.
- `cli.py:199-251` `_resolve_read_store` — arangodb eager `initialize()` error handling to mirror.

---

## Acceptance Criteria

- [ ] `FederatedWikiStore` instantiates as a `BaseWikiStore` (no abstract-method errors)
- [ ] Two planes with colliding `file:README.md`: `search_fts` returns both; foreign one as `other::file:README.md` with `namespace="other"`; local unprefixed
- [ ] Per-namespace min-max: a 5-page plane does not dominate a 500-page plane; `weight` applied
- [ ] `get_page("other::file:x")` routes; neighbour ids come back qualified; unknown ns → `None`/`[]`
- [ ] Writes land local; `delete_page("other::file:x")` → `ValueError`
- [ ] A handle raising in `search_fts` → others returned, `last_skipped` records it
- [ ] `resolve_namespaces` classifies unbuilt sqlite namespace → `NamespaceSkip(reason="unbuilt", hint=...)`
- [ ] `stats()` = local keys + `local` + `namespaces` + `skipped`
- [ ] `pytest tests/knowledge/wiki/test_federation.py -v`; `ruff check .../federation.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_federation.py
import pytest
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot.knowledge.wiki.project import WikiNamespaceConfig
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle, resolve_namespaces

async def _plane(dir_, pages):
    s = SQLiteWikiStore(dir_ / "wiki.db")
    await s.upsert_pages([WikiPageRecord(concept_id=c, title=t, body=b) for c, t, b in pages])
    await s.add_edges([("file:README.md", "file:a.py", "references")])
    return s

@pytest.fixture
async def fed(tmp_path):
    local = await _plane(tmp_path / "local", [("file:README.md", "README", "alpha local"), ("file:a.py", "a", "alpha code")])
    other_store = await _plane(tmp_path / "other", [("file:README.md", "README", "alpha other"), ("file:a.py", "a", "alpha other code")])
    other = SQLiteWikiStore(tmp_path / "other" / "wiki.db", read_only=True)
    h = NamespaceHandle(name="other", store=other, config=WikiNamespaceConfig(store=str(tmp_path / "other")), origin="repo", storage_dir=tmp_path / "other", read_only=True)
    return FederatedWikiStore(local=local, local_name="local", handles=[h], skipped=[])

async def test_search_qualifies_and_merges(fed):
    rows = await fed.search_fts("alpha", limit=10)
    ids = {r["concept_id"] for r in rows}
    assert "file:README.md" in ids and "other::file:README.md" in ids
    assert all(0.0 <= r["score"] <= 1.0 for r in rows) and all("namespace" in r for r in rows)

async def test_get_page_and_neighbors_route(fed):
    assert (await fed.get_page("other::file:README.md"))["concept_id"] == "other::file:README.md"
    assert (await fed.get_page("file:README.md"))["concept_id"] == "file:README.md"
    nb = await fed.neighbors("other::file:README.md")
    assert nb and all(n["concept_id"].startswith("other::") for n in nb)
    assert await fed.get_page("nope::file:x") is None

async def test_writes_local_only(fed):
    await fed.upsert_pages([WikiPageRecord(concept_id="file:new.md", title="n")])
    assert await fed.get_page("file:new.md")
    with pytest.raises(ValueError):
        await fed.delete_page("other::file:README.md")

async def test_scoped(fed):
    only = await fed.scoped("other").search_fts("alpha")
    assert all(r["concept_id"].startswith("other::") for r in only)
    local = await fed.scoped("local").search_fts("alpha")
    assert all("::" not in r["concept_id"] for r in local)

async def test_resolve_unbuilt(tmp_path):
    from parrot.knowledge.wiki.project import WikiProjectConfig
    cfg = WikiProjectConfig(namespaces={"x": WikiNamespaceConfig(path=str(tmp_path / "x"))})
    (tmp_path / "x").mkdir()
    handles, skipped = await resolve_namespaces(tmp_path, cfg, registry_path=tmp_path / "none.json")
    assert not handles and skipped[0].reason == "unbuilt" and "wikitoolkit build --path" in skipped[0].hint
```
(`resolve_namespaces` is async because the arangodb branch awaits `initialize()`; sync callers use
`asyncio.run` like `cli._run`.)

---

## Agent Instructions

1. Read spec §2 (Overview, Data Models, New Public Interfaces), §3 Module 3, §6, §7.
2. Verify the contract — especially TASK-2359/2360/2361 outputs — before coding.
3. Implement; run `pytest tests/knowledge/wiki -v` (whole directory).
4. Update index → `done`; move to `sdd/tasks/completed/`; fill the Completion Note.

---

## Completion Note

**Completed by**: Claude Code (main session)
**Date**: 2026-08-23
**Notes**: federation.py: NamespaceSkip, NamespaceHandle, open_namespace_store (path/vault/store/database kinds), resolve_namespaces (merge + classify unbuilt/unreachable/invalid), FederatedWikiStore (fan-out reads with per-namespace min-max + weight + qualification + dedup, prefix routing for get_page/neighbors, local-only writes with ValueError on a foreign id, stats with namespaces/skipped blocks, scoped() selectors). Lazy exports added to the wiki package. 32 new tests.

**Deviations from spec**: Added an _EmptyStore stand-in so scoped('a,b') (a namespace subset that excludes 'local') has no local plane to leak rows from; scoped(name) is a FederatedWikiStore with qualify_local=True so its rows keep the ns:: prefix. open_namespace_store returns (store, storage_dir) rather than just the store — the CLI write path and the handle both need the directory.
