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


@pytest.mark.asyncio
async def test_doctor_notes_reports_orphans_and_malformed(tmp_path: Path) -> None:
    """``notes=True`` reports orphan notebooks, malformed/stale anchors and broken bindings."""
    source = tmp_path / "book.md"
    source.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    bookstore = Bookstore(_locations(tmp_path))
    card, _status = await bookstore.add_book(source)
    plain = await bookstore.doctor()
    assert "notes" not in plain

    notebook = await bookstore.ensure_notebook(card.book_id)
    toolkit = await bookstore._ready_toolkit("project")
    good = await toolkit.add_node(notebook.tree_name, title="good")
    await toolkit.tag_node(
        notebook.tree_name,
        good["node_id"],
        metadata={"anchors": [{"book_id": card.book_id, "node_id": "0001"}], "anchor_status": "stale"},
    )
    bad = await toolkit.add_node(notebook.tree_name, title="bad")
    await toolkit.tag_node(notebook.tree_name, bad["node_id"], metadata={"anchors": [{"node_id": "x"}]})

    # An orphan notebook (its book has no card) and an unregistered conventional tree.
    await toolkit.create_tree("ghost_notes")
    catalog = bookstore._catalog("project")
    ghost = notebook.model_copy(update={"book_id": "ghost_notes", "tree_name": "ghost_notes", "notes_for": "ghost"})
    catalog.upsert(ghost)
    await toolkit.create_tree("lost_notes")  # no card, but `lost` is not a book: not flagged
    await toolkit.create_tree(f"{card.book_id}2_notes")
    # Card whose tree vanished.
    broken = notebook.model_copy(update={"book_id": "gone_notes", "tree_name": "gone_notes", "notes_for": card.book_id})
    catalog.upsert(broken)

    report = await bookstore.doctor(notes=True)
    notes = report["notes"]["project"]
    assert notes["notebooks"] == 3
    assert "ghost_notes" in notes["orphans"]
    assert len(notes["malformed_anchors"]) == 1
    assert notes["stale_anchors"] == 1
    assert {"book_id": "gone_notes", "reason": "card_without_tree"} in notes["broken_bindings"]
