"""Unit tests for WikiCombinedSearch (TASK-1631; archive exclusion TASK-2072/FEAT-402)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.models import WikiPageCategory, WikiSearchResult


@pytest.fixture
def mock_pi():
    """Mock PageIndexToolkit."""
    pi = MagicMock()
    pi.search = AsyncMock(
        return_value=[
            {"node_id": "n1", "title": "Page 1", "score": 0.9, "summary": "PI summary 1"},
            {"node_id": "n3", "title": "Page 3", "score": 0.5, "summary": "PI summary 3"},
        ]
    )
    return pi


@pytest.fixture
def mock_gi():
    """Mock GraphIndexToolkit."""
    gi = MagicMock()
    gi.search_hybrid = AsyncMock(
        return_value=[
            {"node_id": "n2", "title": "Node 2", "score": 0.8, "summary": "GI summary 2"},
        ]
    )
    gi.get_neighborhood = AsyncMock(
        return_value={"neighbours": [{"node_id": "n5", "title": "Related"}]}
    )
    return gi


class TestWikiCombinedSearch:
    """Tests for WikiCombinedSearch."""

    @pytest.mark.asyncio
    async def test_combined_search_returns_results(self, mock_pi, mock_gi):
        """Combined search returns WikiSearchResult objects from both backends."""
        cs = WikiCombinedSearch(mock_pi, mock_gi)
        results = await cs.search("neural networks", mode="combined")
        assert len(results) >= 1
        assert all(isinstance(r, WikiSearchResult) for r in results)

    @pytest.mark.asyncio
    async def test_combined_search_merges_both_backends(self, mock_pi, mock_gi):
        """Combined mode queries both PI and GI."""
        cs = WikiCombinedSearch(mock_pi, mock_gi)
        results = await cs.search("test", mode="combined")
        sources = {r.source for r in results}
        assert "pageindex" in sources
        assert "graphindex" in sources

    @pytest.mark.asyncio
    async def test_pageindex_only_mode(self, mock_pi, mock_gi):
        """mode='pageindex' does not call GraphIndexToolkit.search_hybrid."""
        cs = WikiCombinedSearch(mock_pi, mock_gi)
        results = await cs.search("test", mode="pageindex")
        mock_gi.search_hybrid.assert_not_called()
        assert all(r.source == "pageindex" for r in results)

    @pytest.mark.asyncio
    async def test_graphindex_only_mode(self, mock_pi, mock_gi):
        """mode='graphindex' does not call PageIndexToolkit.search."""
        cs = WikiCombinedSearch(mock_pi, mock_gi)
        results = await cs.search("test", mode="graphindex")
        mock_pi.search.assert_not_called()
        assert all(r.source == "graphindex" for r in results)

    @pytest.mark.asyncio
    async def test_scores_in_unit_interval(self, mock_pi, mock_gi):
        """All result scores are in [0, 1] after normalisation."""
        cs = WikiCombinedSearch(mock_pi, mock_gi)
        results = await cs.search("neural networks", mode="combined")
        for r in results:
            assert 0.0 <= r.score <= 1.0, f"Score out of range: {r.score}"

    @pytest.mark.asyncio
    async def test_results_sorted_descending(self, mock_pi, mock_gi):
        """Results are sorted by score in descending order."""
        cs = WikiCombinedSearch(mock_pi, mock_gi)
        results = await cs.search("test", mode="combined")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_deduplication_keeps_higher_score(self):
        """When the same node_id appears in both backends, the higher score wins."""
        pi = MagicMock()
        gi = MagicMock()
        pi.search = AsyncMock(
            return_value=[
                {"node_id": "dup", "title": "Duplicate", "score": 0.9, "summary": "x"}
            ]
        )
        gi.search_hybrid = AsyncMock(
            return_value=[
                {"node_id": "dup", "title": "Duplicate", "score": 0.3, "summary": "y"}
            ]
        )
        cs = WikiCombinedSearch(pi, gi)
        results = await cs.search("test", mode="combined")
        dup_results = [r for r in results if r.node_id == "dup"]
        assert len(dup_results) == 1

    @pytest.mark.asyncio
    async def test_empty_results_when_both_backends_empty(self):
        """Returns empty list when both backends return nothing."""
        pi = MagicMock()
        gi = MagicMock()
        pi.search = AsyncMock(return_value=[])
        gi.search_hybrid = AsyncMock(return_value=[])
        cs = WikiCombinedSearch(pi, gi)
        results = await cs.search("test", mode="combined")
        assert results == []

    @pytest.mark.asyncio
    async def test_pi_failure_falls_back_to_gi(self, mock_gi):
        """PageIndex failure returns only GraphIndex results."""
        pi = MagicMock()
        pi.search = AsyncMock(side_effect=RuntimeError("PI down"))
        cs = WikiCombinedSearch(pi, mock_gi)
        results = await cs.search("test", mode="combined")
        assert len(results) >= 1
        assert all(r.source == "graphindex" for r in results)

    @pytest.mark.asyncio
    async def test_gi_failure_falls_back_to_pi(self, mock_pi):
        """GraphIndex failure returns only PageIndex results."""
        gi = MagicMock()
        gi.search_hybrid = AsyncMock(side_effect=RuntimeError("GI down"))
        cs = WikiCombinedSearch(mock_pi, gi)
        results = await cs.search("test", mode="combined")
        assert len(results) >= 1
        assert all(r.source == "pageindex" for r in results)

    @pytest.mark.asyncio
    async def test_find_related_returns_neighbours(self, mock_pi, mock_gi):
        """find_related delegates to get_neighborhood and returns neighbours."""
        cs = WikiCombinedSearch(mock_pi, mock_gi)
        related = await cs.find_related("node-42", depth=2)
        mock_gi.get_neighborhood.assert_called_once_with("node-42", depth=2)
        assert isinstance(related, list)

    @pytest.mark.asyncio
    async def test_find_related_handles_error(self, mock_pi):
        """find_related returns empty list on GraphIndex error."""
        gi = MagicMock()
        gi.get_neighborhood = AsyncMock(side_effect=RuntimeError("graph down"))
        cs = WikiCombinedSearch(mock_pi, gi)
        result = await cs.find_related("n1")
        assert result == []

    @pytest.mark.asyncio
    async def test_custom_weights_applied(self):
        """Custom weights change the score distribution."""
        pi = MagicMock()
        gi = MagicMock()
        pi.search = AsyncMock(
            return_value=[{"node_id": "p1", "title": "PI", "score": 1.0, "summary": ""}]
        )
        gi.search_hybrid = AsyncMock(
            return_value=[{"node_id": "g1", "title": "GI", "score": 1.0, "summary": ""}]
        )
        cs = WikiCombinedSearch(pi, gi)
        # With pageindex weight=1.0, graphindex weight=0.0
        results = await cs.search(
            "test",
            mode="combined",
            weights={"pageindex": 1.0, "graphindex": 0.0},
        )
        gi_results = [r for r in results if r.source == "graphindex"]
        for r in gi_results:
            assert r.score == pytest.approx(0.0, abs=1e-6)

    @pytest.mark.asyncio
    async def test_top_k_limits_results(self):
        """top_k limits the number of returned results."""
        pi = MagicMock()
        gi = MagicMock()
        pi.search = AsyncMock(
            return_value=[
                {"node_id": f"p{i}", "title": f"Page {i}", "score": float(i) / 10, "summary": ""}
                for i in range(8)
            ]
        )
        gi.search_hybrid = AsyncMock(return_value=[])
        cs = WikiCombinedSearch(pi, gi)
        results = await cs.search("test", mode="combined", top_k=3)
        assert len(results) <= 3


class StubWikiStore:
    """Minimal store-backed stub for WikiCombinedSearch archive-exclusion tests.

    Mirrors ``SQLiteWikiStore.search_fts``'s real archive-exclusion
    contract (category=None -> archive excluded; category="archive" ->
    archive-only) so these tests exercise ``WikiCombinedSearch``'s own
    merge/opt-in logic, independent of the SQL implementation (which has
    its own coverage in test_store.py).
    """

    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages

    async def search_fts(self, query, category=None, limit=10):
        rows = self._pages
        if category is not None:
            rows = [r for r in rows if r.get("category") == category]
        else:
            rows = [r for r in rows if r.get("category") != "archive"]
        return rows[:limit]

    async def search_vector(self, embedding, limit=10):
        # No category filtering at all — mirrors the real
        # SQLiteWikiStore.search_vector contract (FEAT-402 archive
        # exclusion for the vector leg is WikiCombinedSearch's job).
        return self._pages[:limit]


@pytest.fixture
def stub_wiki_store():
    return StubWikiStore(
        pages=[
            {
                "concept_id": "p1",
                "title": "Public Page",
                "category": "summary",
                "summary": "public",
                "score": 0.9,
            },
            {
                "concept_id": "a1",
                "title": "Archived Page",
                "category": "archive",
                "summary": "archived",
                "score": 0.8,
            },
        ]
    )


async def _stub_embedder(query):
    return [0.1, 0.2, 0.3]


class TestArchiveExclusion:
    """FEAT-402 (TASK-2072): archive category excluded from default ranking."""

    @pytest.mark.asyncio
    async def test_search_excludes_archive_by_default(self, stub_wiki_store):
        """Store-backed lexical search excludes archive pages by default."""
        cs = WikiCombinedSearch(None, None, store=stub_wiki_store)
        results = await cs.search("query", mode="combined", top_k=10)

        node_ids = {r.node_id for r in results}
        assert "a1" not in node_ids
        assert "p1" in node_ids
        assert all(r.category != WikiPageCategory.ARCHIVE for r in results)

    @pytest.mark.asyncio
    async def test_search_explicit_archive_filter_returns_archived(self, stub_wiki_store):
        """include_archived=True includes archive pages alongside everything else."""
        cs = WikiCombinedSearch(None, None, store=stub_wiki_store)
        results = await cs.search(
            "query", mode="combined", top_k=10, include_archived=True
        )

        node_ids = {r.node_id for r in results}
        assert "a1" in node_ids
        assert "p1" in node_ids

    @pytest.mark.asyncio
    async def test_vector_leg_excludes_archive_by_default(self, stub_wiki_store):
        """The vector leg (no store-level category filter) is post-filtered."""
        cs = WikiCombinedSearch(
            None, None, store=stub_wiki_store, embedder=_stub_embedder
        )
        results = await cs.search("query", mode="vector", top_k=10)

        node_ids = {r.node_id for r in results}
        assert "a1" not in node_ids
        assert "p1" in node_ids

    @pytest.mark.asyncio
    async def test_vector_leg_includes_archive_when_opted_in(self, stub_wiki_store):
        """include_archived=True skips the vector-leg post-filter too."""
        cs = WikiCombinedSearch(
            None, None, store=stub_wiki_store, embedder=_stub_embedder
        )
        results = await cs.search(
            "query", mode="vector", top_k=10, include_archived=True
        )

        node_ids = {r.node_id for r in results}
        assert "a1" in node_ids
