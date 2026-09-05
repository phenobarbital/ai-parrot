"""Bookstore — a personal indexed library of books over PageIndex.

Books (PDF / EPUB / Markdown / plain text) are indexed as PageIndex
hierarchical trees (chapters / sections / page ranges) and catalogued
with a per-book "ficha" (:class:`BookCard`) stored in a SQLite + FTS5
catalog, so an agent can first ask *which book covers topic X* cheaply
and only then drill into the right book's tree.

Data lives per scope under ``<scope>/.parrot/library/``:

- ``library.db`` — the catalog (``books`` table + ``books_fts``).
- ``trees/`` — the :class:`~parrot.knowledge.pageindex.toolkit.PageIndexToolkit`
  storage dir (``<slug>.json`` lean trees + ``<slug>/*.md`` sidecars).

Agent surface: :class:`BookstoreToolkit` (read-only, seven ``bookstore_*``
tools). Management surface: the ``bookstore`` CLI (``add`` / ``list`` /
``show`` / ``search`` / ``toc`` / ``remove`` / ``mcp``).

Imports here are deliberately light — no ``parrot.mcp`` / navconfig
chains at module import time (stdout purity for the MCP server).
"""

from .config import LibraryLocation, resolve_locations
from .models import BookCard, CardDraft, TocEntry

__all__ = (
    "BookCard",
    "CardDraft",
    "LibraryLocation",
    "TocEntry",
    "resolve_locations",
)


def __getattr__(name: str):  # pragma: no cover - thin lazy loader
    """Lazily expose the heavier classes without importing them eagerly.

    ``Bookstore`` pulls in PageIndex (tiktoken, numpy…) and
    ``BookstoreToolkit`` pulls in the tools machinery — neither belongs
    in the import path of ``bookstore.config``/``models`` consumers such
    as the CLI's fast subcommands.
    """
    if name == "Bookstore":
        from .library import Bookstore

        return Bookstore
    if name == "BookstoreToolkit":
        from .toolkit import BookstoreToolkit

        return BookstoreToolkit
    if name == "CatalogStore":
        from .catalog import CatalogStore

        return CatalogStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
