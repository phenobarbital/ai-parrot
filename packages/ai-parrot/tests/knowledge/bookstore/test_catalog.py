"""Tests for the SQLite + FTS5 catalog store."""

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from parrot.knowledge.bookstore.catalog import (
    CatalogStore,
    merged_cards,
    merged_relations,
    merged_search,
)
from parrot.knowledge.bookstore.models import (
    BookCard,
    BookCommunity,
    BookRelation,
    RelationJudgement,
    TocEntry,
)


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
    count = conn.execute("SELECT COUNT(*) FROM books_fts WHERE book_id = 'clean-code'").fetchone()[0]
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
        "CREATE VIRTUAL TABLE IF NOT EXISTS books_fts " "USING no_such_module_fts5(a)",
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
    results = merged_search([("project", project), ("global", global_)], "refactoring")
    assert len(results) == 1
    assert results[0].scope == "project"


# ---------------------------------------------------------------------------
# FEAT-533 — classification migration, FTS rebuild, relations/communities
# ---------------------------------------------------------------------------


def test_added_columns_migrate_old_db(legacy_library_db):
    store = CatalogStore(legacy_library_db)
    card = store.get("meditations")
    assert card is not None
    assert card.genre == "other"
    assert card.traditions == []
    assert card.period is None
    assert card.community_id is None
    assert card.community_label is None
    # The pre-existing row's original fields survive the migration.
    assert card.title == "Meditations"
    assert card.authors == ["Marcus Aurelius"]


def test_fts_rebuilt_on_column_drift(legacy_library_db):
    store = CatalogStore(legacy_library_db)
    conn = sqlite3.connect(legacy_library_db)
    cols = tuple(r[1] for r in conn.execute("PRAGMA table_info(books_fts)"))
    conn.close()
    assert cols == (
        "book_id",
        "title",
        "authors_text",
        "topics_text",
        "summary",
        "toc_digest",
        "genre",
        "traditions_text",
    )
    # search() still works post-rebuild for the pre-existing row.
    results = store.search("stoicism")
    assert results and results[0][0].book_id == "meditations"


def test_fts_not_rebuilt_when_current(tmp_path):
    db_path = tmp_path / "library.db"
    CatalogStore(db_path)
    conn = sqlite3.connect(db_path)
    rowid_before = conn.execute("SELECT rowid FROM sqlite_master WHERE name = 'books_fts'").fetchone()[0]
    conn.close()
    # A second open (and a write, which also runs _ensure_schema) must
    # not touch the already-current books_fts table.
    store2 = CatalogStore(db_path)
    store2.upsert(_card())
    conn = sqlite3.connect(db_path)
    rowid_after = conn.execute("SELECT rowid FROM sqlite_master WHERE name = 'books_fts'").fetchone()[0]
    conn.close()
    assert rowid_before == rowid_after


def test_traditions_slug_normalised_on_upsert(store):
    store.upsert(_card(traditions=["Estoicismo", "estoicismo", "Ética"]))
    card = store.get("clean-code")
    assert card.traditions == ["estoicismo", "etica"]


def test_search_hits_traditions_and_genre(store):
    store.upsert(_card(genre="essay", traditions=["Estoicismo"]))
    results = store.search("estoicismo")
    assert results and results[0][0].book_id == "clean-code"


def test_relation_pk_replaces_and_self_pair_rejected(store):
    rel = BookRelation(
        src_book_id="a",
        dst_book_id="b",
        rel="same_author",
        origin="deterministic",
        computed_at="2026-09-06T00:00:00+00:00",
    )
    store.upsert_relations([rel])
    updated = rel.model_copy(update={"weight": 0.5})
    store.upsert_relations([updated])
    relations = store.list_relations("a")
    assert len(relations) == 1
    assert relations[0].weight == 0.5
    with pytest.raises(ValidationError):
        BookRelation(
            src_book_id="a",
            dst_book_id="a",
            rel="same_author",
            origin="deterministic",
            computed_at="2026-09-06T00:00:00+00:00",
        )


def test_symmetric_rel_canonical_order(store):
    rel = BookRelation(
        src_book_id="b",
        dst_book_id="a",
        rel="parallels",
        origin="llm",
        confidence=0.7,
        computed_at="2026-09-06T00:00:00+00:00",
    )
    store.upsert_relations([rel])
    relations = store.list_relations("a")
    assert len(relations) == 1
    assert relations[0].src_book_id == "a"
    assert relations[0].dst_book_id == "b"


