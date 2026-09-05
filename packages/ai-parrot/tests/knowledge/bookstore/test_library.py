"""Tests for the Bookstore manager (ingestion + read surface)."""

from __future__ import annotations

import builtins
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


@pytest.fixture
def store_no_llm(locations) -> Bookstore:
    return Bookstore(locations)


@pytest.mark.asyncio
async def test_add_book_markdown_with_llm(store, book_md, locations):
    card, status = await store.add_book(book_md)
    assert status == "added"
    assert card.book_id == "synthetic-handbook"
    assert card.card_origin == "llm"
    assert card.title == "Synthetic Handbook"
    assert card.authors == ["Ada Example"]
    assert "async python" in card.topics
    assert card.chapter_count >= 1
    assert card.toc_digest
    # Tree JSON + catalog row exist on disk in the project scope.
    assert (locations[0].trees_dir / "synthetic-handbook.json").is_file()
    assert (locations[0].db_path).is_file()


@pytest.mark.asyncio
async def test_add_book_sha_skip_and_force(store, book_md):
    card1, status1 = await store.add_book(book_md)
    card2, status2 = await store.add_book(book_md)
    assert (status1, status2) == ("added", "skipped")
    assert card2.book_id == card1.book_id
    _, status3 = await store.add_book(book_md, force=True)
    assert status3 == "updated"


@pytest.mark.asyncio
async def test_add_book_no_llm_fallback_card(store_no_llm, book_md):
    card, status = await store_no_llm.add_book(book_md)
    assert status == "added"
    assert card.card_origin == "fallback"
    assert card.title == "Synthetic Handbook"  # de-slugified filename
    assert card.topics  # top-level chapter titles


@pytest.mark.asyncio
async def test_add_book_manual_overrides(store, book_md):
    card, _ = await store.add_book(
        book_md, title="My Handbook", authors=["Me"], topics=["testing"]
    )
    assert card.card_origin == "manual"
    assert (card.title, card.authors, card.topics) == (
        "My Handbook",
        ["Me"],
        ["testing"],
    )
    assert card.book_id == "my-handbook"


@pytest.mark.asyncio
async def test_add_book_txt_requires_llm(store_no_llm, tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("plain text", encoding="utf-8")
    with pytest.raises(BookstoreError, match="LLM"):
        await store_no_llm.add_book(txt)


@pytest.mark.asyncio
async def test_add_book_unsupported_format(store, tmp_path):
    bad = tmp_path / "book.docx"
    bad.write_text("x", encoding="utf-8")
    with pytest.raises(BookstoreError, match="Unsupported format"):
        await store.add_book(bad)


@pytest.mark.asyncio
async def test_epub_without_loaders_package(store, tmp_path, monkeypatch):
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"fake epub")
    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("parrot_loaders"):
            raise ImportError("No module named 'parrot_loaders'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with pytest.raises(BookstoreError, match="ai-parrot-loaders"):
        await store.add_book(epub)


@pytest.mark.asyncio
async def test_slug_collision_suffixing(store, tmp_path):
    a = tmp_path / "same-title.md"
    a.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    b = tmp_path / "same_title.md"
    b.write_text(SAMPLE_MARKDOWN + "\nExtra line to change the sha.\n", encoding="utf-8")
    card_a, _ = await store.add_book(a, title="Same Title")
    card_b, _ = await store.add_book(b, title="Same Title")
    assert card_a.book_id == "same-title"
    assert card_b.book_id == "same-title-2"


@pytest.mark.asyncio
async def test_read_surface_toc_search_and_section(store, book_md):
    card, _ = await store.add_book(book_md)
    toc = store.get_toc(card.book_id)
    assert toc["entries"]
    node_id = toc["entries"][0]["node_id"]
    section = store.read_section(card.book_id, node_id)
    assert section["book_title"] == card.title
    assert section["content"]
    hits = await store.search_book(card.book_id, "vector search")
    assert hits and {"node_id", "title", "score"} <= set(hits[0])


@pytest.mark.asyncio
async def test_read_section_unknown_node(store, book_md):
    card, _ = await store.add_book(book_md)
    with pytest.raises(BookstoreError, match="Unknown section"):
        store.read_section(card.book_id, "9999")


@pytest.mark.asyncio
async def test_no_llm_search_book_is_bm25_only(store_no_llm, book_md):
    card, _ = await store_no_llm.add_book(book_md)
    hits = await store_no_llm.search_book(card.book_id, "vector search")
    assert hits
    assert all(hit["source"] == "bm25" for hit in hits)


@pytest.mark.asyncio
async def test_cross_book_search_no_llm(store_no_llm, book_md):
    card, _ = await store_no_llm.add_book(book_md)
    out = await store_no_llm.search("vector search")
    assert out["books"]
    assert out["books"][0]["book_id"] == card.book_id
    assert out["books"][0]["results"]


@pytest.mark.asyncio
async def test_remove_book(store, book_md, locations):
    card, _ = await store.add_book(book_md)
    assert await store.remove_book(card.book_id) is True
    assert not (locations[0].trees_dir / f"{card.book_id}.json").exists()
    with pytest.raises(BookstoreError):
        store.get_card(card.book_id)


@pytest.mark.asyncio
async def test_global_scope_ingest_and_resolution(store, book_md, locations):
    card, _ = await store.add_book(book_md, scope="global")
    assert card.scope == "global"
    assert (locations[1].trees_dir / f"{card.book_id}.json").is_file()
    resolved, loc = store.resolve_book(card.book_id)
    assert loc.scope == "global"
    assert resolved.scope == "global"


def test_bookstore_requires_locations():
    with pytest.raises(BookstoreError):
        Bookstore([])
