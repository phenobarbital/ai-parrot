"""Bookstore notebooks: relation sheets (and, from TASK-5481, drafting) — FEAT-876.

A *relation sheet* is a notebook node — in a scope's ``_library_notes`` or in a
book notebook ``<book_id>_notes`` — whose ``metadata.anchors`` point at two or
more distinct books. :func:`relation_sheets` projects every such node into
``origin="manual"`` :class:`~parrot.knowledge.bookstore.models.BookRelation`
edges; :func:`apply_relation_sheets` persists them in the scope DB that owns
each edge's source book, where a later computed ``relate_books`` run never
overwrites them (``CatalogStore.upsert_relations``).

Librarian *sectors* (nodes carrying ``metadata.sector_code``) are
classification, not relation claims: they routinely anchor many books and are
answered through :meth:`~parrot.knowledge.bookstore.library.Bookstore.find_books`,
so they are never projected into edges here.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from datetime import datetime, timezone
from typing import Any, Optional, get_args

from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.utils import structure_to_list

from .catalog import CatalogStore
from .library import LIBRARY_NOTEBOOK, NOTEBOOK_SUFFIX, Bookstore
from .models import Anchor, BookRelation, RelationKind

logger = logging.getLogger(__name__)

_DIRECTED = frozenset({"influenced_by", "responds_to"})
_RELATION_KINDS = frozenset(get_args(RelationKind))
#: Maximum characters of the sheet body kept as the edge rationale.
_RATIONALE_MAX_CHARS = 500


def _anchored_books(store: Bookstore, raw_anchors: Any, tree_name: str, node_id: str) -> list[str]:
    """Distinct catalogued book ids a node anchors, in first-anchor order.

    Anchors are resolved through ``(scope, book_id)`` (S11): an anchor whose
    scope has no library location, or whose book is not catalogued as a book
    in that scope, is skipped.
    """
    if not isinstance(raw_anchors, list):
        return []
    known_scopes = {location.scope for location in store.locations}
    books: list[str] = []
    for raw in raw_anchors:
        try:
            anchor = Anchor.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 — malformed anchors are doctor --notes' business
            logger.debug("notebook %r node %r: malformed anchor %r: %s", tree_name, node_id, raw, exc)
            continue
        if anchor.book_id in books or anchor.scope not in known_scopes:
            continue
        card = store._catalog(anchor.scope).get(anchor.book_id)
        if card is None or card.kind != "book":
            logger.debug(
                "notebook %r node %r: anchor %r is not a book of the %s library",
                tree_name,
                node_id,
                anchor.book_id,
                anchor.scope,
            )
            continue
        books.append(anchor.book_id)
    return books


def _sheet_pairs(rel: str, books: list[str]) -> list[tuple[str, str]]:
    """Endpoint pairs of one sheet: first anchor → each other for directed kinds, every pair otherwise."""
    if rel in _DIRECTED:
        first = books[0]
        return [(first, other) for other in books[1:]]
    return list(itertools.combinations(books, 2))


def _relation_sheets_sync(store: Bookstore, scope: Optional[str], now: str) -> list[BookRelation]:
    """Blocking walk of every notebook tree (file reads + catalog lookups)."""
    relations: list[BookRelation] = []
    for location in store.locations:
        if scope is not None and location.scope != scope:
            continue
        if not location.trees_dir.is_dir():
            continue
        trees = JSONTreeStore(location.trees_dir)
        content = store._content_store(location.scope)
        for name in trees.list_names():
            if name != LIBRARY_NOTEBOOK and not name.endswith(NOTEBOOK_SUFFIX):
                continue
            try:
                tree = trees.load(name)
            except Exception as exc:  # noqa: BLE001 — one unreadable notebook never hides the others
                logger.warning("relation sheets: notebook %r (%s) unreadable: %s", name, location.scope, exc)
                continue
            for node in structure_to_list(tree.get("structure", [])):
                if not isinstance(node, dict) or not node.get("node_id"):
                    continue
                metadata = node.get("metadata")
                if not isinstance(metadata, dict) or metadata.get("sector_code") is not None:
                    continue
                node_id = str(node["node_id"])
                books = _anchored_books(store, metadata.get("anchors"), name, node_id)
                if len(books) < 2:
                    continue
                rel = metadata.get("rel") or "parallels"
                if rel not in _RELATION_KINDS:
                    logger.warning(
                        "relation sheets: notebook %r node %r has invalid rel %r — skipped", name, node_id, rel
                    )
                    continue
                body = content.load_current(name, node_id) or str(node.get("title") or "")
                rationale = body.strip()[:_RATIONALE_MAX_CHARS]
                for src, dst in _sheet_pairs(rel, books):
                    relations.append(
                        BookRelation(
                            src_book_id=src,
                            dst_book_id=dst,
                            rel=rel,
                            weight=1.0,
                            origin="manual",
                            rationale=rationale,
                            computed_at=now,
                        )
                    )
    return relations


async def relation_sheets(store: Bookstore, scope: Optional[str] = None) -> list[BookRelation]:
    """Every notebook node anchoring two or more books, as ``origin='manual'`` relations.

    ``metadata.rel`` picks the relation kind (default ``"parallels"``; a value
    outside :data:`~parrot.knowledge.bookstore.models.RelationKind` skips the
    node with a warning). For the directed kinds (``influenced_by``,
    ``responds_to``) the first anchored book is the source of one edge per
    other book; symmetric kinds emit one edge per pair. Pairs are not
    canonicalised here — :meth:`CatalogStore.upsert_relations` does that.

    Args:
        store: The library whose notebooks are read.
        scope: Restrict the walk to one scope's notebooks (``None`` = every scope).

    Returns:
        The sheet relations, in notebook/node order.
    """
    now = datetime.now(timezone.utc).isoformat()
    return await asyncio.to_thread(_relation_sheets_sync, store, scope, now)


async def apply_relation_sheets(store: Bookstore, scope: Optional[str] = None) -> int:
    """Upsert the sheet relations into the store owning each edge's source; returns the edge count.

    Args:
        store: The library whose notebooks are read and whose catalogs are written.
        scope: Restrict the walk to one scope's notebooks (``None`` = every scope).

    Returns:
        Number of manual edges written.
    """
    relations = await relation_sheets(store, scope)

    def _write() -> None:
        groups: dict[int, tuple[CatalogStore, list[BookRelation]]] = {}
        for relation in relations:
            owner = store._relations_store_for(relation.src_book_id)
            groups.setdefault(id(owner), (owner, []))[1].append(relation)
        for owner, owned in groups.values():
            owner.upsert_relations(owned)

    await asyncio.to_thread(_write)
    return len(relations)
