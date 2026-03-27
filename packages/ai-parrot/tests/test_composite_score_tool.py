"""
Tests for CompositeScoreTool.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from parrot.tools.composite_score import CompositeScoreTool, CompositeScoreInput


@pytest.fixture
def score_tool():
    """Create CompositeScoreTool with mocked tech_tool."""
    with patch.object(CompositeScoreTool, '__init__', lambda self, **kwargs: None):
        tool = object.__new__(CompositeScoreTool)
        tool.logger = MagicMock()
        tool._tech_tool = MagicMock()
        return tool


@pytest.fixture
def bullish_analysis():
    """Mock analysis result for bullish setup."""
    return {
        "symbol": "AAPL",
        "timestamp": "2026-03-02T16:00:00",
        "price": 185.0,
        "indicators": {
            "SMA_50": 175.0,   # Price above SMA50 (+1 pt)
            "SMA_200": 165.0,  # Price above SMA200 (+1 pt)
            "RSI_14": 62.0,    # In 50-70 zone (+1 pt)
            "MACD": {
                "value": 2.0,    # MACD > signal (+1 pt)
                "signal": 1.5,
                "hist": 0.5,     # hist > 0 (+0.5 pt)
            },
            "Avg_Volume_20d": 35000000,
        },
        "volume": 55000000,  # > 1.5x avg (+1 pt)
        "signals": ["Bullish Trend (Price > SMA200)"],
    }


@pytest.fixture
def bearish_analysis():
    """Mock analysis result for bearish setup."""
    return {
        "symbol": "AAPL",
        "timestamp": "2026-03-02T16:00:00",
        "price": 155.0,
        "indicators": {
            "SMA_50": 170.0,   # Price below SMA50
            "SMA_200": 180.0,  # Price below SMA200
            "RSI_14": 35.0,    # Weak momentum
            "MACD": {
                "value": -1.0,
                "signal": 0.5,
                "hist": -1.5,
            },
            "Avg_Volume_20d": 35000000,
        },
        "volume": 30000000,
        "signals": ["Bearish Trend (Price < SMA200)"],
    }


@pytest.fixture
def neutral_analysis():
    """Mock analysis result for neutral setup."""
    return {
        "symbol": "AAPL",
        "timestamp": "2026-03-02T16:00:00",
        "price": 175.0,
        "indicators": {
            "SMA_50": 175.0,   # Price at SMA50
            "SMA_200": 175.0,  # Price at SMA200
            "RSI_14": 50.0,    # Neutral RSI
            "MACD": {
                "value": 0.1,
                "signal": 0.1,
                "hist": 0.0,
            },
            "Avg_Volume_20d": 35000000,
        },
        "volume": 35000000,
        "signals": [],
    }


class TestCompositeScoreTool:
    """Tests for CompositeScoreTool."""

    @pytest.mark.asyncio
    async def test_bullish_score(self, score_tool, bullish_analysis):
        """Bullish setup produces high bullish score."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bullish_analysis)

        result = await score_tool._execute(symbol="AAPL", score_type="bullish")

        assert result.symbol == "AAPL"
        assert result.score > 5.0  # Should be moderate-to-strong bullish
        assert "bullish" in result.label
        assert result.recommendation_hint in ("trending_entry", "pullback_buy")

    @pytest.mark.asyncio
    async def test_bearish_score(self, score_tool, bearish_analysis):
        """Bearish setup produces low bullish score."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bearish_analysis)

        result = await score_tool._execute(symbol="AAPL", score_type="bullish")

        assert result.score < 4.0  # Should be neutral-to-bearish
        assert "bearish" in result.label or result.label == "neutral"

    @pytest.mark.asyncio
    async def test_bearish_score_type(self, score_tool, bearish_analysis):
        """Bearish setup with bearish score_type produces high score."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bearish_analysis)

        result = await score_tool._execute(symbol="AAPL", score_type="bearish")

        # When scoring for bearish, a bearish setup should score higher
        assert result.score > 3.0

    @pytest.mark.asyncio
    async def test_components_breakdown(self, score_tool, bullish_analysis):
        """Score includes component breakdown."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bullish_analysis)

        result = await score_tool._execute(symbol="AAPL")

        # Check all 7 components are present
        assert "sma_position" in result.components
        assert "rsi_zone" in result.components
        assert "macd" in result.components
        assert "adx_trend" in result.components
        assert "momentum" in result.components
        assert "volume" in result.components
        assert "ema_alignment" in result.components

        # Each component has score and max
        for name, comp in result.components.items():
            assert "score" in comp, f"{name} missing 'score'"
            assert "max" in comp, f"{name} missing 'max'"
            assert comp["score"] >= 0, f"{name} has negative score"
            assert comp["score"] <= comp["max"], f"{name} score exceeds max"

    @pytest.mark.asyncio
    async def test_crypto_adjustments(self, score_tool, bullish_analysis):
        """Crypto asset type applies different weights."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bullish_analysis)

        result = await score_tool._execute(symbol="BTC", asset_type="crypto")

        # Crypto should have different max values
        assert result.components["momentum"]["max"] == 2.5
        assert result.components["sma_position"]["max"] == 1.5

    @pytest.mark.asyncio
    async def test_error_handling(self, score_tool):
        """Error in analysis returns neutral score."""
        score_tool.tech_tool._execute = AsyncMock(return_value={"error": "No data"})

        result = await score_tool._execute(symbol="INVALID")

        assert result.symbol == "INVALID"
        assert result.score == 0.0
        assert result.label == "neutral"
        assert result.recommendation_hint == "data_unavailable"

    @pytest.mark.asyncio
    async def test_max_score_is_10(self, score_tool, bullish_analysis):
        """Max score field is always 10."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bullish_analysis)

        result = await score_tool._execute(symbol="AAPL")

        assert result.max_score == 10.0

    @pytest.mark.asyncio
    async def test_score_bounds(self, score_tool, bullish_analysis):
        """Score is between 0 and 10."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bullish_analysis)

        result = await score_tool._execute(symbol="AAPL")

        assert 0.0 <= result.score <= 10.0


