"""BrainStore — lean wiki writer/reader for the dream cycle (FEAT-390).

Wraps the SQLite wiki retrieval plane (:func:`create_wiki_store`) directly,
WITHOUT constructing the full :class:`LLMWikiToolkit` (which requires
PageIndex/GraphIndex/OKF toolkit dependencies). ``BrainStore.remember()``
reproduces ``LLMWikiToolkit.remember()`` semantics byte-for-byte so the
brain ``wiki.db`` remains fully interoperable with ``LLMWikiToolkit`` and
the ``wikitoolkit`` CLI.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from parrot.knowledge.wiki import create_wiki_store, pack_results
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens


class BrainStore:
    """Lean wiki writer/reader over ``create_wiki_store`` (no PI/GI/OKF deps).

    Attributes:
        storage_dir: Directory holding the wiki's ``wiki.db`` file.
        wiki_name: Name recorded by the underlying store backend.
        asserted_by: Identity stamped onto pages written via ``remember()``
            (e.g. ``"agent:<id>"``).
    """

    def __init__(
        self,
        storage_dir: Path,
        wiki_name: str,
        asserted_by: str = "agent",
    ) -> None:
        """Initialise the BrainStore, creating ``storage_dir`` if needed.

        Args:
            storage_dir: Directory in which the SQLite wiki store lives.
            wiki_name: Wiki name recorded by the backend.
            asserted_by: Attribution stamped onto authored/memory pages.
        """
        self.logger = logging.getLogger(__name__)
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.wiki_name = wiki_name
        self.asserted_by = asserted_by
        self._store = create_wiki_store(
            self.storage_dir, wiki_name=wiki_name, backend="sqlite"
        )

    async def remember(
        self,
        text: str,
        title: str | None = None,
        category: str = "note",
        related_pages: list[str] | None = None,
    ) -> dict[str, Any]:
        """Save distilled knowledge into the wiki as durable memory.

        Replicates ``LLMWikiToolkit.remember()`` (``toolkit.py:660-725``)
        exactly: the page id is a deterministic hash of the title/category,
        so remembering the same thing twice updates the existing page
        instead of duplicating it.

        Args:
            text: The knowledge to remember (markdown allowed).
            title: Optional short title; derived from the text's first
                line (truncated to 80 chars) when omitted.
            category: One of ``note | decision | lesson | concept`` (open
                string).
            related_pages: Optional page ids to link the memory to via
                ``references``/``asserted`` edges.

        Returns:
            Dict with keys: ``page_id``, ``title``, ``category``, ``status``
            (``"created"`` or ``"updated"``).
        """
        title = (title or text.strip().splitlines()[0][:80]).strip()
        page_id = "mem-" + hashlib.sha1(
            f"{title}::{category}".encode()
        ).hexdigest()[:12]

        existing = await self._store.get_page(page_id, include_body=False)
        record = WikiPageRecord(
            concept_id=page_id,
            node_id=page_id,
            title=title,
            category=category,
            summary=text[:300],
            body=text,
            token_count=estimate_tokens(text),
            origin="memory",
            asserted_by=self.asserted_by,
        )
        await self._store.upsert_pages([record])
        if related_pages:
            await self._store.add_edges(
                [
                    (page_id, str(rp), "references", "asserted")
                    for rp in related_pages
                ]
            )

        return {
            "page_id": page_id,
            "title": title,
            "category": category,
            "status": "updated" if existing else "created",
        }

    async def search(
        self,
        query: str,
        top_k: int = 5,
        max_tokens: int = 600,
    ) -> str:
        """Search the brain wiki and pack results under a token budget.

        Degrades gracefully: any exception or empty result set returns
        ``""`` — never raises.

        Args:
            query: Free-form natural-language query.
            top_k: Maximum number of results to consider.
            max_tokens: Token budget for the packed text.

        Returns:
            Packed, budgeted text block, or ``""`` on no results / error.
        """
        try:
            results = await self._store.search_fts(query, limit=top_k)
        except Exception as exc:  # noqa: BLE001 - memory must never raise
            self.logger.warning(
                "BrainStore.search failed for query %r: %s", query, exc
            )
            return ""

        if not results:
            return ""

        packed = pack_results(results, budget_tokens=max_tokens)
        return packed.text

    async def copy_page_to(self, page_id: str, other: BrainStore) -> str:
        """Copy a page into another BrainStore, preserving attribution.

        Args:
            page_id: The page's ``concept_id`` in this store.
            other: Destination BrainStore (e.g. the org wiki).

        Returns:
            The page id in the destination store (same as ``page_id`` when
            found; the original ``page_id`` is returned unchanged even if
            the source page could not be located, with a WARNING logged).
        """
        page = await self._store.get_page(page_id, include_body=True)
        if page is None:
            self.logger.warning(
                "copy_page_to: page %s not found in %s", page_id, self.wiki_name
            )
            return page_id

        record = WikiPageRecord(
            concept_id=page["concept_id"],
            node_id=page.get("node_id") or page["concept_id"],
            title=page.get("title") or "",
            category=page.get("category") or "note",
            summary=page.get("summary") or "",
            body=page.get("body") or "",
            token_count=page.get("token_count") or 0,
            origin="memory",
            asserted_by=page.get("asserted_by"),
        )
        await other._store.upsert_pages([record])
        return record.concept_id
