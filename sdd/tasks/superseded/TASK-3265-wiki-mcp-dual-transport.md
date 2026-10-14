# TASK-3265: Wiki MCP server — dual transport (`parrot.mcp` or `mcp` SDK)

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3263, TASK-3264
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 / goal G5: the `wikitoolkit mcp` server must run when
`parrot.mcp` (and the agent-framework `AbstractTool` stack behind it) is not
importable, while the in-framework `StdioMCPServer` path stays the default when
it is. After TASK-3260/3261 the six wiki operations, the five ledger operations,
`vault_ingest` and the three structural operations exist as framework-free
`WikiOperation`s (`parrot.knowledge.wiki.operations`,
`parrot.knowledge.wiki.structural.operations`); after TASK-3262/3263 the
`AbstractTool` wrappers live in `parrot_tools.wiki`. This task adds an
`mcp`-SDK stdio server built directly from `WikiOperation`s and teaches
`create_wiki_mcp_server` to pick a transport.

Resolves spec §8 open question 3 ("probe or flag?"): **import probe, with an
explicit `transport=` argument and a `WIKI_MCP_TRANSPORT` env override** (read via
TASK-3264's `resolve_setting`) — probe is the brainstorm's wording, the override
makes both paths deterministic in tests.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_sdk.py` with `WikiSDKServer`
  (mcp 1.29 low-level `Server` + `stdio_server`) built from `list[WikiOperation]`.
- Refactor `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py`:
  - extract the store/federation/ledger/vault resolution into `_open_mcp_context(root) -> _McpContext`
    shared by both transports (behaviour byte-identical to today);
  - `create_wiki_mcp_server(root, *, transport=None) -> StdioMCPServer | WikiSDKServer`;
  - `_resolve_transport(transport)` and `_framework_available()` probe;
  - `main()` unchanged in shape (`asyncio.run(server.start())` works for both).
- SDK path registers `build_wiki_operations(...)` + `build_structural_operations(...)` +
  `build_vault_ingest_operation(...)` when a vault resolves. Obsidian toolkit tools are
  framework-only: log one warning and skip them.
- SDK path must import neither `parrot.mcp.*` nor `parrot_tools.*` nor `parrot.tools.*`.
- Tests: `test_mcp_sdk_path_selected`, `test_mcp_framework_path_preserved`, SDK/framework
  tool-surface parity against the golden file, a subprocess test with `parrot.mcp` genuinely
  unimportable.
- Update the 5 **pre-existing stale** expectations in the MCP test files (see Codebase Contract —
  they already fail on `dev` @ `63cc2198e` because structural + ledger tools and `sqlite_policy`
  were added after the tests were written). Update expectations only; do not change server behaviour to fit them.

**NOT in scope**:
- Creating the operations layer or the `parrot_tools.wiki` wrappers (TASK-3260..3263).
- `resolve_setting` itself (TASK-3264) — only consume it.
- Changing tool names, descriptions or input schemas (golden file is the contract).
- `.claude/settings.local.json` / installer changes — entries keep their shape.
- Any change to `parrot/mcp/*` (core MCP framework) — unchanged by spec.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_sdk.py` | CREATE | `WikiSDKServer` over `mcp.server.lowlevel.Server` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | `_McpContext`, `_open_mcp_context`, transport selection |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_transport.py` | CREATE | SDK/framework selection + parity tests |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py` | MODIFY | fix 2 stale expectations |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py` | MODIFY | fix stale `BASE_TOOLS` |
| `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py` | MODIFY | fix stale `BASE_TOOLS` |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `63cc2198e` (2026-09-15). `mcp_server.py` is edited by
> TASK-3262 (lazy repoint of `create_wiki_tools` / `create_structural_tools` /
> `VaultIngestTool`) and `project.py` by TASK-3264 **before** this task — re-verify
> those anchors at execution time.

### Verified Imports
```python
# mcp SDK 1.29.0 (verified: importlib.metadata.version("mcp") == "1.29.0", this venv)
from mcp.server.lowlevel import Server          # Server.__init__(self, name: str, version: str | None = None, instructions: str | None = None, ...)
from mcp.server.stdio import stdio_server       # stdio_server(stdin=None, stdout=None) -> async ctx manager yielding (read_stream, write_stream)
import mcp.types as types                       # types.Tool fields: name, title, description, inputSchema, outputSchema, ...
                                                # types.TextContent fields: type, text, annotations, meta
                                                # types.CallToolResult fields: meta, content, structuredContent, isError
# Server API (verified via inspect.signature in this venv):
#   Server.list_tools(self)                        -> decorator for `async def () -> list[types.Tool]`
#   Server.call_tool(self, *, validate_input=True) -> decorator for `async def (name: str, arguments: dict) -> ...`;
#       a returned `types.CallToolResult` is passed through verbatim; input is jsonschema-validated
#       against the cached Tool.inputSchema when validate_input=True
#   Server.create_initialization_options(self, notification_options=None, experimental_capabilities=None) -> InitializationOptions
#   Server.run(self, read_stream, write_stream, initialization_options, raise_exceptions=False, stateless=False)

from parrot.knowledge.wiki.operations import OperationResult, WikiOperation, build_wiki_operations, build_vault_ingest_operation  # created by TASK-3260 — verify names
from parrot.knowledge.wiki.structural.operations import build_structural_operations                                          # created by TASK-3261 — verify
from parrot.knowledge.wiki.project import resolve_setting                                                                     # created by TASK-3264 — verify
from parrot.knowledge.wiki.project import (WikiConfigError, find_project_root, load_effective_config, sqlite_policy_from_config)  # mcp_server.py:21-26
from parrot.knowledge.wiki.store import create_wiki_store                                                                     # mcp_server.py:27
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py  (293 lines, pre-3262)
_INVOCATION_CWD = os.getcwd()                                         # line 42
def _ensure_stderr_logging() -> None: ...                             # line 45
def _run_sync(coro: Any) -> Any: ...                                  # line 68
def create_wiki_mcp_server(root: Path) -> StdioMCPServer: ...         # line 91
#   lazy framework imports under contextlib.redirect_stdout(sys.stderr):
#     from parrot.mcp.local_server import StdioMCPServer; from parrot.mcp.server_base import LocalServerConfig
#   store: arangodb branch (resolve_arango_params) vs create_wiki_store(storage, wiki_name=, backend=, sqlite_policy=)
#   federation: resolve_namespaces(root, config) via _run_sync → (handles, skipped)
#   ledger: find_shared_root(root) → LedgerService.from_root(root) → NamespaceHandle("ledger", read_only=True)
#   read_store = FederatedWikiStore(store, config.wiki_name, handles, skipped) if handles or skipped
#   tools = create_wiki_tools(read_store, root=root, config=config, ledger_service=ledger_service)   # line 202
#   tools += create_structural_tools(read_store, root, config)
#   vault = resolve_vault_dir(root, config) → ObsidianToolkit(vault_path=vault).get_tools_sync() + VaultIngestTool(store, root=root, config=config)
#   description string grows with namespaces / vault
    server = StdioMCPServer(LocalServerConfig(name="wikitoolkit", version="1.0.0", description=description))  # line 242
    return server                                                     # line 252
def main() -> None: ...                                               # line 255
    server = create_wiki_mcp_server(root)                             # line 284
    asyncio.run(server.start())                                       # line 289

# packages/ai-parrot/src/parrot/mcp/local_server.py  (core)
class StdioMCPServer(LocalMCPServerBase): ...                         # line 36
    async def start(self): ...                                        # line 44
# packages/ai-parrot/src/parrot/mcp/server_base.py
class LocalServerConfig:  name / version / description               # line 48
class MCPServerBase(ABC):  self.config (line 61); self.tools: dict[str, MCPToolAdapter] (line 62); register_tools (line 75)
# packages/ai-parrot/src/parrot/mcp/adapter.py — the result encoding the SDK path MUST mirror
class MCPToolAdapter:                                                 # line 8
    def to_mcp_tool_definition(self) -> dict[str, Any]: ...           # line 27  (args_schema.model_json_schema(); `confirm` injected when requires_confirmation)
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]: ...  # line 59 (non-ToolResult → str(result); exception → "Error executing tool: {e!s}", isError)
    def _toolresult_to_mcp(self, result: ToolResult) -> dict[str, Any]: ...    # line 108
#     success: str → text; dict → json.dumps(indent=2, default=str); other → str();
#              metadata → extra text "\nMetadata: {json.dumps(metadata, indent=2, default=str)}"
#     error:   "Error: {result.error or 'Unknown error occurred'}"; isError = status != "success"
```

### Tests that must pass after this task
```text
packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py
  TestWikiMCPServerIntegration::test_initialize_and_list_tools    (STALE today: line 90 expects only the 6 wiki tools)
  TestWikiMCPServerIntegration::test_not_in_repo_exits_with_error
  TestCreateWikiMcpServerArangoBackend::test_arangodb_backend_passes_connection_params  (monkeypatches mcp_server_module.create_wiki_store — keep that module global; asserts arango_params["host"] truthy → after TASK-3264 host is required: set ARANGODB_HOST via monkeypatch.setenv if the test does not)
  TestCreateWikiMcpServerArangoBackend::test_sqlite_backend_unaffected_by_arango_branch (STALE today: line 171 expects kwargs == {}; sqlite_policy is passed since FEAT-5xx)
packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py   BASE_TOOLS (line 20) STALE — server.tools also has 3 structural tools
  (asserts `server.tools["wiki_query"].tool._store` — framework path returns MCPToolAdapter with .tool)
packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py        BASE_TOOLS STALE (line 26); asserts obsidian_* tools, `server.config.description` contains "vault"
Baseline on dev @ 63cc2198e: 5 failed, 11 passed (the 5 are the STALE ones above).
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.mcp_sdk`~~ / ~~`WikiSDKServer`~~ — created by this task.
- ~~`mcp.server.fastmcp` usage in this repo for the wiki~~ — do NOT use FastMCP; it infers schemas from
  function signatures and would change the published `inputSchema`. Use the low-level `Server`.
- ~~`StdioMCPServer.tool_names()`~~ — no such method; framework tool names are `set(server.tools)`.
- ~~`WIKI_MCP_TRANSPORT`~~ — new env key introduced here; not read anywhere today.
- ~~`.mcp.json` at the repo root~~ — the wikitoolkit entry lives in `.claude/settings.local.json`.
- ~~An SDK equivalent of `ObsidianToolkit`~~ — Obsidian tools are framework-only.

---

## Implementation Notes

### Key Constraints
- **stdout is the JSON-RPC channel.** Keep every `contextlib.redirect_stdout(sys.stderr)` block and
  both `_ensure_stderr_logging()` calls exactly as today, on both paths.
- **Tool surface parity**: for the shared tools, SDK `types.Tool(name, description, inputSchema)` must equal
  the golden file entries (`packages/ai-parrot/tests/knowledge/wiki/fixtures/wiki_tool_schemas.golden.json`,
  created by TASK-3260/3261). If an operation has `requires_confirmation=True`, inject the same `confirm`
  property/required entry as `MCPToolAdapter.to_mcp_tool_definition` and enforce it in `call_tool`.
- **Result parity**: text content must be byte-identical to `MCPToolAdapter._toolresult_to_mcp` for the same
  `OperationResult`/`str`, so Claude Code sees the same output on either transport.
- `find_spec` returns the already-imported module's spec when a name is in `sys.modules`, so in-process
  tests must force the path via `transport=` / env / monkeypatching `_framework_available`; the genuine
  "unimportable" proof is the subprocess test with a blocking `sys.meta_path` finder.
- `create_wiki_store` must stay a module-level name in `mcp_server.py` (tests monkeypatch it).
- Async-first: `WikiSDKServer.start()` is `async`; `main()` keeps `asyncio.run(server.start())`.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/adapter.py:27-148` — schema + result encoding to mirror.
- `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py:91-252` — body being split.

---

## Implementation Blueprint

### Steps (in order)
1. Re-verify operations/`resolve_setting` names and the post-3262 `mcp_server.py` anchors — *why*: three upstream tasks changed them.
2. Run the MCP test files to record the baseline (expect the 5 stale failures) — *why*: distinguishes stale from regression.
3. Write `mcp_sdk.py` — *why*: self-contained, testable without touching the server module.
4. Extract `_McpContext` + `_open_mcp_context` from `create_wiki_mcp_server` with **no behaviour change**; run the MCP tests again (same results) — *why*: refactor proven before adding the branch.
5. Add `_framework_available`, `_resolve_transport`, the SDK branch, and the new return type — *why*: G5.
6. Fix the stale expectations; write `test_mcp_transport.py`; run Acceptance Criteria commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_sdk.py` (CREATE — block 1/2)
```python
"""Framework-free stdio MCP server for the wiki (FEAT-540, spec Module 5).

Serves :class:`~parrot.knowledge.wiki.operations.WikiOperation` objects over the
``mcp`` SDK's low-level server, so ``wikitoolkit mcp`` works when the agent
framework (``parrot.mcp`` / ``parrot_tools``) is not installed. Tool names,
descriptions, input schemas and text output mirror ``parrot.mcp.adapter.MCPToolAdapter``.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from parrot.knowledge.wiki.operations import OperationResult, WikiOperation

logger = logging.getLogger(__name__)

_CONFIRM_DESCRIPTION = (
    "This operation is destructive. Set true ONLY after the "
    "user has explicitly approved it; the call is rejected "
    "otherwise."
)


def operation_input_schema(operation: WikiOperation) -> dict[str, Any]:
    """Build the MCP ``inputSchema`` exactly as ``MCPToolAdapter.to_mcp_tool_definition`` does.

    Args:
        operation: The operation to describe.

    Returns:
        JSON schema dict (with the ``confirm`` guard when required).
    """
    schema = operation.args_schema.model_json_schema()
    # FILL IN: confirm injection — bounded by adapter.py:39-51 (setdefault type/properties,
    # add "confirm" boolean with _CONFIRM_DESCRIPTION, append to required once)
    return schema


def result_to_content(value: Any) -> types.CallToolResult:
    """Encode an operation's return value like ``MCPToolAdapter`` (adapter.py:82-148).

    Args:
        value: ``OperationResult`` or a bare value (``str`` for text-only operations).

    Returns:
        The MCP call result.
    """
    if not isinstance(value, OperationResult):
        return types.CallToolResult(content=[types.TextContent(type="text", text=str(value))], isError=False)
    # FILL IN: success/error branches — bounded by adapter.py:108-148 byte-for-byte
    # (str → text; dict → json.dumps(indent=2, default=str); else str(); metadata tail;
    # error → f"Error: {error or 'Unknown error occurred'}"; isError = status != "success")
    raise NotImplementedError
```
**Why**: two pure helpers make parity unit-testable without a stdio loop.

### `mcp_sdk.py` (CREATE — block 2/2, appended)
```python
class WikiSDKServer:
    """Stdio MCP server built from wiki operations (no agent framework)."""

    def __init__(self, name: str, version: str, description: str, operations: Sequence[WikiOperation]) -> None:
        """Register ``operations`` on a low-level ``mcp`` server.

        Args:
            name: Server name reported at initialize (``"wikitoolkit"``).
            version: Server version string.
            description: Human description (used as server instructions).
            operations: Operations to expose; names must be unique.

        Raises:
            ValueError: If two operations share a name.
        """
        self.logger = logging.getLogger(__name__)
        self.name = name
        self.version = version
        self.description = description
        self.tools: dict[str, WikiOperation] = {}
        for op in operations:
            if op.name in self.tools:
                raise ValueError(f"duplicate wiki operation name: {op.name!r}")
            self.tools[op.name] = op
        self._server: Server = Server(name, version=version, instructions=description)
        self._server.list_tools()(self._list_tools)
        self._server.call_tool(validate_input=True)(self._call_tool)

    def tool_names(self) -> list[str]:
        """Return registered tool names in registration order."""
        return list(self.tools)

    async def _list_tools(self) -> list[types.Tool]:
        """MCP ``tools/list`` handler."""
        return [
            types.Tool(name=op.name, description=op.description, inputSchema=operation_input_schema(op))
            for op in self.tools.values()
        ]

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        """MCP ``tools/call`` handler — validate, run, encode.

        Args:
            name: Tool name.
            arguments: Raw JSON arguments.

        Returns:
            Encoded result; errors are reported in-band (``isError=True``), never raised.
        """
        # FILL IN: unknown name → in-band error; pop "confirm" and reject unconfirmed calls when
        # requires_confirmation (adapter.py:62-76 text); validate via op.args_schema.model_validate(arguments)
        # then await op.handler(**validated.model_dump()) — bounded by: exceptions become
        # f"Error executing tool: {exc!s}" with isError=True (adapter.py:96-106), logged via self.logger.
        raise NotImplementedError

    async def start(self) -> None:
        """Serve JSON-RPC over stdin/stdout until the client disconnects."""
        async with stdio_server() as (read_stream, write_stream):
            await self._server.run(read_stream, write_stream, self._server.create_initialization_options())
```
**Why**: `self.tools` mirrors `MCPServerBase.tools` so tests can compare `set(server.tools)` across paths.
Validation uses the Pydantic model (defaults applied) rather than raw jsonschema only, because the handlers
expect the same defaults `AbstractTool._execute` received. `model_dump()` vs `exclude_unset`: FILL IN if a
handler distinguishes unset from default — bounded by golden parity + existing wrapper behaviour.

### `mcp_server.py` (MODIFY — block 1: context extraction)
```python
# FILL IN: anchor — insert above `def create_wiki_mcp_server(` (verified pre-3262: mcp_server.py:91;
# occurrences: 1 via grep -c '^def create_wiki_mcp_server' — re-verify after TASK-3262)
from dataclasses import dataclass, field   # add to top-level imports (stdlib)


@dataclass
class _McpContext:
    """Everything both transports need, resolved once per server build."""

    root: Path
    config: Any                 # WikiProjectConfig
    store: Any                  # local BaseWikiStore (writes / vault ingest)
    read_store: Any             # local or FederatedWikiStore (reads)
    ledger_service: Any | None
    handles: list[Any] = field(default_factory=list)
    vault: Path | None = None
    description: str = ""


def _open_mcp_context(root: Path) -> _McpContext:
    """Resolve config, store, federation, ledger overlay and vault for ``root``.

    Moved verbatim from ``create_wiki_mcp_server`` (FEAT-540) so the framework
    and SDK transports share one resolution path.

    Args:
        root: Wiki project root.

    Returns:
        The resolved context.
    """
    # FILL IN: move the body from `config = load_effective_config(root).config` through the
    # `description` / `resolve_vault_dir` computation VERBATIM (keep redirect_stdout blocks, keep
    # module-global `create_wiki_store` so tests can monkeypatch it). Do NOT import ObsidianToolkit
    # or VaultIngestTool here — bounded by: this function runs on the SDK path too.
    raise NotImplementedError
```
**Why**: one resolution path guarantees identical federation/ledger behaviour on both transports.

### `mcp_server.py` (MODIFY — block 2: transport selection)
```python
# REPLACE the signature `def create_wiki_mcp_server(root: Path) -> StdioMCPServer:` (occurrences: 1)
TransportName = Literal["auto", "framework", "sdk"]          # add `Literal` to the typing import


def _framework_available() -> bool:
    """Probe whether ``parrot.mcp`` and ``parrot_tools.wiki`` can be imported (no import side effects kept)."""
    import importlib.util

    try:
        return all(importlib.util.find_spec(m) is not None for m in ("parrot.mcp", "parrot_tools.wiki"))
    except (ImportError, ValueError):
        return False


def _resolve_transport(transport: TransportName | None) -> Literal["framework", "sdk"]:
    """Explicit argument → ``WIKI_MCP_TRANSPORT`` → ``auto`` probe.

    Raises:
        ValueError: For an unknown transport name.
    """
    from parrot.knowledge.wiki.project import resolve_setting

    chosen = str(resolve_setting("WIKI_MCP_TRANSPORT", default="auto", explicit=transport)).lower()
    # FILL IN: validate against {"auto","framework","sdk"}; "auto" → "framework" if _framework_available() else "sdk";
    # "framework" requested but unavailable → raise ImportError naming ai-parrot-tools — bounded by G5.
    raise NotImplementedError


def create_wiki_mcp_server(root: Path, *, transport: TransportName | None = None) -> StdioMCPServer | WikiSDKServer:
    """Build the wikitoolkit MCP server on the selected transport.

    Args:
        root: Wiki project root.
        transport: ``"framework"`` (``parrot.mcp`` StdioMCPServer), ``"sdk"`` (``mcp`` SDK), or
            ``"auto"``/``None`` (env ``WIKI_MCP_TRANSPORT``, then import probe).

    Returns:
        A ``StdioMCPServer`` (framework) or ``WikiSDKServer`` (sdk); both expose ``tools`` and ``start()``.
    """
    ctx = _open_mcp_context(root)
    if _resolve_transport(transport) == "sdk":
        return _build_sdk_server(ctx)
    return _build_framework_server(ctx)
```
Add `if TYPE_CHECKING: from parrot.knowledge.wiki.mcp_sdk import WikiSDKServer` next to the existing
`StdioMCPServer` TYPE_CHECKING import (mcp_server.py:30-33).

### `mcp_server.py` (MODIFY — block 3: the two builders)
```python
def _build_framework_server(ctx: _McpContext) -> StdioMCPServer:
    """Today's path: parrot_tools.wiki AbstractTools on parrot.mcp's StdioMCPServer."""
    # FILL IN: the remaining original body — lazy parrot.mcp imports under redirect_stdout,
    # create_wiki_tools/create_structural_tools from parrot_tools.wiki (as left by TASK-3262/3263),
    # ObsidianToolkit + VaultIngestTool when ctx.vault, StdioMCPServer(LocalServerConfig(name="wikitoolkit",
    # version="1.0.0", description=ctx.description)) — bounded by: byte-identical behaviour to pre-task.
    raise NotImplementedError


def _build_sdk_server(ctx: _McpContext) -> WikiSDKServer:
    """Framework-free path: WikiOperations on the mcp SDK stdio server."""
    from parrot.knowledge.wiki.mcp_sdk import WikiSDKServer
    from parrot.knowledge.wiki.operations import build_vault_ingest_operation, build_wiki_operations
    from parrot.knowledge.wiki.structural.operations import build_structural_operations

    operations = build_wiki_operations(ctx.read_store, root=ctx.root, config=ctx.config, ledger_service=ctx.ledger_service)
    operations += build_structural_operations(ctx.read_store, ctx.root, ctx.config)
    description = ctx.description
    if ctx.vault is not None:
        operations.append(build_vault_ingest_operation(ctx.store, ctx.root, ctx.config))
        logging.getLogger(__name__).warning(
            "Obsidian vault tools need the agent framework (ai-parrot-tools); serving vault_ingest only"
        )
        # FILL IN: description wording for the SDK vault case — bounded by: must still contain "vault"
    _ensure_stderr_logging()
    return WikiSDKServer("wikitoolkit", "1.0.0", description, operations)
```
**Why**: vault_ingest writes to the *local* store (`ctx.store`), reads use `ctx.read_store` — same split as today (mcp_server.py:202 vs VaultIngestTool(store, ...)).

### Stale test expectations (MODIFY)
```python
# test_mcp_server.py:90 — occurrences: 1 (grep -c 'assert names == {' test_mcp_server.py)
# test_mcp_server_namespaces.py:20 / test_mcp_server_vault.py — `BASE_TOOLS = {` occurrences: 1 each
# FILL IN: expected set = the 6 wiki tools + {"wiki_symbol_lookup","wiki_code_outline","wiki_blast_radius"}
#   (ledger tools appear only under a git shared root — tmp_path fixtures have none; verify with a run).
# test_mcp_server.py:171 `assert captured["kwargs"] == {}` → assert only "sqlite_policy" in kwargs and no arango keys.
# — bounded by: fix expectations to the CURRENT intended surface; never change server behaviour to satisfy them.
```

### `packages/ai-parrot/tests/knowledge/wiki/test_mcp_transport.py` (CREATE)
```python
"""FEAT-540 TASK-3265 — wiki MCP server dual transport."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.knowledge.wiki import mcp_server
from parrot.knowledge.wiki.project import WikiProjectConfig, save_project_config

GOLDEN = Path(__file__).parent / "fixtures" / "wiki_tool_schemas.golden.json"


@pytest.fixture
def plain_project(tmp_path: Path) -> Path:
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="plain"))
    return tmp_path


def test_mcp_sdk_path_selected(plain_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """auto + framework unavailable → WikiSDKServer with the same tool names."""
    from parrot.knowledge.wiki.mcp_sdk import WikiSDKServer

    monkeypatch.setattr(mcp_server, "_framework_available", lambda: False)
    server = mcp_server.create_wiki_mcp_server(plain_project)
    assert isinstance(server, WikiSDKServer)
    framework = mcp_server.create_wiki_mcp_server(plain_project, transport="framework")
    assert set(server.tools) == set(framework.tools)


def test_mcp_framework_path_preserved(plain_project: Path) -> None:
    """parrot.mcp importable → StdioMCPServer (spec §4)."""
    from parrot.mcp.local_server import StdioMCPServer

    assert isinstance(mcp_server.create_wiki_mcp_server(plain_project), StdioMCPServer)


def test_env_override_selects_sdk(plain_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # FILL IN: monkeypatch.setenv("WIKI_MCP_TRANSPORT", "sdk") → WikiSDKServer; invalid value → ValueError
    ...


@pytest.mark.asyncio
async def test_sdk_tool_definitions_match_golden(plain_project: Path) -> None:
    # FILL IN: server = create_wiki_mcp_server(plain_project, transport="sdk"); tools = await server._list_tools();
    # compare name/description/inputSchema to GOLDEN entries by name — bounded by spec §5 byte-identical schemas.
    ...


@pytest.mark.asyncio
async def test_sdk_result_encoding_matches_adapter() -> None:
    # FILL IN: for OperationResult(result="x"), (result={"a": 1}), (success=False, status="error", error="boom"),
    # compare result_to_content(...) text/isError with MCPToolAdapter._toolresult_to_mcp(ToolResult(...)).
    ...


def test_server_starts_with_parrot_mcp_unimportable(plain_project: Path) -> None:
    """Subprocess: a meta_path finder blocks parrot.mcp / parrot_tools; SDK server still builds."""
    # FILL IN: run [sys.executable, "-c", script] where script installs a MetaPathFinder raising
    # ModuleNotFoundError for names starting with "parrot.mcp" / "parrot_tools" / "parrot.tools", then
    # builds create_wiki_mcp_server(Path(root)) and prints json.dumps(sorted(server.tools)) plus
    # type(server).__name__; assert "WikiSDKServer" and the wiki tool names — bounded by G5.
    ...
```

### FILL IN checklist
- [ ] `mcp_sdk.operation_input_schema` — confirm injection identical to adapter.py:39-51.
- [ ] `mcp_sdk.result_to_content` — byte-identical to adapter.py:108-148.
- [ ] `WikiSDKServer._call_tool` — unknown tool, confirm guard, pydantic validation, in-band exceptions; unset-vs-default dump.
- [ ] `_open_mcp_context` — verbatim move, module-global `create_wiki_store` preserved.
- [ ] `_resolve_transport` — validation + "framework requested but unavailable" error.
- [ ] `_build_framework_server` — rest of original body, unchanged behaviour.
- [ ] `_build_sdk_server` — vault description wording contains "vault".
- [ ] Stale test expectations (3 files) — current intended surface.
- [ ] `test_mcp_transport.py` — env override, golden parity, encoding parity, subprocess unimportable.

---

## Addendum — repo-root `tests/` MCP consumers (review, 2026-09-15)

Besides `packages/ai-parrot/tests/knowledge/wiki/test_mcp_server*.py`, the repo-root
test tree (run by CI) exercises `create_wiki_mcp_server` / `parrot.knowledge.wiki.mcp_server`
(verified with `git ls-files tests | xargs grep -lE "create_wiki_mcp_server|wiki\.mcp_server"`):

- `tests/knowledge/wiki/test_mcp_server_ledger.py`
- `tests/knowledge/wiki/test_mcp_server_structural.py`
- `tests/knowledge/wiki/test_ledger_integration.py`
- `tests/knowledge/wiki/test_namespaces_e2e.py`
- `tests/knowledge/wiki/test_structural_e2e.py`
- `tests/knowledge/wiki/test_env_call_sites.py` (`test_mcp_server_uses_effective_config` :61)

Read them before refactoring `create_wiki_mcp_server` into `_open_mcp_stores`: any
`monkeypatch.setattr(mcp_server_module, "<name>", ...)` target (e.g.
`create_wiki_store`, `load_effective_config`) must remain a module-level name that
the refactored code still looks up through the module's globals. They must pass on
the framework path unchanged; add no SDK-path expectations to them.

Note: the arango host test fix in `test_mcp_server.py` is owned by TASK-3264 — do
not duplicate it here; if TASK-3264 already landed it, leave it.

---

## Acceptance Criteria

- [ ] The wiki MCP server starts and serves the same tool names with `parrot.mcp` unimportable (subprocess test), and still returns `StdioMCPServer` when it is (spec §5).
- [ ] SDK-path `tools/list` name/description/inputSchema match the golden file for every shared tool.
- [ ] SDK-path text output matches `MCPToolAdapter` for success, dict, metadata and error results.
- [ ] `create_wiki_mcp_server(root)` with no arguments behaves exactly as before on the framework path (all pre-existing, non-stale MCP tests pass unchanged).
- [ ] `grep -n "parrot.mcp\|parrot_tools\|parrot.tools" packages/ai-parrot/src/parrot/knowledge/wiki/mcp_sdk.py` → no matches.
- [ ] `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest packages/ai-parrot/tests/knowledge/wiki/test_mcp_server.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_namespaces.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_server_vault.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_transport.py -v` → all pass (0 failures; baseline was 5 stale failures).
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/mcp_sdk.py packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py packages/ai-parrot/tests/knowledge/wiki/test_mcp_transport.py` clean.
- [ ] Google-style docstrings + type hints on every new function/class.
- [ ] Root-tree MCP tests pass: `pytest tests/knowledge/wiki/test_mcp_server_ledger.py tests/knowledge/wiki/test_mcp_server_structural.py tests/knowledge/wiki/test_ledger_integration.py tests/knowledge/wiki/test_namespaces_e2e.py tests/knowledge/wiki/test_structural_e2e.py tests/knowledge/wiki/test_env_call_sites.py -v`

---

## Test Specification

See `test_mcp_transport.py` in the blueprint (spec §4 `test_mcp_sdk_path_selected`,
`test_mcp_framework_path_preserved`), plus the three repaired MCP test files.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3263 and TASK-3264 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-grep every anchor; confirm the operations / `resolve_setting` names created upstream
4. **Update status** in `sdd/tasks/index/graphindex-core-seams.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`
6. **Verify** all acceptance criteria (worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`; never `uv sync` in a worktree)
7. **Move this file** to `sdd/tasks/completed/TASK-3265-wiki-mcp-dual-transport.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: Spec §2 skeleton has `create_wiki_mcp_server(root: Path) -> StdioMCPServer`; this task adds a
keyword-only `transport` argument and widens the return type (additive). Spec open question 3 resolved as
"import probe + explicit argument + `WIKI_MCP_TRANSPORT` env override".
