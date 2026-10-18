"""WikiToolkit MCP server entry point (FEAT-403 Module 6).

Wires the six wiki `AbstractTool` wrappers (`parrot.knowledge.wiki.tools`)
into a core `StdioMCPServer` (`parrot.mcp.local_server`) so `wikitoolkit
mcp` exposes the codebase knowledge graph as a first-class MCP tool —
equal standing with Grep/Read at tool-selection time (see the spec's
Problem Statement for why the Bash-invoked CLI alone was not enough).
"""

from __future__ import annotations

import asyncio
import argparse
import contextlib
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from parrot.knowledge.wiki.project import (
    WikiConfigError,
    find_project_root,
    load_effective_config,
    sqlite_policy_from_config,
)
from parrot.knowledge.wiki.store import create_wiki_store
from parrot.knowledge.wiki.transport import OperationDescriptor, WikiOperationContext, build_operation_descriptors

# Captured now, before create_wiki_mcp_server()/main() below ever import
# parrot.mcp.* (lazily, on purpose) — parrot.mcp's package __init__ pulls
# in navconfig-based settings that chdir() to the installed package's app
# root as a side effect (pre-existing quirk, not introduced here; verified
# against the unmodified main repo). Capturing the real invocation
# directory up front means `wikitoolkit mcp` still resolves it correctly
# even after that happens.
_INVOCATION_CWD = os.getcwd()


def _ensure_stderr_logging() -> None:
    """Force the root logger onto stderr, tearing down any stdout handler
    a transitively-imported dependency may have already attached.

    Some heavy imports below (`parrot.mcp.*`, pulled in lazily by
    `create_wiki_mcp_server()`) drag in navconfig-based settings that
    configure their own root-logger handler pointed at stdout as a side
    effect (pre-existing, not introduced here). A plain
    `logging.basicConfig(stream=sys.stderr)` is not enough to undo that —
    `addHandler()`-style setup isn't a no-op guarded call like
    `basicConfig()` — so handlers are stripped and replaced explicitly.
    Idempotent; safe to call more than once (e.g. before AND after the
    lazy import happens).
    """
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.WARNING)


