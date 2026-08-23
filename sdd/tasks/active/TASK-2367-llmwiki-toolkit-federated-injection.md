# TASK-2367: `LLMWikiToolkit` accepts an injected (federated) store; `list_wikis` / `_config_for` dispatch namespaces

**Feature**: FEAT-450 — Namespaces for `wikitoolkit` (multi-wiki federation)
**Spec**: `sdd/specs/wiki-namespaces.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Assigned-to**: unassigned
**Depends-on**: TASK-2362

---

## Context

Spec §8 (resolved at `/sdd-task`, 2026-08-23): the agent-facing `LLMWikiToolkit` (toolkit.py)
gets namespace support **in this feature**. It already threads `wiki_name` through its API and
reserves an explicit dispatch point: `_config_for` (toolkit.py:1205-1228, "Multi-wiki support would
dispatch to different configs here") and `list_wikis` (499-516, "Multi-wiki support can be added in
a future iteration"). Today `__init__` (75-165) always builds its own store via `create_wiki_store`.

---

## Scope

- `LLMWikiToolkit.__init__(..., store: Optional[BaseWikiStore] = None, **kwargs)`: when `store` is
  given, use it instead of building one (skip the backend switch); `self._search =
  WikiCombinedSearch(..., store=self._store)` and `self._ingest_orch` keep receiving `self._store`.
  For `SourceCollectionManager` construction keep the current logic keyed on `config.storage_backend`
  (sources stay local).
- `_config_for(wiki_name)`: accept `self._config.wiki_name` as today; additionally, when
  `self._store` is a `FederatedWikiStore` and `wiki_name in self._store.namespaces` (or `"all"` /
  `"local"`), return the same `WikiConfig` (the config object is per-toolkit) — the *store*
  dispatch happens by scoping: add a helper `_store_for(wiki_name) -> BaseWikiStore` returning
  `self._store.scoped(wiki_name)` for federated stores and `self._store` otherwise. Route the
  read methods that take `wiki_name` (`search`, `search_compact`, `browse_pages`, `read_page`,
  `expand`, `find_related`, `get_wiki_info`) through `_store_for` where they touch the store
  directly; `search` / `search_compact` go through `WikiCombinedSearch` — construct a per-call
  `WikiCombinedSearch(self._pi, self._gi, self._config.search_weights, store=self._store_for(wiki_name))`
  when `wiki_name` names a namespace (cache by name).
- `list_wikis()`: when federated, return the local entry **plus** one dict per namespace
  (`wiki_name`, `storage_dir`, `kind`, `origin`, `read_only`, `source_count` where cheap) and the
  skipped list.
- Tests in `tests/knowledge/wiki/test_toolkit.py` (extend): injected store is used (no
  `create_wiki_store` call — patch through the module object, see the repo's test convention in
  commit `089e08e90`), `list_wikis` enumerates namespaces, `search(wiki_name="other")` scopes,
  unknown name still raises `ValueError`.

**NOT in scope**: write routing through the toolkit to foreign namespaces (writes stay local —
toolkit `create_page`/`remember` keep using `self._store`, whose federated writes delegate local);
CLI/MCP.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | MODIFY | injected store, `_store_for`, `list_wikis`, `_config_for` |
| `tests/knowledge/wiki/test_toolkit.py` | MODIFY | add tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit                 # toolkit.py:46
from parrot.knowledge.wiki.models import WikiConfig, WikiSearchResult   # models.py
from parrot.knowledge.wiki.search import WikiCombinedSearch             # search.py:32
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store   # store.py:289,1217
from parrot.knowledge.wiki.federation import FederatedWikiStore          # TASK-2362
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):  tool_prefix = "wiki"                  # 46, 73
    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit, config: WikiConfig, agent_id: str = "agent", **kwargs)   # 75-83
        # store construction 110-128: arangodb branch builds ArangoDBWikiStore directly; else create_wiki_store(config.storage_dir, wiki_name=..., backend=config.storage_backend)
        # sources 129-144 keyed on config.storage_backend; self._bookkeeper = WikiBookkeeper() 145
        # self._search = WikiCombinedSearch(pageindex_toolkit, graphindex_toolkit, config.search_weights, store=self._store)   # 146-151
        # self._ingest_orch = WikiIngestOrchestrator(..., store=self._store, sync_graph=config.sync_graph)   # 152-159
    async def create_wiki(self, wiki_name, description=None) -> dict        # 445
    async def list_wikis(self) -> list[dict]                                # 499-516 — single entry {wiki_name, storage_dir, source_count}
    async def get_wiki_info(self, wiki_name) -> dict                        # 518
    async def search(self, wiki_name, query, mode="combined") -> list[dict] # 991 — self._search.search(query, mode=mode, top_k=15, tree_name=wiki_name)
    async def search_compact(self, wiki_name, query, budget_tokens=..., mode="combined") -> dict   # 1012
    async def expand(...) 1049; find_related(...) 1080; browse_pages(...) 573; read_page(...) 600
    def _config_for(self, wiki_name: str) -> WikiConfig                     # 1205-1228 — raises ValueError on mismatch
# search.py
class WikiCombinedSearch: def __init__(self, pageindex_toolkit, graphindex_toolkit, default_weights=None, store=None, embedder=None)   # 47
    async def search(self, query, mode="combined", top_k=10, tree_name=None, weights=None, include_archived=False) -> list[WikiSearchResult]   # 85 — store path when store is not None
    def _store_row_to_wiki(self, row, source) -> WikiSearchResult            # 249 — node_id = concept_id (qualified ids pass through)
# TASK-2362: FederatedWikiStore.namespaces: dict[str, NamespaceHandle]; .skipped; .local_name; .scoped(name) -> BaseWikiStore
```

