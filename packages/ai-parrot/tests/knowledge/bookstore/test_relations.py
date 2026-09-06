"""Tests for Stage 1 deterministic relations + the related_books read path."""

from __future__ import annotations

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore
from parrot.knowledge.bookstore.models import BookCard, BookRelation, RelationJudgement
from parrot.knowledge.bookstore.relations import _author_key, deterministic_relations

_NOW = "2026-09-06T00:00:00+00:00"


def _card(book_id: str, **overrides) -> BookCard:
    data = {
        "book_id": book_id,
        "title": book_id.replace("-", " ").title(),
        "tree_name": book_id,
        "source_path": f"/books/{book_id}.md",
        "source_sha256": f"{book_id:0<64}"[:64],
        "source_format": "md",
        "added_at": _NOW,
    }
    data.update(overrides)
    return BookCard(**data)


# ---------------------------------------------------------------------------
# Pure Stage 1 functions
# ---------------------------------------------------------------------------


def test_deterministic_same_author_slugified():
    a = _card("play-one", authors=["Calderón de la Barca"])
    b = _card("play-two", authors=["Calderon de la Barca"])
    rels = deterministic_relations([a, b], now=_NOW)
    same_author = [r for r in rels if r.rel == "same_author"]
    assert len(same_author) == 1
    assert (same_author[0].src_book_id, same_author[0].dst_book_id) == (
        "play-one",
        "play-two",
    )


def test_deterministic_author_fallback_slug_ignored():
    # Non-Latin names with no ASCII decomposition collapse to "book"
    # (carding.slugify) — must never be treated as a shared author.
    a = _card("analects", authors=["孔子"])
    b = _card("great-learning", authors=["論語"])
    assert _author_key("孔子") is None
    rels = deterministic_relations([a, b], now=_NOW)
    assert not [r for r in rels if r.rel == "same_author"]


def test_deterministic_shares_topic_jaccard():
    a = _card("a", topics=["stoicism", "ethics", "virtue"])
    b = _card("b", topics=["stoicism", "ethics", "logic", "physics"])
    # |{stoicism, ethics}| / |{stoicism, ethics, virtue, logic, physics}| = 2/5
    rels = deterministic_relations([a, b], now=_NOW)
    shares = [r for r in rels if r.rel == "shares_topic"]
    assert len(shares) == 1
    assert shares[0].weight == pytest.approx(0.4)

    # Below the 0.2 default threshold: 1/6.
    c = _card("c", topics=["stoicism"])
    d = _card("d", topics=["logic", "physics", "biology", "chemistry", "math"])
    below = deterministic_relations([c, d], now=_NOW)
    assert not [r for r in below if r.rel == "shares_topic"]


def test_deterministic_same_tradition_and_genre():
    a = _card("a", traditions=["Estoicismo"], genre="essay")
    b = _card("b", traditions=["estoicismo"], genre="essay")
    rels = deterministic_relations([a, b], now=_NOW)
    assert any(r.rel == "same_tradition" for r in rels)
    assert any(r.rel == "same_genre" for r in rels)

    # The "other" default must never produce a same_genre match.
    c = _card("c", genre="other")
    d = _card("d", genre="other")
    unclassified = deterministic_relations([c, d], now=_NOW)
    assert not [r for r in unclassified if r.rel == "same_genre"]


def test_deterministic_same_era_window_and_period():
    a = _card("a", year=1600)
    b = _card("b", year=1620)  # within the 50-year window
    rels = deterministic_relations([a, b], now=_NOW)
    assert any(r.rel == "same_era" for r in rels)

    c = _card("c", year=1000)
    d = _card("d", year=2000)  # far apart, no period fallback
    far_apart = deterministic_relations([c, d], now=_NOW)
    assert not [r for r in far_apart if r.rel == "same_era"]

    e = _card("e", period="Siglo de Oro")
    f = _card("f", period="siglo de oro")
    by_period = deterministic_relations([e, f], now=_NOW)
    assert any(r.rel == "same_era" for r in by_period)


def test_deterministic_same_language_requires_both():
    a = _card("a", language="es")
    b = _card("b", language="es")
    rels = deterministic_relations([a, b], now=_NOW)
    assert any(r.rel == "same_language" for r in rels)

    c = _card("c", language="es")
    d = _card("d", language=None)
    one_missing = deterministic_relations([c, d], now=_NOW)
    assert not [r for r in one_missing if r.rel == "same_language"]


