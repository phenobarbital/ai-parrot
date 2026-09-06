"""Tests for Stage 3 — communities via graphindex."""

from __future__ import annotations

import pytest

from parrot.knowledge.bookstore.config import LibraryLocation
from parrot.knowledge.bookstore.library import Bookstore, BookstoreError
from parrot.knowledge.bookstore.models import (
    BookCard,
    BookRelation,
    CommunityLabelDraft,
    REL_WEIGHTS,
)
from parrot.knowledge.bookstore.relations import (
    build_book_graph,
    deterministic_relations,
    detect_book_communities,
    fallback_label,
)
from parrot.knowledge.graphindex.communities import Community

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
# Pure graph-adapter / labelling functions
# ---------------------------------------------------------------------------


def test_build_book_graph_edge_weights_and_provenance():
    a, b, c = _card("a"), _card("b"), _card("c")
    relations = [
        BookRelation(
            src_book_id="a", dst_book_id="b", rel="parallels", origin="llm",
            confidence=0.7, weight=REL_WEIGHTS["parallels"], computed_at=_NOW,
        ),
        BookRelation(
            src_book_id="b", dst_book_id="c", rel="same_author",
            origin="deterministic", weight=REL_WEIGHTS["same_author"],
            computed_at=_NOW,
        ),
        BookRelation(
            src_book_id="a", dst_book_id="c", rel="same_community",
            origin="community", computed_at=_NOW,
        ),
    ]
    assembler, nodes = build_book_graph([a, b, c], relations)

    assert {n.node_id for n in nodes} == {"a", "b", "c"}
    # same_community is excluded — only the two other relations become edges.
    assert assembler.edge_count == 2

    ab = assembler.get_edges_for_node("a", direction="outgoing")[0]
    assert ab["provenance"] == "inferred"
    assert ab["confidence"] == 0.7
    assert ab["weight"] == REL_WEIGHTS["parallels"]

    bc = [
        e for e in assembler.get_edges_for_node("b", direction="outgoing")
        if e["target_id"] == "c"
    ][0]
    assert bc["provenance"] == "extracted"
    assert bc["confidence"] is None
    assert bc["weight"] == REL_WEIGHTS["same_author"]


def test_detect_book_communities_two_clusters():
    group_a = [_card(f"a{i}", authors=["Author A"]) for i in range(4)]
    group_b = [_card(f"b{i}", authors=["Author B"]) for i in range(4)]
    cards = group_a + group_b
    relations = deterministic_relations(cards, now=_NOW)

    result, inter, _assembler = detect_book_communities(cards, relations)

    assert len(result.communities) == 2
    assert sorted(c.size for c in result.communities) == [4, 4]


def test_fallback_label_derived_and_singleton_title():
    cards_by_id = {
        "a": _card("a", title="Stoic Ethics"),
        "b": _card("b", title="Stoic Meditations"),
    }
    community = Community(
        community_id="c1", size=2, member_node_ids=["a", "b"],
        centroid_node_id="a", cohesion=1.0, modularity_contribution=0.1,
        top_titles=["Stoic Ethics", "Stoic Meditations"],
    )
    label, origin = fallback_label(community, cards_by_id)
    assert origin == "derived"
    assert label == "Stoic Ethics Meditations"

    singleton = Community(
        community_id="c2", size=1, member_node_ids=["a"],
        centroid_node_id="a", cohesion=0.0, modularity_contribution=0.0,
        top_titles=["Stoic Ethics"],
    )
    label2, origin2 = fallback_label(singleton, cards_by_id)
    assert origin2 == "title"
    assert label2 == "Stoic Ethics"


# ---------------------------------------------------------------------------
# Bookstore Stage 3 orchestration
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


@pytest.fixture
def store_llm(locations, fake_adapter) -> Bookstore:
    return Bookstore(locations, adapter=fake_adapter)


