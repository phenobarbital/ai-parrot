# TASK-3358: Extract `build_wiki_tools()` / `abuild_wiki_tools()` / `WikiToolBundle` from `create_wiki_mcp_server()` (M2d)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3353, TASK-3354, TASK-3357
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (builder part), design research S2. `create_wiki_mcp_server()`
(mcp_server.py:94-252) inlines the whole tool assembly — store, namespaces,
ledger overlay, wiki + structural + vault tools — and resolves namespaces
through `_run_sync` (a transient event loop). The HTTP server (TASK-3361) needs
the same assembly (a) as an **async** function running on the serving loop so
ArangoDB connections are owned by the process, (b) parameterised by
`ledger_dir` (TASK-3354), `read_repair` (TASK-3353) and `include_bulk_tools`
(TASK-3356/3357), and (c) returning the stores so they can be closed on
shutdown. This task performs that extraction; the stdio wrapper stays
byte-identical in behaviour (AC14).

---

## Scope

- `WikiToolBundle` dataclass: `tools`, `vault_tools`, `description`, `store`, `read_store`, `ledger_service`, `namespace_handles`.
- `async def abuild_wiki_tools(root, config, *, ledger_dir=None, read_repair=True, include_bulk_tools=False) -> WikiToolBundle` — the moved body, awaiting `resolve_namespaces()` and `store.initialize()` (ArangoDB) directly; `ledger_dir` → `LedgerService.from_dir(ledger_dir, sqlite_policy=sqlite_policy_from_config(config))` else today's `from_root` gated by `find_shared_root`; `create_structural_tools(read_store, root, config, read_repair=read_repair)`; `if include_bulk_tools: tools += create_bulk_tools(store, root, config)`.
- `def build_wiki_tools(...)` — sync wrapper via `_run_sync(abuild_wiki_tools(...))`.
- `async def close_bundle(bundle)` — close `store`, each namespace handle store, and `ledger_service.store` when present (best-effort, log failures).
- `create_wiki_mcp_server(root)` becomes: config → `build_wiki_tools(root, config)` → `StdioMCPServer(LocalServerConfig(...))` → `register_tools` (same description string, same tool order).
- Tests: tool-name parity with the pre-refactor list; flags respected; `close_bundle` closes.

