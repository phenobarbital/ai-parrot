"""WikiToolkit MCP server entry point (FEAT-403 Module 6).

Wires the six wiki `AbstractTool` wrappers (`parrot.knowledge.wiki.tools`)
into a core `StdioMCPServer` (`parrot.mcp.local_server`) so `wikitoolkit
mcp` exposes the codebase knowledge graph as a first-class MCP tool —
equal standing with Grep/Read at tool-selection time (see the spec's
Problem Statement for why the Bash-invoked CLI alone was not enough).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from parrot.knowledge.wiki.project import (
    WikiConfigError,
    find_project_root,
    load_effective_config,
    sqlite_policy_from_config,
)
from parrot.knowledge.wiki.store import create_wiki_store
from parrot.knowledge.wiki.tools import create_wiki_tools

if TYPE_CHECKING:
    # Import only for the annotation below — the real (runtime) import is
    # deferred inside create_wiki_mcp_server() itself, see its docstring.
    from parrot.mcp.local_server import StdioMCPServer

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


def create_wiki_mcp_server(root: Path) -> StdioMCPServer:
    """Build a `StdioMCPServer` with the six wiki tools registered.

    Args:
        root: Wiki project root (directory containing `.parrot/wiki.json`,
            or the nearest `.git` root — see `find_project_root()`).

    Returns:
        A core `StdioMCPServer` with all six wiki tools registered.
    """
    # Some parrot.mcp.* dependencies print raw diagnostic lines directly to
    # stdout during import (not via logging — pre-existing navconfig
    # settings-init side effect, not introduced here). Redirect stdout to
    # stderr for the duration of the import only, so nothing can leak into
    # the JSON-RPC channel this import is deferred specifically to protect.
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.mcp.local_server import StdioMCPServer
        from parrot.mcp.server_base import LocalServerConfig

    config = load_effective_config(root).config
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
        from parrot.knowledge.wiki.federation import (
            FederatedWikiStore,
            resolve_namespaces,
        )

        try:
            handles, skipped = _run_sync(resolve_namespaces(root, config))
        except Exception as exc:  # noqa: BLE001 — namespaces are optional
            logging.getLogger(__name__).warning("Could not resolve wiki namespaces: %s", exc)
            handles, skipped = [], []

    # FEAT-566: Initialize ledger service for ledger tools — only when `root`
    # resolves to a real, git-backed shared root. `LedgerService.from_root`
    # tolerates the absence of one by falling back to `root`/CWD (so the
    # service itself never raises), which would otherwise make every
    # `create_wiki_mcp_server` call on a bare directory (most unit-test
    # fixtures included) silently grow a `.parrot/ledger/` and mount an
    # extra namespace — changing tool counts with no wiki project involved.
    ledger_service = None
    with contextlib.redirect_stdout(sys.stderr):
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
            from parrot.knowledge.wiki.project import WikiNamespaceConfig
            from parrot.knowledge.wiki.federation import NamespaceHandle

            ledger_dir = ledger_service.shared_root / ".parrot" / "ledger"
            ledger_config = WikiNamespaceConfig(
                store=str(ledger_dir),
                description="SDD work ledger (issues, tasks, specs, insights)",
                weight=0.5,
                overlay_prefixes=["issue", "task", "spec", "insight"],
            )
            handles.append(
                NamespaceHandle(
                    name="ledger",
                    store=ledger_service.store,
                    config=ledger_config,
                    storage_dir=ledger_dir,
                    read_only=True,
                )
            )

    if handles or skipped:
        read_store = FederatedWikiStore(store, config.wiki_name, handles, skipped)
    tools = create_wiki_tools(read_store, root=root, config=config, ledger_service=ledger_service)

    # FEAT-498: symbol-plane tools (wiki_symbol_lookup, wiki_code_outline,
    # wiki_blast_radius) share the same read_store, so they honour the
    # same federated namespaces as the six tools above.
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.knowledge.wiki.structural import create_structural_tools

        structural_tools = create_structural_tools(read_store, root, config)
    tools = tools + structural_tools

    # FEAT-578: decision-plane tools (wiki_decisions_for_symbol,
    # wiki_decision_why) share the same read_store, so they honour the same
    # federated namespaces. wiki_decision_generate is added by the factory
    # only when generation is enabled AND a local project is available; there
    # is no review tool — acceptance is a maintainer CLI action (AC11).
    # decisions.service transitively reaches structural.service (which
    # itself imports wiki.cli for a couple of helpers), and that chain can
    # still trigger the same navconfig settings-init stdout leak the
    # imports above are guarded against — protect this one the same way.
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.knowledge.wiki.decisions import create_decision_tools

        decision_tools = create_decision_tools(read_store, root, config)
    tools = tools + decision_tools

    # Obsidian vault exposure: when the project has a vault (explicit
    # `vault_dir` in wiki.json, or the root itself is a vault), register
    # the full ObsidianToolkit plus the wiki-side vault_ingest tool.
    # Everything — including resolution, whose vault_scan import pulls in
    # parrot.interfaces (another stdout-printing navconfig chain) — runs
    # under the same stdout-redirect discipline as the parrot.mcp.* import
    # above. Destructive obsidian_* tools carry
    # routing_meta["requires_confirmation"], which MCPToolAdapter turns
    # into a required `confirm` argument (soft HITL guard over stdio).
    description = (
        "Codebase knowledge graph — query, explore, remember, and look up "
        "symbols (functions/classes/methods), outlines, and blast radius"
    )
    if handles:
        names = ", ".join(sorted(h.name for h in handles))
        description += f" — federating {len(handles)} namespace(s): {names}"
    vault_tools = []
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.knowledge.wiki.project import resolve_vault_dir

        vault = resolve_vault_dir(root, config)
        if vault is not None:
            from parrot.knowledge.wiki.tools import VaultIngestTool
            from parrot.tools.obsidian import ObsidianToolkit

            toolkit = ObsidianToolkit(vault_path=vault)
            vault_tools = list(toolkit.get_tools_sync())
            vault_tools.append(VaultIngestTool(store, root=root, config=config))
            description += f" — plus Obsidian vault management for {vault.name!r}"
    _ensure_stderr_logging()

    server = StdioMCPServer(
        LocalServerConfig(
            name="wikitoolkit",
            version="1.0.0",
            description=description,
        )
    )
    server.register_tools(tools)
    if vault_tools:
        server.register_tools(vault_tools)
    return server


def main() -> None:
    """CLI/module entry point for `wikitoolkit mcp` — logs to stderr only.

    stdout is reserved for the JSON-RPC channel, so logging is configured
    to stderr before anything else runs.
    """
    _ensure_stderr_logging()

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

    if not config.is_built(root):
        print(
            f"Error: wiki not built yet for {root}. " "Run `wikitoolkit build` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    server = create_wiki_mcp_server(root)
    # The lazy parrot.mcp.* import inside create_wiki_mcp_server() may have
    # re-attached a stdout handler (see _ensure_stderr_logging docstring) —
    # strip it again right before the stdin/stdout JSON-RPC loop starts.
    _ensure_stderr_logging()
    asyncio.run(server.start())


if __name__ == "__main__":
    main()