class TestScoreComponents:
    """Tests for individual score component calculations."""

    @pytest.mark.asyncio
    async def test_sma_position_both_above(self, score_tool, bullish_analysis):
        """Price above both SMAs scores 2.0."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bullish_analysis)

        result = await score_tool._execute(symbol="AAPL", score_type="bullish")

        assert result.components["sma_position"]["score"] == 2.0

    @pytest.mark.asyncio
    async def test_sma_position_both_below(self, score_tool, bearish_analysis):
        """Price below both SMAs scores 0 for bullish."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bearish_analysis)

        result = await score_tool._execute(symbol="AAPL", score_type="bullish")

        assert result.components["sma_position"]["score"] == 0.0

    @pytest.mark.asyncio
    async def test_rsi_zone_bullish(self, score_tool, bullish_analysis):
        """RSI in 50-70 zone scores 1.0 for bullish."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bullish_analysis)

        result = await score_tool._execute(symbol="AAPL", score_type="bullish")

        assert result.components["rsi_zone"]["score"] == 1.0

    @pytest.mark.asyncio
    async def test_macd_bullish(self, score_tool, bullish_analysis):
        """MACD > signal with positive histogram scores 1.5."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bullish_analysis)

        result = await score_tool._execute(symbol="AAPL", score_type="bullish")

        assert result.components["macd"]["score"] == 1.5

    @pytest.mark.asyncio
    async def test_volume_high(self, score_tool, bullish_analysis):
        """Volume > 1.5x avg scores 1.0."""
        score_tool.tech_tool._execute = AsyncMock(return_value=bullish_analysis)

        result = await score_tool._execute(symbol="AAPL", score_type="bullish")

        assert result.components["volume"]["score"] == 1.0


