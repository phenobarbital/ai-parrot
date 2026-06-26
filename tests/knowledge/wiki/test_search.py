"""Unit tests for WikiCombinedSearch (TASK-1631)."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.models import WikiSearchResult


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
