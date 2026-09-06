"""Tests for BookstoreToolkit (agent-facing tool surface)."""

from __future__ import annotations

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.bookstore.toolkit import BookstoreToolkit

from .conftest import SAMPLE_MARKDOWN

EXPECTED_TOOLS = {
    "bookstore_catalog_search",
    "bookstore_list_books",
    "bookstore_get_card",
    "bookstore_get_toc",
    "bookstore_search_book",
    "bookstore_read_section",
    "bookstore_related_books",
    "bookstore_communities",
    "bookstore_get_community",
    "bookstore_search",
}


@pytest.fixture
def bookstore(tmp_path, fake_adapter) -> Bookstore:
    locations = [
        LibraryLocation(scope="project", root=tmp_path / "proj" / "library"),
        LibraryLocation(scope="global", root=tmp_path / "glob" / "library"),
    ]
    return Bookstore(locations, adapter=fake_adapter)


@pytest.fixture
def toolkit(bookstore) -> BookstoreToolkit:
    return BookstoreToolkit(bookstore=bookstore)


@pytest.fixture
def book_md(tmp_path):
    path = tmp_path / "synthetic-handbook.md"
    path.write_text(SAMPLE_MARKDOWN, encoding="utf-8")
    return path


def test_tool_discovery_exposes_exactly_the_read_surface(toolkit):
    assert set(toolkit.list_tool_names()) == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_catalog_search_never_touches_the_llm(
    toolkit, bookstore, book_md, fake_adapter
):
    await bookstore.add_book(book_md)
    fake_adapter.ask.reset_mock()
    fake_adapter.ask_structured.reset_mock()
    results = await toolkit.catalog_search("async python")
    assert results and results[0]["book_id"] == "synthetic-handbook"
    fake_adapter.ask.assert_not_awaited()
    fake_adapter.ask_structured.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_card_omits_bulky_fields(toolkit, bookstore, book_md):
    card, _ = await bookstore.add_book(book_md)
    data = await toolkit.get_card(card.book_id)
    assert data["title"] == card.title
    assert data["toc_digest"]
    assert "toc" not in data and "source_sha256" not in data


@pytest.mark.asyncio
async def test_get_card_and_briefs_include_classification(toolkit, bookstore, book_md):
    card, _ = await bookstore.add_book(book_md)
    full = await toolkit.get_card(card.book_id)
    assert full["genre"] == "essay"
    assert full["traditions"] == ["estoicismo"]
    assert full["period"] == "Imperio romano"

    search_results = await toolkit.catalog_search("async python")
    assert search_results[0]["genre"] == "essay"
    assert search_results[0]["traditions"] == ["estoicismo"]

    listed = await toolkit.list_books()
    assert listed[0]["genre"] == "essay"


@pytest.mark.asyncio
async def test_funnel_toc_search_read(toolkit, bookstore, book_md):
    card, _ = await bookstore.add_book(book_md)
    toc = await toolkit.get_toc(card.book_id)
    assert toc["entries"]
    hits = await toolkit.search_book(card.book_id, "vector search")
    assert hits
    section = await toolkit.read_section(card.book_id, hits[0]["node_id"])
    assert section["content"]
    assert section["book_title"] == card.title


@pytest.mark.asyncio
async def test_search_clamps_max_books(toolkit, bookstore, book_md, monkeypatch):
    await bookstore.add_book(book_md)
    captured: dict = {}

    async def _spy(query, book_ids=None, max_books=3, **kwargs):
        captured["max_books"] = max_books
        return {"query": query, "books": []}

    monkeypatch.setattr(bookstore, "search", _spy)
    await toolkit.search("anything", max_books=500)
    assert captured["max_books"] == 10
    await toolkit.search("anything", max_books=-4)
    assert captured["max_books"] == 1


@pytest.mark.asyncio
async def test_list_books_merges_scopes(toolkit, bookstore, book_md, tmp_path):
    await bookstore.add_book(book_md)
    other = tmp_path / "other-book.md"
    other.write_text(SAMPLE_MARKDOWN + "\nAnother sha.\n", encoding="utf-8")
    await bookstore.add_book(other, scope="global", title="Other Book")
    listed = await toolkit.list_books()
    scopes = {entry["book_id"]: entry["scope"] for entry in listed}
    assert scopes["synthetic-handbook"] == "project"
    assert scopes["other-book"] == "global"


# ---------------------------------------------------------------------------
# FEAT-533 — related_books / communities / get_community / expand_related
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toolkit_related_books_clamps(toolkit, bookstore, monkeypatch):
    captured: dict = {}

    def _spy(book_id, rel=None, depth=1, top_k=10, min_confidence=0.0):
        captured["depth"] = depth
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(bookstore, "related_books", _spy)
    await toolkit.related_books("a", depth=99, top_k=999)
    assert captured == {"depth": 2, "top_k": 50}
    await toolkit.related_books("a", depth=0, top_k=0)
    assert captured == {"depth": 1, "top_k": 1}


@pytest.mark.asyncio
async def test_toolkit_communities_and_get_community(toolkit, bookstore, book_md):
    card, _ = await bookstore.add_book(book_md)
    other = book_md.parent / "other-book.md"
    other.write_text(SAMPLE_MARKDOWN + "\nAnother sha.\n", encoding="utf-8")
    card2, _ = await bookstore.add_book(other, title="Other Book")
    third = book_md.parent / "third-book.md"
    third.write_text(SAMPLE_MARKDOWN + "\nYet another sha.\n", encoding="utf-8")
    await bookstore.add_book(third, title="Third Book")

    await bookstore.relate_books(None, use_llm=False)

    communities = await toolkit.communities()
    assert communities
    for community in communities:
        assert "inter_relations" not in community
        assert "member_book_ids" not in community
        assert community["members"]
        for member in community["members"]:
            assert set(member) == {"book_id", "title"}

    community_id = communities[0]["community_id"]
    full = await toolkit.get_community(community_id)
    assert full["community_id"] == community_id
    assert "inter_relations" in full


@pytest.mark.asyncio
async def test_toolkit_get_community_unknown(toolkit):
    with pytest.raises(BookstoreError):
        await toolkit.get_community("does-not-exist")


@pytest.mark.asyncio
async def test_search_expand_related_respects_max_books(toolkit, bookstore, monkeypatch):
    captured: dict = {}

    async def _spy(query, book_ids=None, max_books=3, expand_related=False, **kwargs):
        captured["expand_related"] = expand_related
        captured["max_books"] = max_books
        return {"query": query, "books": []}

    monkeypatch.setattr(bookstore, "search", _spy)
    await toolkit.search("anything", max_books=2, expand_related=True)
    assert captured == {"expand_related": True, "max_books": 2}
