"""``MultiStoreSearch`` package (FEAT-379).

A package of ``SearchOrigin`` adapters (vector stores, PageIndex,
GraphIndex, ParrotWiki) plus ``MultiStoreSearchToolkit`` — the
agent-facing toolkit orchestrating them (``store_search``,
``batch_search``, ``fts_search``, ``list_search_origins``).

Clean-break migration note (TASK-1937): the legacy single-module tool
and its input-schema model (formerly ``multistoresearch.py``, briefly
``_legacy_tool.py`` during the module→package transition) have been
REMOVED — no deprecation shim. Use ``MultiStoreSearchToolkit`` instead.
"""
from .toolkit import MultiStoreSearchToolkit

__all__ = (
    "MultiStoreSearchToolkit",
)