def _run_sync(coro: Any) -> Any:
    """Run a coroutine from this sync factory, loop or no loop.

    ``main()`` calls the factory before starting the JSON-RPC loop, so
    :func:`asyncio.run` is the normal path. Embedders (and the tests)
    may build a server from inside a running loop, where ``asyncio.run``
    would raise — there the coroutine runs on its own loop in a worker
    thread.

    Args:
        coro: The coroutine to run to completion.

    Returns:
        Whatever the coroutine returned.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


class WikiToolBundle:
    """Everything a transport needs to register for one wiki (FEAT-569).

    ``descriptors`` (and the stores) are built without any framework import.
    The framework ``AbstractTool`` wrappers in ``tools`` / ``vault_tools`` are
    built lazily from ``context`` on first access, so only the framework
    transport pays for (or requires) ``parrot.tools`` / ``parrot_tools``.
    """

    def __init__(
        self,
        tools: list[Any] | None = None,
        vault_tools: list[Any] | None = None,
        description: str = "",
        store: Any = None,
        read_store: Any = None,
        ledger_service: Any | None = None,
        namespace_handles: list[Any] | None = None,
        descriptors: list[OperationDescriptor] | None = None,
        context: WikiOperationContext | None = None,
    ) -> None:
        self._tools = tools
        self._vault_tools = vault_tools
        self.description = description
        self.store = store
        self.read_store = read_store
        self.ledger_service = ledger_service
        self.namespace_handles = namespace_handles if namespace_handles is not None else []
        self.descriptors = descriptors if descriptors is not None else []
        self.context = context

    def _ensure_framework_tools(self) -> None:
        """Build the framework wrappers once, if they were not supplied."""
        if self._tools is None or self._vault_tools is None:
            if self.context is None:
                self._tools, self._vault_tools = [], []
            else:
                self._tools, self._vault_tools = build_framework_tools(self.context)

    @property
    def tools(self) -> list[Any]:
        """Framework ``AbstractTool`` wrappers for the mounted operations (lazy)."""
        self._ensure_framework_tools()
        return self._tools  # type: ignore[return-value]

    @tools.setter
    def tools(self, value: list[Any]) -> None:
        self._tools = value

    @property
    def vault_tools(self) -> list[Any]:
        """Obsidian vault management tools plus ``vault_ingest`` (lazy, framework only)."""
        self._ensure_framework_tools()
        return self._vault_tools  # type: ignore[return-value]

    @vault_tools.setter
    def vault_tools(self, value: list[Any]) -> None:
        self._vault_tools = value


async def abuild_wiki_tools(
    root: Path,
    config: Any,
    *,
    ledger_dir: Path | None = None,
    read_repair: bool = True,
    include_bulk_tools: bool = False,
) -> WikiToolBundle:
    """Assemble the wiki tool surface on the current event loop.

    Args:
        root: Wiki project root (repo root, or the server-side wiki directory).
        config: Effective ``WikiProjectConfig``.
        ledger_dir: Explicit ledger directory, or ``None`` for stdio root discovery.
        read_repair: Whether structural tools may repair from local source files.
        include_bulk_tools: Whether to include server-only bulk and sync tools.

    Returns:
        The assembled bundle; callers own :func:`close_bundle`.
    """
    # NOTE: storage_dir is config.storage_path(root) (".parrot/wiki" by
    # default, or wherever wiki.json points it), NOT a bare "root/.parrot"
    # — matching how `wikitoolkit build`/`query`/etc. resolve the plane
    # (see cli.py:_open_store). The arangodb backend additionally needs
    # connection params/database/analyzer — mirrored from _open_store()
    # so `wikitoolkit mcp` works against the same backends the CLI does.
    storage = config.storage_path(root)
    if config.backend == "arangodb":
        from parrot.knowledge.wiki.project import resolve_arango_params

        store = create_wiki_store(
            storage,
            wiki_name=config.wiki_name,
            backend="arangodb",
            arango_params=resolve_arango_params(config),
            database=config.arango_database or "",
            text_analyzer=config.arango_text_analyzer,
        )
        initialize_result = store.initialize()
        if asyncio.iscoroutine(initialize_result):
            await initialize_result
    else:
        storage.mkdir(parents=True, exist_ok=True)
        store = create_wiki_store(
            storage,
            wiki_name=config.wiki_name,
            backend=config.backend,
            sqlite_policy=sqlite_policy_from_config(config),
        )

    # Federated namespaces (FEAT-450): the read tools inherit them
    # through the store they already hold. Resolution runs under the same
    # stdout-redirect discipline as every other import here — opening a
    # namespace can pull in navconfig/asyncdb, which print to stdout.
    read_store = store
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.knowledge.wiki.federation import FederatedWikiStore, resolve_namespaces

        try:
            handles, skipped = await resolve_namespaces(root, config)
        except Exception as exc:  # noqa: BLE001 — namespaces are optional
            logging.getLogger(__name__).warning("Could not resolve wiki namespaces: %s", exc)
            handles, skipped = [], []

    # FEAT-566: Initialize ledger service for ledger tools. An explicit
    # ledger directory is for a server without a checkout, so it bypasses
    # shared-root discovery entirely.
    ledger_service = None
    with contextlib.redirect_stdout(sys.stderr):
        if ledger_dir is not None:
            from parrot.knowledge.wiki.ledger.service import LedgerService

            ledger_service = LedgerService.from_dir(
                ledger_dir,
                sqlite_policy=sqlite_policy_from_config(config),
            )
        else:
            from parrot.knowledge.wiki.project import find_shared_root

            if find_shared_root(root) is not None:
                try:
                    from parrot.knowledge.wiki.ledger.service import LedgerService

                    ledger_service = LedgerService.from_root(root)
                except Exception as exc:  # noqa: BLE001 — ledger is optional
                    logging.getLogger(__name__).warning("Could not initialize ledger service: %s", exc)

    # FEAT-566: Mount ledger as a read-only overlay namespace. The config's
    # `store` field is set only to satisfy WikiNamespaceConfig's "exactly
    # one source" validator — resolve_namespaces() is never asked to open
    # this entry; the NamespaceHandle wraps the already-open LedgerStore
    # directly.
    if ledger_service is not None:
        with contextlib.redirect_stdout(sys.stderr):
            from parrot.knowledge.wiki.federation import NamespaceHandle
            from parrot.knowledge.wiki.project import WikiNamespaceConfig

            ledger_dir_eff = ledger_dir or ledger_service.shared_root / ".parrot" / "ledger"
            ledger_config = WikiNamespaceConfig(
                store=str(ledger_dir_eff),
                description="SDD work ledger (issues, tasks, specs, insights)",
                weight=0.5,
                overlay_prefixes=["issue", "task", "spec", "insight"],
            )
            handles.append(
                NamespaceHandle(
                    name="ledger",
                    store=ledger_service.store,
                    config=ledger_config,
                    storage_dir=ledger_dir_eff,
                    read_only=True,
                )
            )

    # FEAT-600: mount the SQL schema plane as a read-only overlay (same shape as the ledger block above).
    # Mount only when a plane already exists — never grow `.parrot/schema/` from a bare directory (tool counts, AC11).
    schema_service = None
    if ledger_dir is None:
        with contextlib.redirect_stdout(sys.stderr):
            from parrot.knowledge.wiki.project import find_shared_root

            shared_root = find_shared_root(root)
            if shared_root is not None and config.schema_plane.enabled and config.schema_path(shared_root).exists():
                try:
                    from parrot.knowledge.wiki.schema.service import SchemaPlaneService

                    schema_service = SchemaPlaneService.from_root(root)
                except Exception as exc:  # noqa: BLE001 — the plane is optional
                    logging.getLogger(__name__).warning("Could not initialize schema plane: %s", exc)
    if schema_service is not None:
        with contextlib.redirect_stdout(sys.stderr):
            from parrot.knowledge.wiki.federation import NamespaceHandle
            from parrot.knowledge.wiki.project import WikiNamespaceConfig

            schema_dir = schema_service.plane_dir
            schema_config = WikiNamespaceConfig(
                store=str(schema_dir),
                description="SQL schema plane (sources, schemas, tables)",
                weight=0.5,
                overlay_prefixes=["source", "schema", "table"],
            )
            handles.append(
                NamespaceHandle(
                    name="schema",
                    store=schema_service.store,
                    config=schema_config,
                    storage_dir=schema_dir,
                    read_only=True,
                )
            )

    if handles or skipped:
        read_store = FederatedWikiStore(store, config.wiki_name, handles, skipped)
    # Descriptors are built from the operations registry and the stores/services
    # above.  No framework wrapper (parrot.tools / parrot_tools) is imported
    # here; those are built lazily by ``build_framework_tools`` for the
    # framework transport only.
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.knowledge.wiki.decisions.factory import make_decision_service_factory
        from parrot.knowledge.wiki.project import resolve_vault_dir
        from parrot.knowledge.wiki.structural.factory import make_structural_service_factory

        vault = resolve_vault_dir(root, config)
        context = WikiOperationContext(
            store=store,
            read_store=read_store,
            root=root,
            config=config,
            ledger_service=ledger_service,
            schema_service=schema_service,
            structural_service_factory=make_structural_service_factory(
                read_store, root, config, read_repair=read_repair
            ),
            decision_service_factory=make_decision_service_factory(read_store, root, config),
            include_bulk_tools=include_bulk_tools,
            vault_dir=vault,
            read_repair=read_repair,
        )

    description = (
        "Codebase knowledge graph — query, explore, remember, and look up "
        "symbols (functions/classes/methods), outlines, and blast radius"
    )
    if handles:
        names = ", ".join(sorted(h.name for h in handles))
        description += f" — federating {len(handles)} namespace(s): {names}"
    if vault is not None:
        description += f" — plus Obsidian vault management for {vault.name!r}"

    return WikiToolBundle(
        description=description,
        store=store,
        read_store=read_store,
        ledger_service=ledger_service,
        namespace_handles=list(handles),
        descriptors=build_operation_descriptors(context),
        context=context,
    )


def build_framework_tools(context: WikiOperationContext) -> tuple[list[Any], list[Any]]:
    """Build the framework ``AbstractTool`` wrappers for the framework transport.

    Imports ``parrot_tools.wiki`` and ``parrot.tools``; the SDK transport never
    calls this.

    Args:
        context: Transport-neutral operation context.

    Returns:
        ``(tools, vault_tools)``: the wiki/structural/bulk/decision/schema
        tools, and the Obsidian toolkit tools plus ``vault_ingest`` (empty
        when the project has no vault).
    """
    root, config, read_store, store = context.root, context.config, context.read_store, context.store
    from parrot.knowledge.wiki.tools import create_wiki_tools

    tools = create_wiki_tools(read_store, root=root, config=config, ledger_service=context.ledger_service)

    # FEAT-498: symbol-plane tools share the same federated read store.
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.knowledge.wiki.structural import create_structural_tools

        tools = tools + create_structural_tools(read_store, root, config, read_repair=context.read_repair)

    if context.include_bulk_tools:
        from parrot.knowledge.wiki.tools import create_bulk_tools

        tools = tools + create_bulk_tools(store, root, config)

    # FEAT-578: decision-plane tools share the same read store.
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.knowledge.wiki.decisions import create_decision_tools

        tools = tools + create_decision_tools(read_store, root, config)

    # FEAT-600: schema-plane tools share read_store; [] when no plane is mounted (AC11).
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.knowledge.wiki.schema.tools import create_schema_tools

        tools = tools + create_schema_tools(read_store, root, config, context.schema_service)

    # Obsidian vault exposure: when the project has a vault, register the full
    # ObsidianToolkit plus the wiki-side vault_ingest tool.
    vault_tools: list[Any] = []
    if context.vault_dir is not None:
        with contextlib.redirect_stdout(sys.stderr):
            from parrot.knowledge.wiki.tools import VaultIngestTool
            from parrot.tools.obsidian import ObsidianToolkit

            toolkit = ObsidianToolkit(vault_path=context.vault_dir)
            vault_tools = list(toolkit.get_tools_sync())
            vault_tools.append(VaultIngestTool(store, root=root, config=config))
    return tools, vault_tools


def build_wiki_tools(
    root: Path,
    config: Any,
    *,
    ledger_dir: Path | None = None,
    read_repair: bool = True,
    include_bulk_tools: bool = False,
) -> WikiToolBundle:
    """Synchronously assemble wiki tools for the stdio transport.

    Args:
        root: Wiki project root.
        config: Effective project configuration.
        ledger_dir: Optional explicit ledger directory.
        read_repair: Whether structural tools may repair local source data.
        include_bulk_tools: Whether to include server-only bulk and sync tools.

    Returns:
        The assembled wiki tool bundle.
    """
    return _run_sync(
        abuild_wiki_tools(
            root,
            config,
            ledger_dir=ledger_dir,
            read_repair=read_repair,
            include_bulk_tools=include_bulk_tools,
        )
    )


async def close_bundle(bundle: WikiToolBundle) -> None:
    """Close every store the bundle owns, logging failures without raising.

    Args:
        bundle: Bundle whose stores should be closed.
    """
    targets = [bundle.store, *(handle.store for handle in bundle.namespace_handles)]
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


def to_sdk_server(descriptors: list[OperationDescriptor], *, name: str) -> Any:
    """Build a low-level MCP SDK stdio server for operation descriptors.

    Args:
        descriptors: Transport-neutral operations to expose.
        name: MCP server name.

    Returns:
        A lazily-imported MCP SDK server with a ``start`` coroutine.
    """
    from mcp import types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    server = Server(name)

    @server.list_tools()
    async def list_tools() -> list[Any]:
        """Return descriptor schemas in the SDK's MCP shape."""
        return [
            types.Tool(
                name=descriptor.name,
                description=descriptor.description,
                inputSchema=descriptor.input_model.model_json_schema(),
            )
            for descriptor in descriptors
        ]

    @server.call_tool()
    async def call_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
        """Execute one operation and serialize its neutral result."""
        descriptor = next((item for item in descriptors if item.name == tool_name), None)
        if descriptor is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Tool not found: {tool_name}")], isError=True
            )
        try:
            result = await descriptor.invoke(descriptor.input_model(**arguments))
        except Exception as exc:  # noqa: BLE001 -- MCP failures are request-scoped
            return types.CallToolResult(content=[types.TextContent(type="text", text=str(exc))], isError=True)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=result.text)],
            structuredContent=result.data,
            isError=result.is_error,
        )

    async def start() -> None:
        """Serve JSON-RPC over the SDK stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    server.start = start
    return server


def _import_framework_server() -> tuple[Any, Any]:
    """Import the framework stdio server classes (the only auto-fallback trigger).

    Returns:
        ``(StdioMCPServer, LocalServerConfig)``.

    Raises:
        ImportError: When ``parrot.mcp`` is unavailable.
    """
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.mcp.local_server import StdioMCPServer
        from parrot.mcp.server_base import LocalServerConfig
    return StdioMCPServer, LocalServerConfig


def _resolve_transport(transport: Literal["auto", "framework", "sdk"]) -> tuple[str, Any]:
    """Pick the concrete transport, falling back to the SDK only for ``auto``.

    Args:
        transport: Requested transport.

    Returns:
        ``("sdk", None)`` or ``("framework", (StdioMCPServer, LocalServerConfig))``.

    Raises:
        ImportError: When ``framework`` is requested and ``parrot.mcp`` is unavailable.
    """
    if transport == "sdk":
        return "sdk", None
    try:
        return "framework", _import_framework_server()
    except ImportError as exc:
        if transport != "auto":
            raise
        logging.getLogger(__name__).warning("framework MCP transport unavailable (%s); falling back to the SDK", exc)
        return "sdk", None


def create_wiki_mcp_server(root: Path, *, transport: Literal["auto", "framework", "sdk"] = "auto") -> Any:
    """Build the wiki stdio MCP server on the selected transport.

    Args:
        root: Wiki project root (directory containing `.parrot/wiki.json`,
            or the nearest `.git` root — see `find_project_root()`).
        transport: ``sdk`` builds from the operation descriptors with the MCP
            SDK and imports no framework module; ``framework`` registers the
            ``AbstractTool`` wrappers on ``StdioMCPServer``; ``auto`` prefers
            the framework and falls back to the SDK only when ``parrot.mcp``
            cannot be imported.

    Returns:
        A framework or SDK MCP server with all mounted wiki operations.
    """
    config = load_effective_config(root).config
    bundle = build_wiki_tools(root, config)
    _ensure_stderr_logging()
    selected, framework = _resolve_transport(transport)
    if selected == "sdk":
        server = to_sdk_server(bundle.descriptors, name="wikitoolkit")
    else:
        stdio_server_cls, local_config_cls = framework
        server = stdio_server_cls(local_config_cls(name="wikitoolkit", version="1.0.0", description=bundle.description))
        # The framework path registers the wrapper tools (they keep their
        # store handles); descriptors feed only the SDK transport.
        server.register_tools(bundle.tools)
        if bundle.vault_tools:
            server.register_tools(bundle.vault_tools)
    server.wiki_bundle = bundle
    return server


def create_proxy_mcp_server(remote: Any, *, transport: Literal["auto", "framework", "sdk"] = "auto") -> Any:
    """Build a stdio server that forwards MCP requests to a remote wiki."""
    from parrot.knowledge.wiki.cli import _authoring_identity
    from parrot.knowledge.wiki.remote import RemoteWikiClient, RemoteWikiError

    actor = remote.actor if remote.actor is not None else _authoring_identity(None)

    def make_sdk_proxy() -> Any:
        """Build the lazy SDK proxy without importing framework modules."""
        from mcp import types
        from mcp.server import Server
        from mcp.server.stdio import stdio_server

        server = Server("wikitoolkit")
        client: Any | None = None
        tools_cache: list[dict[str, Any]] | None = None

        async def client_ready() -> Any:
            nonlocal client
            if client is None:
                client = RemoteWikiClient(remote, actor=actor)
                await client.initialize()
            return client

        @server.list_tools()
        async def list_tools() -> list[Any]:
            """Forward remote MCP tool definitions."""
            nonlocal client, tools_cache
            try:
                if tools_cache is None:
                    tools_cache = await (await client_ready()).list_tools()
                return [types.Tool(**tool) for tool in tools_cache]
            except RemoteWikiError:
                client = None
                raise

        @server.call_tool()
        async def call_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
            """Forward remote MCP calls preserving result envelopes."""
            nonlocal client
            try:
                result = await (await client_ready()).call_tool(tool_name, arguments)
            except RemoteWikiError as exc:
                client = None
                return types.CallToolResult(content=[types.TextContent(type="text", text=str(exc))], isError=True)
            content = [
                types.TextContent(type="text", text=item.get("text", ""))
                for item in result.get("content", [])
                if item.get("type") == "text"
            ]
            return types.CallToolResult(
                content=content,
                structuredContent=result.get("structuredContent"),
                isError=result.get("isError", False),
            )

        async def start() -> None:
            """Serve the SDK proxy over stdio."""
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())

        server.start = start
        return server

    selected, framework = _resolve_transport(transport)
    if selected == "sdk":
        return make_sdk_proxy()

    stdio_server_cls, local_config_cls = framework

    class ProxyStdioMCPServer(stdio_server_cls):
        """Forwarding stdio server; remote failures remain request-scoped."""

        def __init__(self, config: Any, remote_cfg: Any, proxy_actor: str) -> None:
            super().__init__(config)
            self._remote_cfg = remote_cfg
            self._actor = proxy_actor
            self._client: Any | None = None
            self._tools_cache: list[dict[str, Any]] | None = None

        async def _client_ready(self) -> Any:
            if self._client is None:
                client = RemoteWikiClient(self._remote_cfg, actor=self._actor)
                await client.initialize()
                self._client = client
            return self._client

        async def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
            """Return the remote tool definitions, cached after a successful request."""
            try:
                if self._tools_cache is None:
                    self._tools_cache = await (await self._client_ready()).list_tools()
            except RemoteWikiError:
                self._client = None
                raise
            return {"tools": self._tools_cache}

        async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
            """Forward one tool call and convert remote failures to local errors."""
            try:
                return await (await self._client_ready()).call_tool(
                    params.get("name", ""), params.get("arguments", {}) or {}
                )
            except RemoteWikiError as exc:
                self._client = None
                raise RuntimeError(str(exc)) from exc

    return ProxyStdioMCPServer(
        local_config_cls(
            name="wikitoolkit",
            version="1.0.0",
            description=f"remote proxy → {remote.url}",
        ),
        remote,
        actor,
    )


def main() -> None:
    """CLI/module entry point for `wikitoolkit mcp` — logs to stderr only.

    stdout is reserved for the JSON-RPC channel, so logging is configured
    to stderr before anything else runs.
    """
    _ensure_stderr_logging()

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--transport", choices=("auto", "framework", "sdk"), default="auto")
    args, _unknown = parser.parse_known_args()

    root = find_project_root(Path(_INVOCATION_CWD))
    if root is None:
        print(
            "Error: not inside a git repository with a wiki",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        config = load_effective_config(root).config
    except WikiConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    from parrot.knowledge.wiki.project import resolve_remote

    remote = resolve_remote(config)
    if remote is not None:
        server = create_proxy_mcp_server(remote, transport=args.transport)
    else:
        if not config.is_built(root):
            print(
                f"Error: wiki not built yet for {root}. " "Run `wikitoolkit build` first.",
                file=sys.stderr,
            )
            sys.exit(1)
        server = create_wiki_mcp_server(root, transport=args.transport)
    # The lazy parrot.mcp.* import inside create_wiki_mcp_server() may have
    # re-attached a stdout handler (see _ensure_stderr_logging docstring) —
    # strip it again right before the stdin/stdout JSON-RPC loop starts.
    _ensure_stderr_logging()
    try:
        asyncio.run(server.start())
    finally:
        bundle = getattr(server, "wiki_bundle", None)
        if bundle is not None:
            _run_sync(close_bundle(bundle))


if __name__ == "__main__":
    main()
