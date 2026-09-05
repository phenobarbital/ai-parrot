"""Pydantic models for the Bookstore catalog (the "ficha hemeroteca").

:class:`BookCard` is the durable catalog card persisted per book in
``library.db``; :class:`CardDraft` is the structured-output target the
LLM fills during carding (:mod:`parrot.knowledge.bookstore.carding`).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class TocEntry(BaseModel):
    """One table-of-contents row derived from a PageIndex tree node.

    Args:
        node_id: PageIndex node id (``"0003"``) — the key for
            ``bookstore_read_section``.
        title: Section/chapter title.
        depth: 1-based depth in the tree (1 = top-level chapter).
        start_page: Physical start page (PDF trees only).
        end_page: Physical end page (PDF trees only).
    """

    node_id: str
    title: str
    depth: int = 1
    start_page: Optional[int] = None
    end_page: Optional[int] = None


class CardDraft(BaseModel):
    """LLM structured-output draft of the descriptive card fields.

    Produced by ``carding.generate_card_fields`` (or its no-LLM
    fallback) and merged into a :class:`BookCard` by the ingestion flow.
    """

    title: str = Field(..., description="Full book title.")
    authors: list[str] = Field(
        default_factory=list, description="Author names, best effort."
    )
    year: Optional[int] = Field(
        default=None, description="Publication year when identifiable."
    )
    language: Optional[str] = Field(
        default=None, description="Primary language, ISO 639-1 (e.g. 'en', 'es')."
    )
    topics: list[str] = Field(
        default_factory=list,
        description="5-10 research topics/keywords this book is useful for.",
    )
    summary: str = Field(
        default="",
        description=(
            "One-paragraph librarian summary: what the book covers and "
            "what kind of questions it can answer."
        ),
    )


class BookCard(BaseModel):
    """The catalog card ("ficha hemeroteca") for one indexed book.

    ``book_id`` doubles as the PageIndex ``tree_name`` — one slug, one
    tree, one card.
    """

    book_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    language: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    summary: str = ""
    toc_digest: str = ""
    toc: list[TocEntry] = Field(default_factory=list)
    tree_name: str
    scope: Literal["project", "global"] = "project"
    source_path: str
    source_sha256: str
    source_format: Literal["pdf", "md", "txt", "epub"]
    page_count: Optional[int] = None
    chapter_count: int = 0
    added_at: str
    card_origin: Literal["llm", "fallback", "manual"] = "llm"

    def brief(self) -> dict:
        """Compact dict for catalog listings (small tool outputs).

        Returns:
            The fields an agent needs to pick a book, without the full
            ToC payload.
        """
        first_line = self.summary.split("\n", 1)[0] if self.summary else ""
        return {
            "book_id": self.book_id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "language": self.language,
            "topics": self.topics,
            "summary": first_line,
            "chapter_count": self.chapter_count,
            "page_count": self.page_count,
            "scope": self.scope,
        }
