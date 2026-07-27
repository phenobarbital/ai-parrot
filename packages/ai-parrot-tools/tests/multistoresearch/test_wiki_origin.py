"""Unit tests for ParrotWikiOrigin (FEAT-379).

Row shape matches the REAL ``SQLiteWikiStore.search_fts`` /
``search_vector`` return value (verified in
``parrot/knowledge/wiki/store.py``): ``concept_id``, ``node_id``,
``title``, ``category``, ``summary``, ``source_id``, ``token_count``,
``score`` — NOT ``page_id``/``content``.
"""
from parrot.models import SearchOriginKind
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord
from parrot_tools.multistoresearch.origins import ParrotWikiOrigin


class FakeWikiStore:
    def __init__(self):
        self.fts_calls = []
        self.vec_calls = []

    async def search_fts(self, query, category=None, limit=10):
        self.fts_calls.append((query, category))
        return [
            {
                "concept_id": "p1",
                "node_id": "n1",
                "title": "T",
                "category": "docs",
                "summary": "S",
                "source_id": "src1",
                "token_count": 42,
                "score": 1.0,
            }
        ]

    async def search_vector(self, embedding, limit=10):
        self.vec_calls.append(embedding)
        return [
            {
                "concept_id": "p2",
                "node_id": "n2",
                "title": "V",
                "category": "docs",
                "summary": "S2",
                "source_id": "src2",
                "token_count": 10,
                "score": 0.9,
            }
        ]


async def fake_embedder(text):
    return [0.1, 0.2]


def test_supports_fts_is_always_true():
    assert ParrotWikiOrigin(store=FakeWikiStore()).supports_fts is True


async def test_search_without_embedder_uses_fts():
    store = FakeWikiStore()
    hits = await ParrotWikiOrigin(store=store).search("q", k=5)
    assert store.fts_calls and not store.vec_calls
    assert hits[0].origin_kind == SearchOriginKind.WIKI
    assert hits[0].id == "p1"
    assert hits[0].native_rank == 1


async def test_search_with_embedder_uses_vector():
    store = FakeWikiStore()
    hits = await ParrotWikiOrigin(store=store, embedder=fake_embedder).search(
        "q", k=5
    )
    assert store.vec_calls and not store.fts_calls
    assert hits[0].id == "p2"


async def test_fts_search_passes_category():
    store = FakeWikiStore()
    await ParrotWikiOrigin(store=store, category="docs").fts_search("q", k=5)
    assert store.fts_calls == [("q", "docs")]


async def test_fts_search_always_uses_fts_even_with_embedder():
    """fts_search always calls search_fts, regardless of embedder config."""
    store = FakeWikiStore()
    origin = ParrotWikiOrigin(store=store, embedder=fake_embedder)
    hits = await origin.fts_search("q", k=5)
    assert store.fts_calls and not store.vec_calls
    assert hits[0].origin_kind == SearchOriginKind.WIKI


def test_constructing_without_embedder_works():
    """FTS-only origin — no embedder required."""
    origin = ParrotWikiOrigin(store=FakeWikiStore())
    assert origin.supports_fts is True
    assert "no embedder configured" in origin.description


async def test_normalize_builds_content_from_title_and_summary():
    store = FakeWikiStore()
    hits = await ParrotWikiOrigin(store=store).search("q", k=5)
    assert "T" in hits[0].content
    assert "S" in hits[0].content


async def test_integration_real_sqlite_wiki_store(tmp_path):
    """End-to-end against a real SQLiteWikiStore (not a fake)."""
    store = SQLiteWikiStore(tmp_path / "wiki.db", wiki_name="test-wiki")
    await store.upsert_pages(
        [
            WikiPageRecord(
                concept_id="c1",
                title="Neural Networks",
                category="concept",
                summary="An introduction to neural networks.",
                body="Full body text about neural networks.",
            ),
            WikiPageRecord(
                concept_id="c2",
                title="Unrelated Topic",
                category="concept",
                summary="Something else entirely.",
                body="Body about something else.",
            ),
        ]
    )

    origin = ParrotWikiOrigin(store=store)
    hits = await origin.search("neural networks", k=5)

    assert len(hits) >= 1
    assert hits[0].origin_kind == SearchOriginKind.WIKI
    assert hits[0].id == "c1"
    assert hits[0].native_rank == 1