def test_directed_rel_keeps_direction(store):
    rel = BookRelation(
        src_book_id="b",
        dst_book_id="a",
        rel="influenced_by",
        origin="llm",
        confidence=0.9,
        computed_at="2026-09-06T00:00:00+00:00",
    )
    store.upsert_relations([rel])
    relations = store.list_relations("a")
    assert len(relations) == 1
    assert relations[0].src_book_id == "b"
    assert relations[0].dst_book_id == "a"


def test_list_relations_both_directions_and_rel_filter(store):
    store.upsert_relations(
        [
            BookRelation(
                src_book_id="a",
                dst_book_id="b",
                rel="same_author",
                origin="deterministic",
                computed_at="2026-09-06T00:00:00+00:00",
            ),
            BookRelation(
                src_book_id="c",
                dst_book_id="a",
                rel="same_genre",
                origin="deterministic",
                computed_at="2026-09-06T00:00:00+00:00",
            ),
        ]
    )
    all_for_a = store.list_relations("a")
    assert len(all_for_a) == 2
    only_same_author = store.list_relations("a", rel="same_author")
    assert len(only_same_author) == 1
    assert only_same_author[0].rel == "same_author"


def test_delete_relations_by_book_and_origin(store):
    store.upsert_relations(
        [
            BookRelation(
                src_book_id="a",
                dst_book_id="b",
                rel="same_author",
                origin="deterministic",
                computed_at="2026-09-06T00:00:00+00:00",
            ),
            BookRelation(
                src_book_id="a",
                dst_book_id="c",
                rel="parallels",
                origin="llm",
                confidence=0.7,
                computed_at="2026-09-06T00:00:00+00:00",
            ),
        ]
    )
    deleted = store.delete_relations(origin="llm")
    assert deleted == 1
    remaining = store.list_relations("a")
    assert len(remaining) == 1
    assert remaining[0].origin == "deterministic"
    deleted = store.delete_relations(book_id="a")
    assert deleted == 1
    assert store.list_relations("a") == []


def test_judgements_record_and_judged_pairs(store):
    store.record_judgements(
        "a",
        [
            RelationJudgement(dst_book_id="b", rel="parallels", confidence=0.7),
            RelationJudgement(dst_book_id="c", rel="none", confidence=0.2),
        ],
        model="test-model",
    )
    assert store.judged_pairs("a") == {"b", "c"}
    assert store.judged_pairs("z") == set()
    deleted = store.delete_judgements("b")
    assert deleted == 1
    assert store.judged_pairs("a") == {"c"}


def test_communities_replace_all_and_get(store):
    c1 = BookCommunity(
        community_id="c1",
        label="Stoics",
        label_origin="llm",
        algorithm="leiden",
        size=2,
        cohesion=1.0,
        centroid_book_id="a",
        member_book_ids=["a", "b"],
        computed_at="2026-09-06T00:00:00+00:00",
    )
    store.upsert_communities([c1])
    assert store.get_community("c1").label == "Stoics"
    assert len(store.list_communities()) == 1
    c2 = BookCommunity(
        community_id="c2",
        label="Epicureans",
        label_origin="derived",
        algorithm="leiden",
        size=1,
        cohesion=0.0,
        centroid_book_id="d",
        member_book_ids=["d"],
        computed_at="2026-09-06T00:00:00+00:00",
    )
    store.upsert_communities([c2])
    # Replace-all: c1 is gone.
    assert store.get_community("c1") is None
    assert [c.community_id for c in store.list_communities()] == ["c2"]


def test_merged_relations_filters_dangling_and_project_wins(tmp_path):
    project = CatalogStore(tmp_path / "p.db")
    global_ = CatalogStore(tmp_path / "g.db")
    now = "2026-09-06T00:00:00+00:00"
    project.upsert_relations(
        [
            BookRelation(src_book_id="a", dst_book_id="b", rel="same_author", origin="deterministic", computed_at=now),
        ]
    )
    global_.upsert_relations(
        [
            # Same edge, different weight — project's copy should win.
            BookRelation(
                src_book_id="a", dst_book_id="b", rel="same_author", origin="deterministic", weight=0.5, computed_at=now
            ),
            # Dangling: "ghost" is not in visible_ids.
            BookRelation(
                src_book_id="a", dst_book_id="ghost", rel="same_genre", origin="deterministic", computed_at=now
            ),
        ]
    )
    merged = merged_relations([("project", project), ("global", global_)], visible_ids={"a", "b"})
    assert len(merged) == 1
    assert merged[0].weight == 1.0