class TestScoreLabels:
    """Tests for label assignment thresholds."""

    def test_determine_label_strong_bullish(self, score_tool):
        """Score >= 7.5 is strong_bullish."""
        label = score_tool._determine_label(7.5, "bullish")
        assert label == "strong_bullish"

        label = score_tool._determine_label(9.0, "bullish")
        assert label == "strong_bullish"

    def test_determine_label_moderate_bullish(self, score_tool):
        """Score >= 5.5 but < 7.5 is moderate_bullish."""
        label = score_tool._determine_label(5.5, "bullish")
        assert label == "moderate_bullish"

        label = score_tool._determine_label(6.5, "bullish")
        assert label == "moderate_bullish"

    def test_determine_label_neutral(self, score_tool):
        """Score >= 3.5 but < 5.5 is neutral."""
        label = score_tool._determine_label(3.5, "bullish")
        assert label == "neutral"

        label = score_tool._determine_label(4.5, "bullish")
        assert label == "neutral"

    def test_determine_label_moderate_bearish(self, score_tool):
        """Score >= 2.0 but < 3.5 is moderate_bearish for bullish type."""
        label = score_tool._determine_label(2.0, "bullish")
        assert label == "moderate_bearish"

        label = score_tool._determine_label(3.0, "bullish")
        assert label == "moderate_bearish"

    def test_determine_label_strong_bearish(self, score_tool):
        """Score < 2.0 is strong_bearish for bullish type."""
        label = score_tool._determine_label(1.5, "bullish")
        assert label == "strong_bearish"

        label = score_tool._determine_label(0.0, "bullish")
        assert label == "strong_bearish"

    def test_determine_label_inverted_for_bearish(self, score_tool):
        """Bearish score type inverts the labels."""
        # High score for bearish type = strong_bearish
        label = score_tool._determine_label(8.0, "bearish")
        assert label == "strong_bearish"

        # Low score for bearish type = strong_bullish
        label = score_tool._determine_label(1.0, "bearish")
        assert label == "strong_bullish"


class TestRecommendationHints:
    """Tests for recommendation hint generation."""

    def test_recommendation_hints(self, score_tool):
        """Verify all recommendation hints."""
        assert score_tool._get_recommendation_hint("strong_bullish") == "trending_entry"
        assert score_tool._get_recommendation_hint("moderate_bullish") == "pullback_buy"
        assert score_tool._get_recommendation_hint("neutral") == "wait"
        assert score_tool._get_recommendation_hint("moderate_bearish") == "caution"
        assert score_tool._get_recommendation_hint("strong_bearish") == "avoid"

    def test_unknown_label_defaults_to_wait(self, score_tool):
        """Unknown label returns 'wait'."""
        assert score_tool._get_recommendation_hint("unknown") == "wait"


class TestInputSchema:
    """Tests for input schema validation."""

    def test_input_schema_valid(self):
        """Valid input passes validation."""
        inp = CompositeScoreInput(
            symbol="AAPL",
            asset_type="stock",
            score_type="bullish",
        )
        assert inp.symbol == "AAPL"
        assert inp.asset_type == "stock"
        assert inp.score_type == "bullish"

    def test_input_schema_defaults(self):
        """Defaults are applied correctly."""
        inp = CompositeScoreInput(symbol="AAPL")
        assert inp.asset_type == "stock"
        assert inp.score_type == "bullish"
        assert inp.source == "alpaca"
        assert inp.lookback_days == 365

    def test_input_schema_crypto(self):
        """Crypto asset type is valid."""
        inp = CompositeScoreInput(symbol="BTC", asset_type="crypto")
        assert inp.asset_type == "crypto"


class TestToolExport:
    """Tests for tool export and registration."""

    def test_import_from_tools(self):
        """CompositeScoreTool can be imported from parrot.tools."""
        from parrot.tools import CompositeScoreTool as CST
        assert CST is not None
        assert CST.name == "composite_score"
