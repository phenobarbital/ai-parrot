# TASK-2365: `namespace` argument on wiki tools + federated store injection in the MCP server

**Feature**: FEAT-450 — Namespaces for `wikitoolkit` (multi-wiki federation)
**Spec**: `sdd/specs/wiki-namespaces.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2362
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5, G7. The six `AbstractTool` wrappers (`tools.py`) and the MCP server
(`mcp_server.py`) already hold one `BaseWikiStore`; injecting a `FederatedWikiStore` makes
`wiki_query` / `wiki_page` / `wiki_related` / `wiki_status` namespace-aware. Only an optional
`namespace` argument is added to the three read inputs, resolved through `store.scoped(...)`
(duck-typed so the existing `AsyncMock` store tests keep passing).

---

## Scope

- `tools.py`: add `namespace: str | None = Field(default=None, description="Namespace name, 'all', 'local', or omit for the default routing")`
  to `WikiQueryInput`, `WikiPageInput`, `WikiRelatedInput`; in the three `_execute` methods compute
  `store = self._store.scoped(namespace) if namespace and hasattr(self._store, "scoped") else self._store`
  (unknown name → `ToolResult(success=False, error=...)` for page/related; a short error string for
  query, which returns `str`). `WikiStatusTool` unchanged (the federated `stats()` already adds
  `namespaces`/`skipped`). Update the tool `description`s to mention namespaces and `ns::` ids.
- `mcp_server.py::create_wiki_mcp_server`: after the local store is created (line 95/105), call
  `handles, skipped = asyncio.run(resolve_namespaces(root, config))` **inside the existing
  `contextlib.redirect_stdout(sys.stderr)` discipline** and, when the merged map is non-empty, wrap:
  `store = FederatedWikiStore(store, config.wiki_name, handles, skipped)` before
  `create_wiki_tools(store, root=root, config=config)` (108). `VaultIngestTool` keeps receiving the
  **local** store (it writes). Server description mentions the namespace count when > 0.
- Tests: `packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py` (namespace passthrough with
  a fake store exposing `scoped`, and unchanged behaviour with a plain `AsyncMock`);
  `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py` (a temp root with one
  namespace → `wiki_query` result contains a qualified id).

**NOT in scope**: CLI; `LLMWikiToolkit` (TASK-2367); changing `create_wiki_tools` signature.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | `namespace` field + scoped dispatch |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | federated injection |
| `packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py` | MODIFY | add tests |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py` | CREATE | MCP injection test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.tools import (WikiQueryTool, WikiPageTool, WikiRelatedTool, WikiRememberTool,
    WikiNoteTool, WikiStatusTool, VaultIngestTool, create_wiki_tools)    # tools.py:67,90,115,137,214,272,288,399
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server     # mcp_server.py:66
from parrot.knowledge.wiki.federation import FederatedWikiStore, resolve_namespaces   # TASK-2362
from parrot.tools.abstract import AbstractTool, ToolResult               # parrot/tools/abstract.py:235,200
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
class WikiQueryInput(BaseModel): question: str; budget_tokens: int = DEFAULT_BUDGET_TOKENS   # 23-25
class WikiPageInput(BaseModel): page_id: str                                                  # 28-29
class WikiRelatedInput(BaseModel): page_id: str                                               # 32-33
class WikiQueryTool(AbstractTool): name = "wiki_query"; description = "..."; args_schema = WikiQueryInput   # 67-78
    def __init__(self, store: BaseWikiStore): super().__init__(name=self.name, description=self.description); self._store = store   # 80-82
    async def _execute(self, question: str, budget_tokens: int = DEFAULT_BUDGET_TOKENS) -> str   # 84 — search_fts → pack_results(...).text
class WikiPageTool:    async def _execute(self, page_id: str) -> ToolResult      # 105 — get_page(include_body=True); not found → ToolResult(success=False, ...)
class WikiRelatedTool: async def _execute(self, page_id: str) -> ToolResult      # 130 — neighbors(page_id) → ToolResult(result={"neighbors": ...})
class WikiStatusTool:  async def _execute(self) -> ToolResult                    # 283 — ToolResult(result=await store.stats())
class VaultIngestTool: def __init__(self, store, root: Path, config: WikiProjectConfig)   # 300
def create_wiki_tools(store, root=None, config=None) -> list[AbstractTool]       # 399-428
# parrot/tools/abstract.py
class ToolResult(BaseModel): success: bool = True; status: str = "success"; result: Any; error: Optional[str] = None; metadata: dict   # 200-207
# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
_INVOCATION_CWD = os.getcwd()                                                   # 36
def _ensure_stderr_logging() -> None                                            # 39
def create_wiki_mcp_server(root: Path) -> StdioMCPServer                        # 66
    with contextlib.redirect_stdout(sys.stderr): from parrot.mcp.local_server import StdioMCPServer; from parrot.mcp.server_base import LocalServerConfig   # 83-85
    config = load_project_config(root); storage = config.storage_path(root)      # 87-93
    store = create_wiki_store(... arangodb ...) (95) / storage.mkdir + create_wiki_store(storage, wiki_name=..., backend=config.backend) (104-107)
    tools = create_wiki_tools(store, root=root, config=config)                   # 108
    vault block 111-138: resolve_vault_dir → ObsidianToolkit(vault_path=vault).get_tools_sync() + VaultIngestTool(store, root=root, config=config)
    server = StdioMCPServer(LocalServerConfig(name="wikitoolkit", version="1.0.0", description=description)); server.register_tools(tools)   # 139-144
