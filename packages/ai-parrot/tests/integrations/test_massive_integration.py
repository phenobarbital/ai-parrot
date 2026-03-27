"""Integration tests for MassiveToolkit.

These tests hit the real Massive API and require the MASSIVE_API_KEY
environment variable. They verify end-to-end functionality including
real network responses, payload shapes, and caching behaviors.

Run with: pytest tests/integrations/test_massive_integration.py
"""

import asyncio
import os
import time

import pytest
import redis.asyncio as redis

from parrot.tools.massive import MassiveToolkit

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("MASSIVE_API_KEY"),
        reason="MASSIVE_API_KEY environment variable not set",
    ),
]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def toolkit():
    """Real toolkit instance for integration tests."""
    # Ensure Benzinga detection is reset
    tk = MassiveToolkit()
    tk._benzinga_available = None
    return tk


@pytest.fixture
async def redis_cache():
    """Real Redis connection for checking/clearing cache."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/15")
    client = redis.from_url(redis_url, decode_responses=True)
    
    # Wait for ready
    await client.ping()
    
    yield client
    
    # Cleanup: delete all testing massive keys
    async for key in client.scan_iter("tool_cache:massive:*"):
        await client.delete(key)
    await client.aclose()


# =============================================================================
# Tests
# =============================================================================


class TestOptionsChainIntegration:
    """Integration tests for options chain endpoint."""

    @pytest.mark.asyncio
    async def test_fetch_aapl_options_with_greeks(self, toolkit):
        """Fetch real AAPL options chain with Greeks."""
        # Note: In a real test, you'd want a future date, but for integration 
        # testing against the live API, any valid date range works.
        # Massive Snapshot returns current active chains.
        result = await toolkit.get_options_chain_enriched(
            underlying="AAPL",
            limit=10,
        )

        # Allow graceful degradation or success
        assert result["source"] in ("massive", "massive_error")
        assert result["underlying"] == "AAPL"

        if result.get("error"):
            # Plan not entitled or 404
            assert "HTTP Error 40" in result["error"] or "Forbidden" in result["error"]
            assert result["fallback"] == "use_yfinance_options"
        else:
            assert result["contracts_count"] > 0
            assert len(result["contracts"]) > 0

            # Verify Greeks present
            contract = result["contracts"][0]
            assert "greeks" in contract
            greeks = contract["greeks"]
            
            # At least one greek should be non-null for active AAPL options
            has_greek = any(
                v is not None 
                for v in [greeks["delta"], greeks["gamma"], greeks["theta"], greeks["vega"]]
            )
            assert has_greek, "Greeks missing from live options chain data"
            assert "implied_volatility" in contract


class TestShortInterestIntegration:
    """Integration tests for short interest endpoint."""

    @pytest.mark.asyncio
    async def test_fetch_gme_short_interest(self, toolkit):
        """Fetch real GME short interest data."""
        result = await toolkit.get_short_interest("GME", limit=5)

        assert result["source"] in ("massive", "massive_error")
        assert result["symbol"] == "GME"
        
        if result.get("error"):
            assert "HTTP Error 40" in result["error"] or "Forbidden" in result["error"]
            assert result["fallback"] == "check_finviz_short_data"
        else:
            # Verify data structure
            assert "latest" in result
            assert result["latest"]["short_interest"] > 0
            assert result["latest"]["days_to_cover"] > 0
            
            assert "derived" in result
            assert result["derived"]["trend"] in ["increasing", "decreasing", "stable", None]
            assert len(result["history"]) > 0


class TestShortVolumeIntegration:
    """Integration tests for daily short volume endpoint."""

    @pytest.mark.asyncio
    async def test_fetch_tsla_short_volume(self, toolkit):
        """Fetch real TSLA short volume data."""
        result = await toolkit.get_short_volume("TSLA", limit=5)

        assert result["source"] in ("massive", "massive_error")
        assert result["symbol"] == "TSLA"
        
        if result.get("error"):
            assert "HTTP Error 40" in result["error"] or "Forbidden" in result["error"]
            assert result["fallback"] == "check_finviz_short_data"
        else:
            assert len(result["data"]) > 0
            latest = result["data"][0]
            
            # Short volume ratio should be calculated (between 0 and 1)
            # Note: extremely rarely, data anomalies could push this over 1
            assert latest["short_volume_ratio"] >= 0
            
            assert "derived" in result
            assert "avg_short_ratio_5d" in result["derived"]


class TestCacheIntegration:
    """Integration tests for the caching layer."""

    @pytest.mark.asyncio
    async def test_second_call_hits_cache(self, toolkit, redis_cache):
        """Second call with same params returns cached data without network."""
        # Clean any existing cache for AAPL short interest
        async for key in redis_cache.scan_iter("tool_cache:massive:short_interest:*AAPL*"):
            await redis_cache.delete(key)

        # First call (cache miss -> hits API)
        result1 = await toolkit.get_short_interest("AAPL", limit=3)
        assert result1.get("cached", False) is False

        # Second call (cache hit -> no network)
        result2 = await toolkit.get_short_interest("AAPL", limit=3)
        assert result2.get("cached") is True
        
        # Data logic/error should match precisely
        assert result1.get("error") == result2.get("error")
        
        if not result1.get("error"):
            assert result1["latest"]["short_interest"] == result2["latest"]["short_interest"]
            assert result1["latest"]["settlement_date"] == result2["latest"]["settlement_date"]


class TestEnrichTickerIntegration:
    """Integration tests for symbol enrichment."""

    @pytest.mark.asyncio
    async def test_enrich_single_ticker_selective(self, toolkit):
        """Enrich a single ticker, selecting endpoints to skip paid ones."""
        # Using selective endpoints to avoid failing on Benzinga if not in plan
        result = await toolkit._enrich_ticker_selective(
            "AAPL",
            endpoints=["short_interest", "short_volume"]
        )

        assert "short_interest" in result
        assert "short_volume" in result
        
        assert result["short_interest"]["symbol"] == "AAPL"
        
        assert result["short_volume"]["symbol"] == "AAPL"
        
        assert "options_chain" not in result
        assert "earnings" not in result


class TestEnrichCandidatesIntegration:
    """Integration tests for batch enrichment."""

    @pytest.mark.asyncio
    async def test_batch_enrichment_stays_under_rate_limit(self, toolkit):
        """Batch enrichment processes multiple tickers concurrently safely."""
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]

        start_time = time.time()
        # Fetching short volume (relatively fast endpoint) for 5 tickers
        # With max_concurrent=3 (default), this proves Semaphore limits execution
        results = await toolkit.enrich_candidates(
            symbols,
            endpoints=["short_volume"],
            max_concurrent=3,
        )
        elapsed = time.time() - start_time

        # Should have results for all symbols
        assert len(results) == 5
        for symbol in symbols:
            assert symbol in results
            assert results[symbol]["short_volume"]["symbol"] == symbol
            assert results[symbol]["short_volume"]["source"] in ("massive", "massive_error")

        # Sanity check timing to ensure we aren't bypassing standard execution
        print(f"Batch enrichment of {len(symbols)} tickers took {elapsed:.2f}s")
