"""Tests for MassiveToolkit main implementation."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.tools.massive.toolkit import MassiveToolkit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _env_api_key(monkeypatch):
    """Ensure API key is always available."""
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key-12345")


@pytest.fixture
def mock_cache():
    """Mock MassiveCache."""
    with patch("parrot.tools.massive.toolkit.MassiveCache") as mock_cls:
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.set = AsyncMock()
        cache.close = AsyncMock()
        mock_cls.return_value = cache
        yield cache


@pytest.fixture
def mock_client():
    """Mock MassiveClient."""
    with patch("parrot.tools.massive.toolkit.MassiveClient") as mock_cls:
        client = MagicMock()
        # Default: empty responses
        client.list_snapshot_options_chain = AsyncMock(return_value=[])
        client.list_short_interest = AsyncMock(return_value=[])
        client.list_short_volume = AsyncMock(return_value=[])
        client.get_benzinga_earnings = AsyncMock(return_value=[])
        client.get_benzinga_analyst_ratings = AsyncMock(return_value=[])
        client.get_benzinga_consensus_ratings = AsyncMock(return_value={})
        mock_cls.return_value = client
        yield client


@pytest.fixture
def toolkit(mock_client, mock_cache):
    """Create a MassiveToolkit with mocked dependencies."""
    tk = MassiveToolkit(api_key="test-key")
    tk._benzinga_available = True  # Skip probe
    return tk


def _make_option_contract(**overrides):
    """Create a mock options contract dictionary."""
    contract = {
        "ticker": "O:AAPL250321C00185000",
        "strike_price": 185.0,
        "expiration_date": "2025-03-21",
        "contract_type": "call",
        "implied_volatility": 0.285,
        "open_interest": 12450,
        "volume": 3200,
        "break_even_price": 189.95,
        "greeks": {
            "delta": overrides.get("delta", 0.512),
            "gamma": overrides.get("gamma", 0.031),
            "theta": overrides.get("theta", -0.145),
            "vega": overrides.get("vega", 0.287),
        },
        "last_quote": {
            "bid": overrides.get("bid", 4.85),
            "ask": overrides.get("ask", 5.10),
        },
        "last_trade": {
            "price": overrides.get("last_price", 4.95),
        },
        "underlying_asset": {
            "price": overrides.get("underlying_price", 185.42),
        }
    }
    contract.update(overrides)
    return contract


def _make_short_interest_record(**overrides):
    """Create a mock short interest record."""
    record = {
        "settlement_date": "2026-02-14",
        "short_interest": 15000000,
        "short_volume": None,
        "avg_daily_volume": 4500000,
        "days_to_cover": 3.34,
        "date": None,
    }
    record.update(overrides)
    return record


def _make_short_volume_record(**overrides):
    """Create a mock short volume record."""
    record = {
        "date": "2026-02-28",
        "short_volume": 5000000,
        "short_exempt_volume": 200000,
        "total_volume": 15000000,
        "volume": None,
        "timestamp": None,
    }
    record.update(overrides)
    return record


def _make_earnings_record(**overrides):
    """Create a mock earnings record."""
    record = {
        "date": "2026-01-30",
        "date_reported": None,
        "time": "AMC",
        "timing": None,
        "period": "Q1 2026",
        "fiscal_period": None,
        "eps_estimate": 2.35,
        "eps_actual": 2.50,
        "revenue_estimate": 124500000000.0,
        "revenue_actual": 126100000000.0,
    }
    record.update(overrides)
    return record


def _make_analyst_action(**overrides):
    """Create a mock analyst action."""
    action = {
        "date": "2026-02-20",
        "action_date": None,
        "analyst": "John Smith",
        "analyst_name": None,
        "analyst_firm": "Goldman Sachs",
        "firm": None,
        "action_type": "upgrade",
        "rating_action": None,
        "rating_prior": "hold",
        "rating_current": "buy",
        "rating": None,
        "pt_prior": 170.0,
        "pt_current": 200.0,
        "price_target_prior": None,
        "price_target": None,
    }
    action.update(overrides)
    return action


# =============================================================================
# Tests
# =============================================================================


class TestInit:
    """Tests for MassiveToolkit initialization."""

    def test_init_requires_api_key(self, monkeypatch):
        """Raises without API key."""
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        with pytest.raises(ValueError, match="MASSIVE_API_KEY"):
            MassiveToolkit()

    def test_init_from_env(self, mock_client, mock_cache):
        """Reads API key from environment."""
        tk = MassiveToolkit()
        assert tk.api_key == "test-key-12345"

    def test_init_from_arg(self, mock_client, mock_cache):
        """API key from argument takes precedence."""
        tk = MassiveToolkit(api_key="custom-key")
        assert tk.api_key == "custom-key"


class TestOptionsChain:
    """Tests for get_options_chain_enriched."""

    @pytest.mark.asyncio
    async def test_returns_greeks(self, toolkit, mock_client):
        """Options chain includes Greeks data."""
        mock_client.list_snapshot_options_chain.return_value = [
            _make_option_contract(),
        ]
        result = await toolkit.get_options_chain_enriched("AAPL")

        assert result["source"] == "massive"
        assert result["underlying"] == "AAPL"
        assert len(result["contracts"]) == 1
        contract = result["contracts"][0]
        assert contract["greeks"]["delta"] == 0.512
        assert contract["greeks"]["gamma"] == 0.031
        assert contract["greeks"]["theta"] == -0.145
        assert contract["greeks"]["vega"] == 0.287

    @pytest.mark.asyncio
    async def test_returns_pricing(self, toolkit, mock_client):
        """Options chain includes pricing data."""
        mock_client.list_snapshot_options_chain.return_value = [
            _make_option_contract(),
        ]
        result = await toolkit.get_options_chain_enriched("AAPL")

        contract = result["contracts"][0]
        assert contract["bid"] == 4.85
        assert contract["ask"] == 5.10
        assert contract["midpoint"] == 4.975
        assert contract["implied_volatility"] == 0.285

    @pytest.mark.asyncio
    async def test_underlying_price(self, toolkit, mock_client):
        """Options chain includes underlying price."""
        mock_client.list_snapshot_options_chain.return_value = [
            _make_option_contract(underlying_price=185.42),
        ]
        result = await toolkit.get_options_chain_enriched("AAPL")
        assert result["underlying_price"] == 185.42

    @pytest.mark.asyncio
    async def test_graceful_degradation(self, toolkit, mock_client):
        """Returns fallback dict on error."""
        mock_client.list_snapshot_options_chain.side_effect = Exception("API Error")
        result = await toolkit.get_options_chain_enriched("AAPL")

        assert "error" in result
        assert result["fallback"] == "use_yfinance_options"
        assert "massive" in result["source"]

    @pytest.mark.asyncio
    async def test_cache_hit(self, toolkit, mock_cache, mock_client):
        """Returns cached result on hit."""
        mock_cache.get.return_value = {"underlying": "AAPL", "cached": False}
        result = await toolkit.get_options_chain_enriched("AAPL")

        assert result["cached"] is True
        mock_client.list_snapshot_options_chain.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_set(self, toolkit, mock_cache, mock_client):
        """Sets cache after successful fetch."""
        mock_client.list_snapshot_options_chain.return_value = []
        await toolkit.get_options_chain_enriched("AAPL")

        mock_cache.set.assert_called_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][0] == "options_chain"


class TestShortInterest:
    """Tests for get_short_interest."""

    @pytest.mark.asyncio
    async def test_derived_trend_increasing(self, toolkit, mock_client):
        """Short interest trend is increasing when change > 5%."""
        mock_client.list_short_interest.return_value = [
            _make_short_interest_record(short_interest=15000000),
            _make_short_interest_record(
                settlement_date="2026-01-31", short_interest=14000000,
            ),
        ]
        result = await toolkit.get_short_interest("GME")

        assert result["symbol"] == "GME"
        assert result["derived"]["trend"] == "increasing"
        assert result["derived"]["short_interest_change_pct"] > 0

    @pytest.mark.asyncio
    async def test_derived_trend_decreasing(self, toolkit, mock_client):
        """Short interest trend is decreasing when change < -5%."""
        mock_client.list_short_interest.return_value = [
            _make_short_interest_record(short_interest=10000000),
            _make_short_interest_record(
                settlement_date="2026-01-31", short_interest=14000000,
            ),
        ]
        result = await toolkit.get_short_interest("GME")

        assert result["derived"]["trend"] == "decreasing"
        assert result["derived"]["short_interest_change_pct"] < 0

    @pytest.mark.asyncio
    async def test_graceful_degradation(self, toolkit, mock_client):
        """Returns fallback on error."""
        mock_client.list_short_interest.side_effect = Exception("Timeout")
        result = await toolkit.get_short_interest("GME")

        assert "error" in result
        assert "fallback" in result


class TestShortVolume:
    """Tests for get_short_volume."""

    @pytest.mark.asyncio
    async def test_ratios_calculated(self, toolkit, mock_client):
        """Short volume ratio is calculated correctly."""
        mock_client.list_short_volume.return_value = [
            _make_short_volume_record(short_volume=5000000, total_volume=15000000),
        ]
        result = await toolkit.get_short_volume("TSLA")

        assert result["symbol"] == "TSLA"
        assert len(result["data"]) == 1
        assert result["data"][0]["short_volume_ratio"] == pytest.approx(0.3333, abs=0.001)

    @pytest.mark.asyncio
    async def test_derived_averages(self, toolkit, mock_client):
        """Derived averages calculated from multiple records."""
        records = [
            _make_short_volume_record(
                date=f"2026-02-{28 - i:02d}",
                short_volume=5000000 + i * 100000,
                total_volume=15000000,
            )
            for i in range(10)
        ]
        mock_client.list_short_volume.return_value = records
        result = await toolkit.get_short_volume("TSLA")

        assert result["derived"]["avg_short_ratio_5d"] is not None
        assert result["derived"]["avg_short_ratio_20d"] is not None


class TestEarnings:
    """Tests for get_earnings_data."""

    @pytest.mark.asyncio
    async def test_surprise_calculated(self, toolkit, mock_client):
        """EPS and revenue surprise calculated."""
        mock_client.get_benzinga_earnings.return_value = [
            _make_earnings_record(eps_estimate=2.35, eps_actual=2.50),
        ]
        result = await toolkit.get_earnings_data(symbol="AAPL")

        assert result["source"] == "massive_benzinga"
        assert len(result["earnings"]) == 1
        assert result["earnings"][0]["eps_surprise_pct"] > 0

    @pytest.mark.asyncio
    async def test_derived_beat_rate(self, toolkit, mock_client):
        """Derived beat rate from 4 quarters."""
        mock_client.get_benzinga_earnings.return_value = [
            _make_earnings_record(eps_estimate=2.0, eps_actual=2.2),
            _make_earnings_record(eps_estimate=2.0, eps_actual=2.1),
            _make_earnings_record(eps_estimate=2.0, eps_actual=1.9),
            _make_earnings_record(eps_estimate=2.0, eps_actual=2.3),
        ]
        result = await toolkit.get_earnings_data(symbol="AAPL")

        assert result["derived"]["beat_rate_4q"] == 0.75
        assert result["derived"]["trend"] == "consistent_beater"

    @pytest.mark.asyncio
    async def test_benzinga_unavailable(self, toolkit):
        """Returns fallback when Benzinga is not in plan."""
        toolkit._benzinga_available = False
        result = await toolkit.get_earnings_data(symbol="AAPL")

        assert "error" in result
        assert "Benzinga" in result["error"]
        assert result["fallback"] == "use_finnhub_earnings"


class TestAnalystRatings:
    """Tests for get_analyst_ratings."""

    @pytest.mark.asyncio
    async def test_actions_transformed(self, toolkit, mock_client):
        """Analyst actions are transformed correctly."""
        mock_client.get_benzinga_analyst_ratings.return_value = [
            _make_analyst_action(),
        ]
        mock_client.get_benzinga_consensus_ratings.return_value = {
            "buy": 15, "hold": 5, "sell": 2,
            "targetMean": 195.0, "targetHigh": 220.0, "targetLow": 160.0,
        }
        result = await toolkit.get_analyst_ratings("AAPL")

        assert result["source"] == "massive_benzinga"
        assert len(result["recent_actions"]) == 1
        action = result["recent_actions"][0]
        assert action["firm"] == "Goldman Sachs"
        assert action["action"] == "upgrade"

    @pytest.mark.asyncio
    async def test_consensus_included(self, toolkit, mock_client):
        """Consensus ratings included when requested."""
        mock_client.get_benzinga_analyst_ratings.return_value = []
        mock_client.get_benzinga_consensus_ratings.return_value = {
            "buy": 15, "hold": 5, "sell": 2,
            "targetMean": 195.0,
        }
        result = await toolkit.get_analyst_ratings("AAPL", include_consensus=True)

        assert result["consensus"] is not None
        assert result["consensus"]["buy"] == 15

    @pytest.mark.asyncio
    async def test_derived_sentiment(self, toolkit, mock_client):
        """Derived net sentiment from recent actions."""
        mock_client.get_benzinga_analyst_ratings.return_value = [
            _make_analyst_action(action_type="upgrade", date="2026-02-20"),
            _make_analyst_action(action_type="upgrade", date="2026-02-15"),
            _make_analyst_action(action_type="downgrade", date="2026-02-10"),
        ]
        result = await toolkit.get_analyst_ratings("AAPL")

        assert result["derived"]["upgrades_30d"] == 2
        assert result["derived"]["downgrades_30d"] == 1
        assert result["derived"]["net_sentiment"] == "positive"

    @pytest.mark.asyncio
    async def test_benzinga_unavailable(self, toolkit):
        """Returns fallback when Benzinga is not in plan."""
        toolkit._benzinga_available = False
        result = await toolkit.get_analyst_ratings("AAPL")

        assert "error" in result
        assert result["fallback"] == "use_finnhub_recommendations"


class TestEnrichTicker:
    """Tests for enrich_ticker convenience method."""

    @pytest.mark.asyncio
    async def test_returns_all_endpoints(self, toolkit, mock_client):
        """enrich_ticker returns results for all endpoints."""
        mock_client.list_snapshot_options_chain.return_value = []
        mock_client.list_short_interest.return_value = []
        mock_client.list_short_volume.return_value = []
        mock_client.get_benzinga_earnings.return_value = []
        mock_client.get_benzinga_analyst_ratings.return_value = []
        mock_client.get_benzinga_consensus_ratings.return_value = {}

        result = await toolkit.enrich_ticker("AAPL")

        assert result["symbol"] == "AAPL"
        assert "options_chain" in result
        assert "short_interest" in result
        assert "short_volume" in result
        assert "earnings" in result
        assert "analyst_ratings" in result


class TestEnrichCandidates:
    """Tests for enrich_candidates batch method."""

    @pytest.mark.asyncio
    async def test_batch_enrichment(self, toolkit, mock_client):
        """enrich_candidates processes multiple symbols."""
        mock_client.list_snapshot_options_chain.return_value = []
        mock_client.list_short_interest.return_value = []
        mock_client.list_short_volume.return_value = []
        mock_client.get_benzinga_earnings.return_value = []
        mock_client.get_benzinga_analyst_ratings.return_value = []
        mock_client.get_benzinga_consensus_ratings.return_value = {}

        results = await toolkit.enrich_candidates(["AAPL", "TSLA"])

        assert "AAPL" in results
        assert "TSLA" in results

    @pytest.mark.asyncio
    async def test_selective_endpoints(self, toolkit, mock_client):
        """enrich_candidates with specific endpoints only."""
        mock_client.list_short_interest.return_value = []

        results = await toolkit.enrich_candidates(
            ["AAPL"], endpoints=["short_interest"],
        )

        assert "AAPL" in results
        mock_client.list_snapshot_options_chain.assert_not_called()


class TestBenzingaDetection:
    """Tests for Benzinga lazy detection."""

    @pytest.mark.asyncio
    async def test_benzinga_available(self, toolkit, mock_client):
        """Benzinga available when probe succeeds."""
        toolkit._benzinga_available = None
        mock_client.get_benzinga_earnings.return_value = [_make_earnings_record()]

        available = await toolkit._check_benzinga()
        assert available is True
        assert toolkit._benzinga_available is True

    @pytest.mark.asyncio
    async def test_benzinga_unavailable_403(self, toolkit, mock_client):
        """Benzinga unavailable when probe returns 403."""
        from parrot.tools.massive.client import MassiveAPIError

        toolkit._benzinga_available = None
        mock_client.get_benzinga_earnings.side_effect = MassiveAPIError(
            "Forbidden", status_code=403,
        )

        available = await toolkit._check_benzinga()
        assert available is False
        assert toolkit._benzinga_available is False

    @pytest.mark.asyncio
    async def test_benzinga_cached_result(self, toolkit):
        """Probe result is cached after first check."""
        toolkit._benzinga_available = True
        available = await toolkit._check_benzinga()
        assert available is True
