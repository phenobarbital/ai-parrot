import pytest
from parrot.finance.enrichment import (
    CandidateTicker,
    _extract_candidates,
    _infer_asset_class,
    _infer_data_needs,
)
from parrot.finance.schemas import ResearchBriefing, ResearchItem


@pytest.fixture
def mock_equity_item():
    item = ResearchItem(assets_mentioned=["AAPL"])
    item.relevance_score = 0.8
    return item


@pytest.fixture
def mock_sentiment_item():
    item = ResearchItem(assets_mentioned=["TSLA"])
    item.relevance_score = 0.7
    return item


@pytest.fixture
def mock_briefings(mock_equity_item, mock_sentiment_item):
    item1 = ResearchItem(assets_mentioned=["AAPL", "BTC", "SPY"])
    item1.relevance_score = 0.9
    
    item2 = ResearchItem(assets_mentioned=["AAPL"])
    item2.relevance_score = 0.85
    
    b1 = ResearchBriefing(research_items=[item1, mock_equity_item])
    b2 = ResearchBriefing(research_items=[item2, mock_sentiment_item])
    
    return {
        "equity": b1,
        "sentiment": b2
    }


@pytest.fixture
def mock_briefings_large():
    items = []
    for i in range(20):
        item = ResearchItem(assets_mentioned=[f"TICK{i}"])
        item.relevance_score = 0.5
        items.append(item)
    b = ResearchBriefing(research_items=items)
    return {"equity": b}


class TestCandidateTicker:
    def test_infer_asset_class_equity(self):
        """US equity symbols classified correctly."""
        assert _infer_asset_class("AAPL") == "equity"

    def test_infer_asset_class_crypto(self):
        """Crypto symbols classified correctly."""
        assert _infer_asset_class("BTC") == "crypto"

    def test_infer_asset_class_etf(self):
        """ETF symbols classified correctly."""
        assert _infer_asset_class("SPY") == "etf"

    def test_extract_candidates_ranking(self, mock_briefings):
        """Tickers mentioned by multiple crews rank higher."""
        candidates = _extract_candidates(mock_briefings)
        assert candidates[0].mention_count >= candidates[-1].mention_count
        assert candidates[0].symbol == "AAPL"  # Mentioned 3 times

    def test_extract_candidates_cap(self, mock_briefings_large):
        """Candidate list capped at max_candidates."""
        candidates = _extract_candidates(mock_briefings_large, max_candidates=15)
        assert len(candidates) <= 15

    def test_infer_data_needs_equity(self, mock_equity_item):
        """Equity research items get options + earnings + analyst_ratings."""
        needs = _infer_data_needs("equity", mock_equity_item)
        assert {"options", "earnings", "analyst_ratings"}.issubset(needs)

    def test_infer_data_needs_sentiment(self, mock_sentiment_item):
        """Sentiment items get short_interest + short_volume."""
        needs = _infer_data_needs("sentiment", mock_sentiment_item)
        assert {"short_interest", "short_volume"}.issubset(needs)

    def test_crypto_excluded_from_enrichment(self, mock_briefings):
        """Crypto tickers have empty data_needs set."""
        candidates = _extract_candidates(mock_briefings)
        crypto = [c for c in candidates if c.asset_class == "crypto"]
        assert len(crypto) > 0
        for c in crypto:
            assert len(c.data_needs) == 0
