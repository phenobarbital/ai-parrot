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
from pathlib import Path
from typing import TYPE_CHECKING

from parrot.knowledge.wiki.project import (
    WikiConfigError,
    find_project_root,
    load_project_config,
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

    config = load_project_config(root)
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
            storage, wiki_name=config.wiki_name, backend=config.backend
        )
    tools = create_wiki_tools(store, root=root, config=config)
    server = StdioMCPServer(LocalServerConfig(
        name="wikitoolkit",
        version="1.0.0",
        description="Codebase knowledge graph — query, explore, and remember",
    ))
    server.register_tools(tools)
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
        config = load_project_config(root)
    except WikiConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not config.is_built(root):
        print(
            f"Error: wiki not built yet for {root}. "
            "Run `wikitoolkit build` first.",
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