@pytest.mark.asyncio
async def test_stage3_skipped_under_three_cards(store):
    project = store._catalog("project")
    project.upsert(_card("a"))
    project.upsert(_card("b"))

    summary = await store.relate_books(None, use_llm=False)

    assert summary.communities is None
    assert any("skipped (<3 books)" in note for note in summary.notes)
    assert store.communities() == []


@pytest.mark.asyncio
async def test_stage3_persists_partition_and_same_community_edges(store):
    project = store._catalog("project")
    for card in (
        [_card(f"a{i}", authors=["Author A"]) for i in range(3)]
        + [_card(f"b{i}", authors=["Author B"]) for i in range(3)]
    ):
        project.upsert(card)

    summary = await store.relate_books(None, use_llm=False)

    assert summary.communities == 2
    communities = store.communities()
    assert len(communities) == 2
    for community in communities:
        assert community.label_origin in ("derived", "title")

    same_community = project.list_relations("a0", rel="same_community")
    assert same_community

    card_a0 = project.get("a0")
    assert card_a0.community_id is not None
    assert card_a0.community_label is not None


@pytest.mark.asyncio
async def test_stage3_rewrites_same_community_edges(store):
    project = store._catalog("project")
    for card in (
        _card("a", authors=["Author X"]), _card("b", authors=["Author X"]), _card("c", authors=["Author Y"]),
    ):
        project.upsert(card)
    # A stale edge that must not survive Stage 3's rewrite.
    project.upsert_relations(
        [
            BookRelation(
                src_book_id="a", dst_book_id="c", rel="same_community",
                origin="community", computed_at=_NOW,
            ),
        ]
    )

    await store.relate_books(None, use_llm=False)

    stale = [
        r for r in project.list_relations("a", rel="same_community")
        if r.dst_book_id == "c"
    ]
    assert stale == []


@pytest.mark.asyncio
async def test_stage3_labels_llm_then_fallback_on_error(store_llm, fake_adapter):
    project = store_llm._catalog("project")
    for card in (
        _card("a", authors=["Author X"], title="Stoic Ethics"),
        _card("b", authors=["Author X"], title="Stoic Meditations"),
        _card("c", authors=["Author Y"], title="Unrelated Topic"),
    ):
        project.upsert(card)

    summary = await store_llm.relate_books(None, use_llm=False)
    assert summary.communities == 2
    assert any(c.label_origin == "llm" for c in store_llm.communities())

    original_side_effect = fake_adapter.ask_structured.side_effect

    def _raising(prompt, schema, **kwargs):
        if schema is CommunityLabelDraft:
            raise RuntimeError("label boom")
        return original_side_effect(prompt, schema, **kwargs)

    fake_adapter.ask_structured.side_effect = _raising
    summary2 = await store_llm.relate_books(None, use_llm=False)
    assert summary2.communities == 2
    for community in store_llm.communities():
        assert community.label_origin in ("derived", "title")


@pytest.mark.asyncio
async def test_communities_table_in_project_db_only(store):
    project = store._catalog("project")
    global_ = store._catalog("global")
    project.upsert(_card("a", authors=["Author X"], scope="project"))
    project.upsert(_card("b", authors=["Author X"], scope="project"))
    global_.upsert(_card("c", authors=["Author Y"], scope="global"))

    await store.relate_books(None, use_llm=False)

    assert project.list_communities()
    assert global_.list_communities() == []


@pytest.mark.asyncio
async def test_community_id_stable_for_same_membership(store):
    project = store._catalog("project")
    for card in (
        _card("a", authors=["Author X"]), _card("b", authors=["Author X"]), _card("c", authors=["Author Y"]),
    ):
        project.upsert(card)

    await store.relate_books(None, use_llm=False)
    ids1 = {c.community_id for c in store.communities()}
    await store.relate_books(None, use_llm=False)
    ids2 = {c.community_id for c in store.communities()}

    assert ids1 == ids2


def test_get_community_unknown_raises(store):
    with pytest.raises(BookstoreError):
        store.get_community("does-not-exist")
