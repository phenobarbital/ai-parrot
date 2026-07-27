"""``MultiStoreSearch`` package (FEAT-379).

Replaces the old single-module ``MultiStoreSearchTool`` with a package of
``SearchOrigin`` adapters (vector stores, PageIndex, GraphIndex,
ParrotWiki) plus a ``MultiStoreSearchToolkit`` (added by TASK-1936).

Module→package transition note: the old ``MultiStoreSearchTool`` /
``MultiStoreSearchSchema`` still live in ``_legacy_tool.py`` (unchanged)
and are re-exported here so the existing registry entry
(``parrot_tools.multistoresearch.MultiStoreSearchTool``) and
``StoreRouter`` integration keep resolving. This re-export — and
``_legacy_tool.py`` itself — are REMOVED by the clean-break migration
(TASK-1937).
"""
from ._legacy_tool import MultiStoreSearchTool, MultiStoreSearchSchema
from .toolkit import MultiStoreSearchToolkit

__all__ = (
    "MultiStoreSearchTool",
    "MultiStoreSearchSchema",
    "MultiStoreSearchToolkit",
)
