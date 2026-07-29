"""Unit tests for FEAT-379 core models: SearchOriginKind, OriginHit,
OriginSection, MultiSearchResponse, and the MultiSearch protocol.
"""
from parrot.models import (
    SearchOriginKind,
    OriginHit,
    OriginSection,
    MultiSearchResponse,
    MultiSearch,
    StoreType,
)


def test_store_type_unchanged():
    """StoreType must remain DB-store-only after this feature."""
    assert {m.name for m in StoreType} == {"PGVECTOR", "FAISS", "ARANGO"}


def test_origin_kind_values():
    """SearchOriginKind covers the four multi-search origin families."""
    assert {k.value for k in SearchOriginKind} == {
        "vector",
        "pageindex",
        "graphindex",
        "wiki",
    }


def test_origin_hit_validation():
    """OriginHit validates with the contractual field names."""
    hit = OriginHit(
        id="1",
        content="x",
        score=0.5,
        metadata={},
        origin="pgvector",
        origin_kind=SearchOriginKind.VECTOR,
        native_rank=1,
    )
    assert hit.native_rank == 1
    assert hit.origin == "pgvector"
    assert hit.origin_kind is SearchOriginKind.VECTOR


def test_origin_hit_optional_id_and_score():
    """id and score are optional (some origins may not provide them)."""
    hit = OriginHit(
        content="x",
        metadata={},
        origin="wiki",
        origin_kind=SearchOriginKind.WIKI,
        native_rank=1,
    )
    assert hit.id is None
    assert hit.score is None


def test_origin_section_defaults():
    """OriginSection defaults hits to an empty list."""
    section = OriginSection(
        origin="wiki",
        origin_kind=SearchOriginKind.WIKI,
        description="ParrotWiki FTS + vector search",
        status="ok",
    )
    assert section.hits == []
    assert section.note is None


def test_multi_search_response_defaults():
    """MultiSearchResponse defaults sections/merged_top_k/notes to empty."""
    response = MultiSearchResponse(query="hello")
    assert response.sections == []
    assert response.merged_top_k == []
    assert response.notes == []


def test_multisearch_protocol_runtime_check():
    """isinstance check against MultiSearch is runtime-checkable."""

    class Ok:
        async def search(self, query, k=None, **kw):
            ...

    class NotOk:
        ...

    assert isinstance(Ok(), MultiSearch)
    assert not isinstance(NotOk(), MultiSearch)