**NOT in scope**: HTTP server (TASK-3361), pass-through server (TASK-3364), any change to tool names.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | extract builder; slim wrapper |
| `packages/ai-parrot/tests/knowledge/wiki/test_wiki_tool_bundle.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported at mcp_server.py:10-28: asyncio, contextlib, logging, os, sys, ThreadPoolExecutor, Path, TYPE_CHECKING/Any,
#   from parrot.knowledge.wiki.project import WikiConfigError, find_project_root, load_effective_config, sqlite_policy_from_config
#   from parrot.knowledge.wiki.store import create_wiki_store ; from parrot.knowledge.wiki.tools import create_wiki_tools
from dataclasses import dataclass, field                                          # stdlib (add)
from parrot.knowledge.wiki.tools import create_bulk_tools                          # added by TASK-3356/3357
from parrot.knowledge.wiki.structural import create_structural_tools               # already imported lazily at mcp_server.py:207 — now accepts read_repair= (TASK-3353)
from parrot.knowledge.wiki.ledger.service import LedgerService                     # lazily imported at mcp_server.py:~150; from_dir added by TASK-3354
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle, resolve_namespaces   # lazily imported at mcp_server.py:~140
from parrot.knowledge.wiki.project import WikiNamespaceConfig, find_shared_root, resolve_arango_params, resolve_vault_dir   # lazily imported in the current body
from parrot.knowledge.wiki.store import BaseWikiStore                              # store.py:525
from parrot.mcp.local_server import StdioMCPServer; from parrot.mcp.server_base import LocalServerConfig   # lazily imported at mcp_server.py:~105 under redirect_stdout
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py (current)
def _ensure_stderr_logging() -> None                       # :47
def _run_sync(coro: Any) -> Any                            # :70-92 — asyncio.run, or a worker thread when a loop is running
def create_wiki_mcp_server(root: Path) -> StdioMCPServer   # :94 (anchor 1×) … body:
    config = load_effective_config(root).config            # :110 (1×)
    storage = config.storage_path(root)                    # :117 (1×) → arangodb branch create_wiki_store(..., arango_params=resolve_arango_params(config), database=..., text_analyzer=...) else sqlite create_wiki_store(..., sqlite_policy=sqlite_policy_from_config(config))
    handles, skipped = _run_sync(resolve_namespaces(root, config))   # → MUST become `await resolve_namespaces(root, config)`
    # ledger: if find_shared_root(root) is not None: LedgerService.from_root(root); NamespaceHandle(name="ledger", store=ledger_service.store, config=WikiNamespaceConfig(store=str(ledger_dir), description=..., weight=0.5, overlay_prefixes=["issue","task","spec","insight"]), storage_dir=ledger_dir, read_only=True)
    read_store = FederatedWikiStore(store, config.wiki_name, handles, skipped) if handles or skipped else store
    tools = create_wiki_tools(read_store, root=root, config=config, ledger_service=ledger_service)   # :202 (1×)
    tools = tools + create_structural_tools(read_store, root, config)                                  # :209 (1×)
    description = "Codebase knowledge graph — query, explore, remember, and look up symbols …" (+ namespaces, + vault)
    vault_tools … ObsidianToolkit(vault_path=vault).get_tools_sync() + VaultIngestTool(store, root=root, config=config)
    server = StdioMCPServer(LocalServerConfig(name="wikitoolkit", version="1.0.0", description=description))   # :243-249 (`    server = StdioMCPServer(` 1×)
    server.register_tools(tools); if vault_tools: server.register_tools(vault_tools); return server           # :249-252
def main() -> None                                          # :261-289 — `server = create_wiki_mcp_server(root)` (1×), `asyncio.run(server.start())` (:289)
# TASK-3353: create_structural_tools(store, root, config, *, read_repair=True)
# TASK-3354: LedgerService.from_dir(ledger_dir, *, sqlite_policy=None)
# TASK-3357: create_bulk_tools(store, root, config) -> 4 tools
# federation.py: class NamespaceHandle(name, store, config, storage_dir, read_only) :96-128 ; FederatedWikiStore(store, wiki_name, handles, skipped) :622
# arango_store.py: ArangoDBWikiStore.initialize() :258 ; close() :423
```

### Does NOT Exist
- ~~`build_wiki_tools` / `abuild_wiki_tools` / `WikiToolBundle` / `close_bundle`~~ — created here.
- ~~`create_wiki_mcp_server(root, config)`~~ — keep the one-argument signature (callers: `main()`, tests).
- ~~`BaseWikiStore.close()` on every backend~~ — `SQLiteWikiStore`/`InMemoryWikiStore` may not define `close`; `close_bundle` must `getattr(store, "close", None)` and await only when present.
- ~~`StdioMCPServer.tools` as a list~~ — it is `dict[str, MCPToolAdapter]` (server_base.py:~62); tests compare `set(server.tools)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_wiki_tool_bundle.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#create_wiki_mcp_server",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#_run_sync",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py#main",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#resolve_namespaces",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py#create_structural_tools",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep every `contextlib.redirect_stdout(sys.stderr)` guard exactly where the current body has it (stdout is the stdio JSON-RPC channel).
- `abuild_wiki_tools` must not call `_run_sync` anywhere; `build_wiki_tools` is the only place that does.
- In the ArangoDB branch, `await store.initialize()` before resolving namespaces (design research S2) — the sync path used to rely on lazy init.
- Tool order must stay: wiki tools → structural → (bulk) → vault, so `tools/list` is stable for the golden test (TASK-3367).

---

## Implementation Blueprint

### Steps (in order)
1. Add `WikiToolBundle` + `abuild_wiki_tools` above `create_wiki_mcp_server` — *why*: the wrapper references them.
2. Move the body of `create_wiki_mcp_server` into `abuild_wiki_tools`, converting `_run_sync(resolve_namespaces(...))` to `await`, adding the three flags — *why*: the server must own its loop.
3. Add `build_wiki_tools` (sync) + `close_bundle` — *why*: stdio path and shutdown path.
4. Rewrite `create_wiki_mcp_server` as the thin wrapper — *why*: AC14 parity with the fewest moving parts.
5. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` (MODIFY — block 1)
```python
# occurrences: 1 (verified: grep -c '^def create_wiki_mcp_server(root: Path)' packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py)
# BEFORE — insert above `def create_wiki_mcp_server(root: Path) -> StdioMCPServer:` (verified: mcp_server.py:94)
@dataclass
class WikiToolBundle:
    """Everything a transport needs to register for one wiki (FEAT-569)."""
    tools: list[Any]
    vault_tools: list[Any]
    description: str
    store: Any                       # writable local plane (BaseWikiStore)
    read_store: Any                  # federated read view (BaseWikiStore)
    ledger_service: Any | None
    namespace_handles: list[Any] = field(default_factory=list)


async def abuild_wiki_tools(
    root: Path,
    config: Any,
    *,
    ledger_dir: Path | None = None,
    read_repair: bool = True,
    include_bulk_tools: bool = False,
) -> WikiToolBundle:
    """Assemble the wiki tool surface on the CURRENT event loop (no transient loops).

    Args:
        root: Wiki project root (repo root, or the server-side wiki directory).
        config: Effective ``WikiProjectConfig``.
        ledger_dir: Explicit ledger directory (server); ``None`` keeps the git-root
            discovery via ``find_shared_root`` (stdio).
        read_repair: Passed to ``create_structural_tools`` — ``False`` on hosts without a source tree.
        include_bulk_tools: Register ``create_bulk_tools()`` (server only).

    Returns:
        The bundle; callers own ``close_bundle(bundle)``.
    """
    # FILL IN: MOVE the current body of create_wiki_mcp_server (mcp_server.py:~105-238) here, with these changes only:
    #   1. arangodb branch: `await store.initialize()` right after create_wiki_store(...)            — S2
    #   2. `handles, skipped = _run_sync(resolve_namespaces(root, config))` → `handles, skipped = await resolve_namespaces(root, config)`
    #   3. ledger: `if ledger_dir is not None: ledger_service = LedgerService.from_dir(ledger_dir, sqlite_policy=sqlite_policy_from_config(config))`
    #      `elif find_shared_root(root) is not None: <existing from_root block>`; the NamespaceHandle block uses `ledger_dir_eff = ledger_dir or ledger_service.shared_root / ".parrot" / "ledger"`
    #   4. `tools = tools + create_structural_tools(read_store, root, config, read_repair=read_repair)`
    #   5. after structural: `if include_bulk_tools: from parrot.knowledge.wiki.tools import create_bulk_tools; tools = tools + create_bulk_tools(store, root, config)`
    #   6. return WikiToolBundle(tools=tools, vault_tools=vault_tools, description=description, store=store, read_store=read_store,
    #                            ledger_service=ledger_service, namespace_handles=list(handles))
    # Keep every `with contextlib.redirect_stdout(sys.stderr):` guard and `_ensure_stderr_logging()` call exactly as they are — bounded by AC14 (stdio byte-identical)
    raise NotImplementedError


def build_wiki_tools(root: Path, config: Any, *, ledger_dir: Path | None = None, read_repair: bool = True,
                     include_bulk_tools: bool = False) -> WikiToolBundle:
    """Sync wrapper for the stdio path — the ONLY place that uses ``_run_sync``."""
    return _run_sync(abuild_wiki_tools(root, config, ledger_dir=ledger_dir, read_repair=read_repair, include_bulk_tools=include_bulk_tools))


async def close_bundle(bundle: WikiToolBundle) -> None:
    """Close every store the bundle owns (best effort; failures are logged, never raised)."""
    targets = [bundle.store, *(h.store for h in bundle.namespace_handles)]
    if bundle.ledger_service is not None:
        targets.append(bundle.ledger_service.store)
    for target in targets:
        close = getattr(target, "close", None)
        if close is None:
            continue
        try:
            result = close()
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning("close_bundle: %s", exc)


```
**Why this shape**: the spec fixes the three flags and the bundle fields; moving (not rewriting) the body is what keeps AC14. `_run_sync` stays for stdio because `main()` is synchronous.

### `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` (MODIFY — block 2: the wrapper)
```python
# REPLACE the body of `def create_wiki_mcp_server(root: Path) -> StdioMCPServer:` (mcp_server.py:94-252) with:
    """Build a `StdioMCPServer` with the wiki tools registered (thin wrapper over build_wiki_tools)."""
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.mcp.local_server import StdioMCPServer
        from parrot.mcp.server_base import LocalServerConfig

    config = load_effective_config(root).config
    bundle = build_wiki_tools(root, config)
    _ensure_stderr_logging()
    server = StdioMCPServer(LocalServerConfig(name="wikitoolkit", version="1.0.0", description=bundle.description))
    server.register_tools(bundle.tools)
    if bundle.vault_tools:
        server.register_tools(bundle.vault_tools)
    return server
```
**Why**: same server name/version/description/tool order as today (:243-252), so `test_mcp_server*.py` keep passing unchanged. Keep the original docstring's Args/Returns text.

### FILL IN checklist
- [ ] Body move with the six listed changes — bounded by AC14 + S2.
- [ ] Docstring of `create_wiki_mcp_server` retains Args/Returns.
- [ ] Verify tool order in the golden test fixture (TASK-3367 consumes it).

---

## Acceptance Criteria

- [ ] `set(create_wiki_mcp_server(root).tools)` equals the pre-refactor set on the same fixture repo (14 names with a git-backed root; 9 without ledger); `test_mcp_server.py`, `test_mcp_server_namespaces.py`, `test_mcp_server_vault.py` pass unchanged.
- [ ] `build_wiki_tools(root, cfg, include_bulk_tools=True).tools` contains the 4 bulk tool names; with the default it contains none.
- [ ] `build_wiki_tools(root, cfg, ledger_dir=tmp)` yields `ledger_service.shared_root == tmp.parent.parent` and never calls `find_shared_root` (monkeypatch it to raise).
- [ ] `build_wiki_tools(..., read_repair=False)` → structural tools' service `_read_repair is False`.
- [ ] `await abuild_wiki_tools(...)` works inside a running loop without `_run_sync` (monkeypatch `_run_sync` to raise).
- [ ] `await close_bundle(bundle)` calls `close()` on stores that define it and does not raise for ones that don't.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_wiki_tool_bundle.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_wiki_tool_bundle.py
import pytest
from parrot.knowledge.wiki import mcp_server
from parrot.knowledge.wiki.mcp_server import abuild_wiki_tools, build_wiki_tools, close_bundle, create_wiki_mcp_server
from parrot.knowledge.wiki.project import WikiProjectConfig, load_effective_config, save_project_config
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store

BASE = {"wiki_query", "wiki_page", "wiki_related", "wiki_remember", "wiki_note", "wiki_status",
        "wiki_symbol_lookup", "wiki_code_outline", "wiki_blast_radius"}
BULK = {"wiki_page_hashes", "wiki_ingest_batch", "wiki_sync_push", "wiki_sync_pull"}


@pytest.fixture
def repo(tmp_path):
    cfg = WikiProjectConfig(wiki_name="t"); (tmp_path / ".parrot").mkdir(); save_project_config(tmp_path, cfg)
    store = create_wiki_store(cfg.storage_path(tmp_path), wiki_name="t", backend="sqlite")
    import asyncio; asyncio.run(store.upsert_pages([WikiPageRecord(concept_id="c", title="c", body="b")]))
    return tmp_path


def test_parity_and_flags(repo):
    assert BASE <= set(create_wiki_mcp_server(repo).tools) and not BULK & set(create_wiki_mcp_server(repo).tools)
    cfg = load_effective_config(repo).config
    b = build_wiki_tools(repo, cfg, include_bulk_tools=True, read_repair=False, ledger_dir=repo / "srv" / ".parrot" / "ledger")
    assert BULK <= {t.name for t in b.tools}
    assert b.ledger_service.shared_root == (repo / "srv").resolve()


async def test_async_builder_no_transient_loop(repo, monkeypatch):
    monkeypatch.setattr(mcp_server, "_run_sync", lambda coro: (_ for _ in ()).throw(AssertionError("transient loop")))
    b = await abuild_wiki_tools(repo, load_effective_config(repo).config)
    await close_bundle(b)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3353, TASK-3354, TASK-3357 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-read mcp_server.py:94-252 in full before moving it
4. **Update status** in `sdd/tasks/index/wikitoolkit-http-mcp.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** acceptance criteria; run the Validation Commands
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