def test_deterministic_canonical_symmetric_order():
    a = _card("zzz", authors=["Same Author"])
    b = _card("aaa", authors=["Same Author"])
    rels = deterministic_relations([a, b], now=_NOW)
    same_author = [r for r in rels if r.rel == "same_author"][0]
    assert (same_author.src_book_id, same_author.dst_book_id) == ("aaa", "zzz")


# ---------------------------------------------------------------------------
# Bookstore read path + cascade
# ---------------------------------------------------------------------------


@pytest.fixture
def locations(tmp_path) -> list[LibraryLocation]:
    return [
        LibraryLocation(scope="project", root=tmp_path / "proj" / "library"),
        LibraryLocation(scope="global", root=tmp_path / "glob" / "library"),
    ]


@pytest.fixture
def store(locations) -> Bookstore:
    return Bookstore(locations)


@pytest.mark.asyncio
async def test_related_books_depth2_and_filters(store):
    project = store._catalog("project")
    for card in (_card("a"), _card("b"), _card("c"), _card("d")):
        project.upsert(card)
    project.upsert_relations(
        [
            BookRelation(
                src_book_id="a", dst_book_id="b", rel="same_author",
                origin="deterministic", weight=0.9, computed_at=_NOW,
            ),
            BookRelation(
                src_book_id="b", dst_book_id="c", rel="same_tradition",
                origin="deterministic", weight=0.7, computed_at=_NOW,
            ),
            BookRelation(
                src_book_id="a", dst_book_id="d", rel="parallels",
                origin="llm", confidence=0.3, computed_at=_NOW,
            ),
        ]
    )

    depth1 = store.related_books("a", depth=1)
    assert {item["book"]["book_id"] for item in depth1} == {"b", "d"}

    depth2 = store.related_books("a", depth=2)
    ids2 = {item["book"]["book_id"]: item["hop"] for item in depth2}
    assert ids2 == {"b": 1, "d": 1, "c": 2}

    only_same_author = store.related_books("a", rel="same_author")
    assert {item["book"]["book_id"] for item in only_same_author} == {"b"}

    above_confidence = store.related_books("a", min_confidence=0.5)
    assert "d" not in {item["book"]["book_id"] for item in above_confidence}

    limited = store.related_books("a", depth=2, top_k=1)
    assert len(limited) == 1


@pytest.mark.asyncio
async def test_cross_scope_edge_stored_in_src_scope_and_dangling_filtered(store):
    project = store._catalog("project")
    global_ = store._catalog("global")
    project.upsert(_card("a", scope="project"))
    global_.upsert(_card("g-book", scope="global"))

    relation = BookRelation(
        src_book_id="g-book", dst_book_id="a", rel="same_author",
        origin="deterministic", computed_at=_NOW,
    )
    store._write_deterministic([relation])
    assert global_.list_relations("g-book")
    assert project.list_relations("a") == []

    # Dangling: an edge in the global DB pointing to a book invisible
    # to this Bookstore must be filtered out on read, never raise.
    ghost = BookRelation(
        src_book_id="g-book", dst_book_id="ghost", rel="same_genre",
        origin="deterministic", computed_at=_NOW,
    )
    global_.upsert_relations([ghost])
    results = store.related_books("a")
    ids = {item["book"]["book_id"] for item in results}
    assert "g-book" in ids
    assert "ghost" not in ids


@pytest.mark.asyncio
async def test_remove_book_cascades_relations_and_judgements(store):
    project = store._catalog("project")
    global_ = store._catalog("global")
    project.upsert(_card("a"))
    project.upsert(_card("c"))
    global_.upsert(_card("b"))

    project.upsert_relations(
        [
            BookRelation(
                src_book_id="a", dst_book_id="c", rel="same_author",
                origin="deterministic", computed_at=_NOW,
            ),
        ]
    )
    global_.upsert_relations(
        [
            BookRelation(
                src_book_id="b", dst_book_id="a", rel="same_tradition",
                origin="deterministic", computed_at=_NOW,
            ),
        ]
    )
    global_.record_judgements(
        "b", [RelationJudgement(dst_book_id="a", rel="parallels", confidence=0.6)]
    )

    await store.remove_book("a")

    assert project.list_relations("a") == []
    assert global_.list_relations("a") == []
    assert global_.judged_pairs("b") == set()
