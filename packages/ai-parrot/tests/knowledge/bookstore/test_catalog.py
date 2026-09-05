"""Tests for the SQLite + FTS5 catalog store."""

from __future__ import annotations

import sqlite3

import pytest

from parrot.knowledge.bookstore.catalog import (
    CatalogStore,
    merged_cards,
    merged_search,
)
from parrot.knowledge.bookstore.models import BookCard, TocEntry


def _card(book_id: str = "clean-code", **overrides) -> BookCard:
    data = {
        "book_id": book_id,
        "title": "Clean Code",
        "authors": ["Robert C. Martin"],
        "year": 2008,
        "language": "en",
        "topics": ["refactoring", "naming", "unit testing"],
        "summary": "A handbook of agile software craftsmanship.",
        "toc_digest": "1 Clean Code (pp. 1-20)\n2 Meaningful Names (pp. 21-40)",
        "toc": [TocEntry(node_id="0000", title="Clean Code", depth=1)],
        "tree_name": book_id,
        "source_path": f"/books/{book_id}.pdf",
        "source_sha256": f"{book_id:0<64}"[:64],
        "source_format": "pdf",
        "page_count": 464,
        "chapter_count": 17,
        "added_at": "2026-09-05T00:00:00+00:00",
    }
    data.update(overrides)
    return BookCard(**data)


@pytest.fixture
def store(tmp_path) -> CatalogStore:
    return CatalogStore(tmp_path / "library.db")


def test_upsert_get_roundtrip(store):
    card = _card()
    store.upsert(card)
    loaded = store.get("clean-code")
    assert loaded is not None
    assert loaded.title == "Clean Code"
    assert loaded.authors == ["Robert C. Martin"]
    assert loaded.toc[0].node_id == "0000"


def test_upsert_twice_keeps_single_fts_row(store, tmp_path):
    store.upsert(_card())
    store.upsert(_card(summary="Updated summary about refactoring."))
    conn = sqlite3.connect(tmp_path / "library.db")
    count = conn.execute(
        "SELECT COUNT(*) FROM books_fts WHERE book_id = 'clean-code'"
    ).fetchone()[0]
    conn.close()
    assert count == 1
    assert "Updated summary" in store.get("clean-code").summary


def test_fts_search_ranks_relevant_book_first(store):
    store.upsert(_card())
    store.upsert(
        _card(
            "sicp",
            title="Structure and Interpretation of Computer Programs",
            topics=["lisp", "recursion", "abstraction"],
            summary="Classic text on programming abstractions in Scheme.",
            toc_digest="1 Building Abstractions (pp. 1-100)",
            source_sha256="b" * 64,
        )
    )
    results = store.search("refactoring and naming things")
    assert results
    assert results[0][0].book_id == "clean-code"


def test_fts_query_sanitizes_punctuation(store):
    store.upsert(_card())
    # Raw colons/quotes would be FTS5 syntax errors if passed through.
    results = store.search('naming: "the hard parts" (chapter 2)')
    assert results and results[0][0].book_id == "clean-code"


def test_find_by_sha_and_remove(store):
    card = _card()
    store.upsert(card)
    assert store.find_by_sha(card.source_sha256).book_id == "clean-code"
    assert store.remove("clean-code") is True
    assert store.remove("clean-code") is False
    assert store.get("clean-code") is None
    assert store.search("refactoring") == []


def test_taken_slugs(store):
    store.upsert(_card())
    store.upsert(_card("sicp", tree_name="sicp", source_sha256="b" * 64))
    assert store.taken_slugs() == {"clean-code", "sicp"}


def test_additive_migration(tmp_path, monkeypatch):
    db = tmp_path / "library.db"
    CatalogStore(db)  # create current schema
    conn = sqlite3.connect(db)
    conn.execute("ALTER TABLE books DROP COLUMN card_origin")
    conn.commit()
    conn.close()
    monkeypatch.setattr(
        "parrot.knowledge.bookstore.catalog._ADDED_COLUMNS",
        [("card_origin", "card_origin TEXT NOT NULL DEFAULT 'llm'")],
    )
    migrated = CatalogStore(db)
    migrated.upsert(_card())
    assert migrated.get("clean-code").card_origin == "llm"


def test_fts_unavailable_falls_back_to_like(tmp_path, monkeypatch):
    # Simulate a SQLite build without FTS5: the virtual-table DDL raises
    # OperationalError, exactly like `no such module: fts5`.
    monkeypatch.setattr(
        "parrot.knowledge.bookstore.catalog._FTS_DDL",
        "CREATE VIRTUAL TABLE IF NOT EXISTS books_fts "
        "USING no_such_module_fts5(a)",
    )
    store = CatalogStore(tmp_path / "library.db")
    assert store.supports_fts is False
    store.upsert(_card())
    results = store.search("refactoring")
    assert results and results[0][0].book_id == "clean-code"


def test_merged_cards_project_wins(tmp_path):
    project = CatalogStore(tmp_path / "p.db")
    global_ = CatalogStore(tmp_path / "g.db")
    project.upsert(_card(summary="project copy"))
    global_.upsert(_card(summary="global copy"))
    global_.upsert(_card("sicp", tree_name="sicp", source_sha256="b" * 64))
    merged = merged_cards([("project", project), ("global", global_)])
    by_id = {card.book_id: card for card in merged}
    assert by_id["clean-code"].summary == "project copy"
    assert by_id["clean-code"].scope == "project"
    assert by_id["sicp"].scope == "global"


def test_merged_search_dedupes_and_stamps_scope(tmp_path):
    project = CatalogStore(tmp_path / "p.db")
    global_ = CatalogStore(tmp_path / "g.db")
    project.upsert(_card())
    global_.upsert(_card())
    results = merged_search(
        [("project", project), ("global", global_)], "refactoring"
    )
    assert len(results) == 1
    assert results[0].scope == "project"