def main() -> None                                                              # 148 — find_project_root(_INVOCATION_CWD), is_built check, asyncio.run(server.start())
# tests
packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py: `mock_store = AsyncMock()` (17); `WikiQueryTool(mock_store)` (37); create_wiki_tools tests 168-179
packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py: `create_wiki_mcp_server(tmp_path)` (25,44), fixture vault (30)
```

### Does NOT Exist
- ~~`WikiQueryInput.namespace`~~ etc. — you add them.
- ~~`AsyncMock().scoped`~~ — an `AsyncMock` auto-creates attributes, so `hasattr(mock, "scoped")` is **True**
  and `mock.scoped(...)` returns a coroutine, not a store. Guard with `isinstance(self._store, FederatedWikiStore)`
  (import lazily inside `_execute` or at module level — `federation.py` imports only wiki modules) **or**
  `callable(getattr(type(self._store), "scoped", None))`. Write the test for the plain-mock path.
- ~~`create_wiki_tools(..., namespaces=...)`~~ — signature unchanged.
- ~~`server.register_tool(s)` printing to stdout~~ — nothing may print to stdout before the JSON-RPC loop.

---

## Implementation Notes

### Pattern to Follow
```python
# mcp_server.py:104-108 → wrap before handing to tools
with contextlib.redirect_stdout(sys.stderr):
    from parrot.knowledge.wiki.federation import FederatedWikiStore, resolve_namespaces
    handles, skipped = asyncio.run(resolve_namespaces(root, config))
read_store = FederatedWikiStore(store, config.wiki_name, handles, skipped) if (handles or skipped) else store
tools = create_wiki_tools(read_store, root=root, config=config)
```
`create_wiki_tools` also builds `WikiRememberTool`/`WikiNoteTool` from the same store — with a
federated store their writes delegate to local (spec), so passing `read_store` is correct.

### Key Constraints
- `asyncio.run` inside `create_wiki_mcp_server` is fine (called from sync `main()` before
  `asyncio.run(server.start())`); do not nest inside a running loop.
- Keep tool `description`s short — they become the LLM's tool descriptions.

### References in Codebase
- `mcp_server.py:111-138` — lazy-import + stdout-redirect discipline to copy.

---

## Acceptance Criteria

- [ ] `wiki_query(question, namespace="other")` scopes; `namespace=None` → default routing; unknown → error result
- [ ] Plain `AsyncMock` store keeps passing the existing `test_wiki_tools.py` tests
- [ ] `create_wiki_mcp_server(root_with_namespace)` registers tools bound to a `FederatedWikiStore`; `wiki_query` output contains `other::`
- [ ] `wiki_status` result contains `namespaces` and `skipped`
- [ ] `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py -v`; `ruff check` on both modules

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_wiki_tools.py (append)
class _Fed(FederatedWikiStore): ...   # or build a real one from two temp planes (see TASK-2362 fixture)

async def test_query_namespace_scopes(fed):
    tool = WikiQueryTool(fed)
    out = await tool._execute("alpha", namespace="other")
    assert "other::" in out and "[file:" not in out

async def test_page_unknown_namespace(fed):
    res = await WikiPageTool(fed)._execute("file:README.md", namespace="nope")
    assert res.success is False

async def test_plain_mock_store_unchanged(mock_store):
    mock_store.search_fts.return_value = [{"concept_id": "file:x", "title": "x", "summary": "s", "score": 1.0}]
    assert "file:x" in await WikiQueryTool(mock_store)._execute("q")

# packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py
def test_server_injects_federated_store(tmp_path, monkeypatch):
    ...build two tiny planes with SQLiteWikiStore; write tmp_path/".parrot/wiki.json" with namespaces={"other": {"path": str(other_root)}}...
    server = create_wiki_mcp_server(tmp_path)
    tool = next(t for t in server._tools.values() if t.name == "wiki_query")   # adapt to StdioMCPServer's registry attribute (grep server_base.py:38-50)
    assert isinstance(tool._store, FederatedWikiStore)
```

---

## Agent Instructions

1. Read spec §3 Module 5, §6 (`tools.py`, `mcp_server.py` blocks), §7 (stdout discipline).
2. Verify the contract; check `parrot/mcp/server_base.py:38-50` for how registered tools are stored.
3. Implement; run the tests above plus `tests/knowledge/wiki`.
4. Update index → `done`; move to `sdd/tasks/completed/`; fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
