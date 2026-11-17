"""Bookstore per-book segment reads (FEAT-840 / TASK-5311)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError

from .conftest import SAMPLE_MARKDOWN


@pytest.fixture
def locations(tmp_path) -> list[LibraryLocation]:
    return [
        LibraryLocation(scope="project", root=tmp_path / "proj" / "library"),
        LibraryLocation(scope="global", root=tmp_path / "glob" / "library"),
    ]


@pytest.fixture
def book_md(tmp_path) -> Path:
    path = tmp_path / "synthetic-handbook.md"
    path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    return path


@pytest.fixture
def store(locations, fake_adapter) -> Bookstore:
    return Bookstore(locations, adapter=fake_adapter)


@pytest.mark.asyncio
async def test_bookstore_read_segments_and_outline(store, book_md):
    card, _ = await store.add_book(book_md)
    outline = await store.outline(card.book_id)
    assert outline["book_id"] == card.book_id and outline["book_title"] == card.title
    assert outline["entries"]
    node_id = next(e["node_id"] for e in outline["entries"] if e["owned_segments"])
    read = await store.read_segments(card.book_id, node_id=node_id)
    assert read["book_id"] == card.book_id and read["book_title"] == card.title
    assert read["segments"] and read["segments"][0]["address"]["doc_id"]
    assert read["framed"].startswith("<document_text")
    whole = await store.read_segments(card.book_id, start=0, end=2, max_chars=100000)
    assert [s["seq"] for s in whole["segments"]] == [0, 1]


@pytest.mark.asyncio
async def test_bookstore_read_pages_unpaged_book(store, book_md):
    card, _ = await store.add_book(book_md)
    with pytest.raises(BookstoreError, match="read_segments"):
        await store.read_pages(card.book_id, "1")


@pytest.mark.asyncio
async def test_bookstore_book_without_segments(store, book_md, monkeypatch):
    card, _ = await store.add_book(book_md)
    toolkit = store._toolkit("project")

    async def none(tree_name):
        return []

    monkeypatch.setattr(toolkit, "list_documents", none)
    for call in (
        store.read_segments(card.book_id),
        store.read_pages(card.book_id, "1"),
        store.outline(card.book_id),
    ):
        with pytest.raises(BookstoreError, match="pageindex_index_segments"):
            await call


@pytest.mark.asyncio
async def test_bookstore_unknown_node_is_bookstore_error(store, book_md):
    card, _ = await store.add_book(book_md)
    with pytest.raises(BookstoreError):
        await store.read_segments(card.book_id, node_id="9999")
