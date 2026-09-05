"""Bookstore MCP server entry point (``bookstore mcp``).

Wires the seven read-only ``bookstore_*`` tools into a core
:class:`~parrot.mcp.local_server.StdioMCPServer` so Claude Code (and any
MCP client) can research the personal indexed library with first-class
tools — same pattern and stdout-purity discipline as
``parrot.knowledge.wiki.mcp_server``.

Degradation matrix:

- LLM configured (``PARROT_BOOKSTORE_LLM``): full surface — hybrid
  in-book search and scoped cross-book tree-walks.
- No LLM, ``bm25s`` installed: ``search_book``/``search`` run BM25-only.
- No LLM, no ``bm25s``: those two tools error explanatorily, while
  ``catalog_search`` / ``list_books`` / ``get_card`` / ``get_toc`` /
  ``read_section`` (the core funnel) keep working fully.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .config import LibraryLocation, resolve_locations

if TYPE_CHECKING:
    # Runtime import is deferred (see create_bookstore_mcp_server) so the
    # navconfig-based parrot.mcp import chain cannot touch stdout first.
    from parrot.mcp.local_server import StdioMCPServer

# Captured before any lazy parrot.mcp.* import below — that import chain
# pulls navconfig settings which chdir() as a side effect (pre-existing
# quirk; same guard as wiki/mcp_server.py).
_INVOCATION_CWD = os.getcwd()


def _ensure_stderr_logging() -> None:
    """Force the root logger onto stderr, replacing any stdout handler.

    Idempotent; called before AND after the lazy heavy imports, because
    navconfig-based settings attach their own stdout handler as an
    import side effect and ``logging.basicConfig`` alone cannot undo
    that.
    """
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    )
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.WARNING)


def create_bookstore_mcp_server(
    locations: list[LibraryLocation],
    adapter: Optional[object] = None,
    lightweight_model: Optional[str] = None,
) -> StdioMCPServer:
    """Build a ``StdioMCPServer`` with the bookstore tools registered.

    Args:
        locations: Resolved library locations (project first).
        adapter: Optional PageIndex LLM adapter; ``None`` = degraded.
        lightweight_model: Optional cheap model id (same provider as
            the adapter's client).

    Returns:
        The configured, not-yet-started stdio server.
    """
    # parrot.mcp.* dependencies may print raw lines to stdout during
    # import (navconfig settings-init side effect) — redirect for the
    # duration of every heavy import so nothing leaks into JSON-RPC.
    with contextlib.redirect_stdout(sys.stderr):
        from parrot.mcp.local_server import StdioMCPServer
        from parrot.mcp.server_base import LocalServerConfig

        from .library import Bookstore
        from .toolkit import BookstoreToolkit

        store = Bookstore(
            locations, adapter=adapter, lightweight_model=lightweight_model
        )
        toolkit = BookstoreToolkit(bookstore=store)
        tools = toolkit.get_tools_sync()
        book_count = len(store.list_books())

    description = (
        f"Personal indexed book library — {book_count} book(s). "
        "Research funnel: bookstore_catalog_search (which book covers X) → "
        "bookstore_get_toc → bookstore_search_book → bookstore_read_section."
    )
    if adapter is None:
        description += " (no LLM configured: lexical search only)"

    _ensure_stderr_logging()
    server = StdioMCPServer(
        LocalServerConfig(
            name="bookstore",
            version="1.0.0",
            description=description,
        )
    )
    server.register_tools(tools)
    return server


def main() -> None:
    """Entry point for ``bookstore mcp`` — logs to stderr only.

    stdout is reserved for the JSON-RPC channel.
    """
    _ensure_stderr_logging()

    locations = resolve_locations(
        cwd=Path(_INVOCATION_CWD), require_exists=True
    )
    if not locations:
        print(
            "Error: no bookstore library found (neither .parrot/library in "
            "this repo nor ~/.parrot/library). Run `bookstore add <file>` "
            "first.",
            file=sys.stderr,
        )
        sys.exit(1)

    from ._llm import resolve_adapter

    adapter, lightweight_model, client = resolve_adapter()

    async def _serve() -> None:
        server = create_bookstore_mcp_server(
            locations, adapter=adapter, lightweight_model=lightweight_model
        )
        _ensure_stderr_logging()
        if client is not None and hasattr(client, "__aenter__"):
            async with client:
                await server.start()
        else:
            await server.start()

    asyncio.run(_serve())


if __name__ == "__main__":
    main()