### Does NOT Exist
- ~~`LLMWikiToolkit(store=...)`~~ — no such kwarg today (`**kwargs` goes to `AbstractToolkit`); you add it explicitly before `**kwargs`.
- ~~`LLMWikiToolkit._store_for`~~ — you create it.
- ~~`WikiConfig.namespaces`~~ — `WikiConfig` (models.py) has no namespace fields; do not add any — namespaces come from the injected store.
- ~~`WikiCombinedSearch.scoped`~~ — scoping is a store concern; build a per-namespace `WikiCombinedSearch` instead.

---

## Implementation Notes

### Pattern to Follow
```python
# toolkit.py:110-128 — wrap the existing branch
if store is not None:
    self._store = store
elif config.storage_backend == "arangodb":
    ...existing...
else:
    ...existing...
```
Patch `create_wiki_store` in tests through the module object
(`patch.object(toolkit_module, "create_wiki_store")`), not a dotted string (repo convention, see
`tests/knowledge/wiki/test_cli.py:23-36` comment).

### Key Constraints
- `AbstractToolkit` auto-exposes public async methods as tools — do **not** add new public methods
  unless they are meant to be LLM-callable; `_store_for` must be underscore-prefixed.
- Keep `_config_for`'s `ValueError` for truly unknown names (explicit programming error, per its docstring).

### References in Codebase
- `toolkit.py:1205-1228` docstring — the designed dispatch point.
- `.agent/CONTEXT.md` "AbstractTool / AbstractToolkit" — reserved underscore names.

---

## Acceptance Criteria

- [ ] `LLMWikiToolkit(..., store=fed)` uses the injected store; `create_wiki_store` not called
- [ ] `list_wikis()` returns local + namespaces (+ skipped) when federated; single entry otherwise
- [ ] `search("other", q)` / `search_compact("other", q)` return only `other::` ids; `search(config.wiki_name, q)` unchanged
- [ ] `_config_for("nope")` still raises `ValueError`
- [ ] `pytest tests/knowledge/wiki/test_toolkit.py -v`; `ruff check .../toolkit.py`

---

## Test Specification

```python
# tests/knowledge/wiki/test_toolkit.py (append) — reuse the module's existing pi/gi/okf stubs
import parrot.knowledge.wiki.toolkit as toolkit_module

async def test_injected_store_used(fed, stub_toolkits, tmp_path):
    with patch.object(toolkit_module, "create_wiki_store") as cws:
        tk = LLMWikiToolkit(*stub_toolkits, WikiConfig(wiki_name="local", storage_dir=tmp_path), store=fed)
    cws.assert_not_called()
    assert tk._store is fed

async def test_list_wikis_enumerates_namespaces(tk_fed):
    names = {w["wiki_name"] for w in await tk_fed.list_wikis()}
    assert {"local", "other"} <= names

async def test_search_scopes_namespace(tk_fed):
    rows = await tk_fed.search("other", "alpha")
    assert rows and all(r["node_id"].startswith("other::") for r in rows)
```

---

## Agent Instructions

1. Read spec §8 (last item), §6 (`toolkit.py` block), `.agent/CONTEXT.md` toolkit rules.
2. Verify the contract; implement; run `tests/knowledge/wiki/test_toolkit.py` and `test_toolkit_arango.py`.
3. Update index → `done`; move to `sdd/tasks/completed/`; fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
