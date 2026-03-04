import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.finance.enrichment import EnrichmentService, CandidateTicker
from parrot.finance.schemas import ResearchBriefing, ResearchItem


@pytest.fixture
def mock_massive():
    toolkit = AsyncMock()
    toolkit.DEFAULT_MAX_CONCURRENT = 3
    toolkit.get_options_chain_enriched = AsyncMock(return_value={"contracts": [{"contract_type": "call", "open_interest": 100}, {"contract_type": "put", "open_interest": 50}]})
    toolkit.get_earnings_data = AsyncMock(return_value={"earnings": [{"eps_surprise_pct": 10}]})
    toolkit.get_analyst_ratings = AsyncMock(return_value={"consensus": {"strong_buy": 5}})
    toolkit.get_short_interest = AsyncMock(return_value={"derived": {"trend": "increasing", "days_to_cover_zscore": 2.0}})
    toolkit.get_short_volume = AsyncMock(return_value={"derived": {"trend_5d": "increasing"}})
    return toolkit

@pytest.fixture
def mock_redis():
    redis = MagicMock()
    redis.get.return_value = None
    redis.set.return_value = True
    return redis

@pytest.fixture
def service(mock_massive, mock_redis):
    return EnrichmentService(
        massive_toolkit=mock_massive,
        redis_client=mock_redis,
    )

@pytest.fixture
def mock_briefings():
    item1 = ResearchItem(assets_mentioned=["AAPL"])
    item1.relevance_score = 0.9
    
    item2 = ResearchItem(assets_mentioned=["TSLA"])
    item2.relevance_score = 0.85
    
    b1 = ResearchBriefing(research_items=[item1])
    b2 = ResearchBriefing(research_items=[item2])
    
    return {
        "equity": b1,
        "sentiment": b2
    }


class TestEnrichmentService:
    @pytest.mark.asyncio
    async def test_enrich_briefings_adds_items(self, service, mock_briefings):
        """Enrichment adds ResearchItem entries to briefings."""
        initial_equity_len = len(mock_briefings["equity"].research_items)
        result = await service.enrich_briefings(mock_briefings)
        assert len(result["equity"].research_items) > initial_equity_len

    @pytest.mark.asyncio
    async def test_merge_routes_options_to_equity(self, service, mock_briefings):
        """Options data routed to equity briefing."""
        enrichment = {"AAPL": {"options": {"contracts": []}}}
        result = await service._merge_into_briefings(mock_briefings, enrichment)
        sources = [i.source for i in result["equity"].research_items]
        assert "massive:options" in sources

    @pytest.mark.asyncio
    async def test_merge_routes_short_to_sentiment(self, service, mock_briefings):
        """Short interest data routed to sentiment briefing."""
        enrichment = {"AAPL": {"short_interest": {"si_ratio": 0.05}}}
        result = await service._merge_into_briefings(mock_briefings, enrichment)
        sources = [i.source for i in result["sentiment"].research_items]
        assert "massive:short_interest" in sources

    @pytest.mark.asyncio
    async def test_derived_error_skipped(self, service):
        """Derived analytics errors don't pollute briefings."""
        enrichment = {"AAPL": {"options": {"error": "timeout"}}}
        result = await service._compute_derived(enrichment)
        assert "derived_options" not in result["AAPL"]

    @pytest.mark.asyncio
    async def test_crypto_skipped(self, service, mock_massive):
        """Crypto candidates not sent to Massive."""
        candidates = [CandidateTicker(symbol="BTC", asset_class="crypto")]
        candidates[0].data_needs = set()
        
        await service._fetch_enrichment(candidates)
        mock_massive.get_options_chain_enriched.assert_not_called()
        mock_massive.get_short_interest.assert_not_called()

    @pytest.mark.asyncio
    async def test_compute_derived(self, service):
        """Derived analytics are successfully computed from raw data."""
        enrichment = {
            "TSLA": {
                "options": {
                    "contracts": [
                        {"contract_type": "put", "open_interest": 200},
                        {"contract_type": "call", "open_interest": 100},
                    ]
                },
                "short_interest": {"derived": {"trend": "increasing", "days_to_cover_zscore": 2.0}},
                "short_volume": {"derived": {"trend_5d": "increasing"}}
            }
        }
        
        result = await service._compute_derived(enrichment)
        assert "derived_options" in result["TSLA"]
        assert result["TSLA"]["derived_options"]["put_call_oi_ratio"] == 2.0
        
        assert "derived_short" in result["TSLA"]
        # Score = 20 (increasing si) + 30 (high dtc_z) + 20 (increasing sv) = 70
        assert result["TSLA"]["derived_short"]["squeeze_score"] == 70
        assert result["TSLA"]["derived_short"]["squeeze_risk"] == "high"
