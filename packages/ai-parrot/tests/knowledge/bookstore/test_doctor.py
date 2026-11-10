"""Deterministic regression coverage for Bookstore doctor recovery."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from parrot.knowledge.bookstore.catalog import CatalogStore
from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore
from parrot.knowledge.bookstore.models import RelationJudgement

from .conftest import SAMPLE_MARKDOWN


def _locations(tmp_path: Path) -> list[LibraryLocation]:
    return [LibraryLocation(scope="project", root=tmp_path / "library")]


@pytest.mark.asyncio
async def test_repair_structural_drift(tmp_path: Path) -> None:
    """Repair updates proven fields and clears unproven source identity."""
    source = tmp_path / "book.md"
    source.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    bookstore = Bookstore(_locations(tmp_path))
    card, _status = await bookstore.add_book(source)
    catalog = bookstore._catalog("project")
    catalog.upsert(
        card.model_copy(
            update={
                "toc_digest": "outdated",
                "summary": "Manual description remains intact.",
                "source_sha256": "proven-source-hash",
            }
        )
    )

    report = await bookstore.doctor(repair=True)

    repaired = catalog.get(card.book_id)
    assert report["books"] == [{"scope": "project", "book_id": card.book_id, "status": "drift", "repaired": True}]
    assert repaired is not None
    assert repaired.summary == "Manual description remains intact."
    assert repaired.source_sha256 == ""
    assert repaired.toc_digest == card.toc_digest


@pytest.mark.asyncio
async def test_orphan_and_busy_reports(tmp_path: Path) -> None:
    """Doctor reports unrepairable and locked books truthfully."""
    source = tmp_path / "book.md"
    source.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    bookstore = Bookstore(_locations(tmp_path))
    card, _status = await bookstore.add_book(source)
    await bookstore._toolkit("project").delete_tree(card.tree_name)

    orphan = await bookstore.doctor()
    assert orphan["books"][0]["status"] == "orphan_card"
    assert orphan["books"][0]["repaired"] is False

    async with bookstore._book_operation_lock("project", card.tree_name):
        busy = await bookstore.doctor()
    assert busy["books"][0]["status"] == "busy"


@pytest.mark.asyncio
async def test_judgements_and_empty_targets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both endpoints and negative judgements count; no targets skips relate."""
    source = tmp_path / "book.md"
    source.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    bookstore = Bookstore(_locations(tmp_path))
    first, _status = await bookstore.add_book(source)
    other = tmp_path / "other.md"
    other.write_text(SAMPLE_MARKDOWN.replace("Chapter Two", "Different Chapter"), encoding="utf-8")
    second, _status = await bookstore.add_book(other)
    catalog: CatalogStore = bookstore._catalog("project")
    catalog.record_judgements(
        first.book_id,
        [
            RelationJudgement(
                dst_book_id=second.book_id,
                rel="none",
                confidence=0.9,
                rationale="No conceptual overlap.",
            )
        ],
        model="test",
    )
    relate_books = AsyncMock()
    monkeypatch.setattr(bookstore, "relate_books", relate_books)

    report = await bookstore.doctor(relate=True)

    assert catalog.judgement_count(first.book_id) == 1
    assert catalog.judgement_count(second.book_id) == 1
    assert report["unjudged_book_ids"] == []
    relate_books.assert_not_awaited()
