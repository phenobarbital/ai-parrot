"""
Unit tests for MassiveToolkit Pydantic models.
"""

import pytest
from pydantic import ValidationError

from parrot.tools.massive.models import (
    OptionsChainInput,
    ShortInterestInput,
    ShortVolumeInput,
    EarningsDataInput,
    AnalystRatingsInput,
    GreeksData,
    OptionsContract,
    OptionsChainOutput,
    ShortInterestRecord,
    ShortInterestDerived,
    ShortInterestOutput,
    ShortVolumeRecord,
    ShortVolumeDerived,
    ShortVolumeOutput,
    EarningsRecord,
    EarningsDerived,
    EarningsOutput,
    AnalystAction,
    ConsensusRating,
    AnalystRatingsDerived,
    AnalystRatingsOutput,
)


# =============================================================================
# INPUT MODEL TESTS
# =============================================================================


class TestOptionsChainInput:
    """Tests for OptionsChainInput model."""

    def test_minimal_input(self):
        """Only underlying is required."""
        inp = OptionsChainInput(underlying="AAPL")
        assert inp.underlying == "AAPL"
        assert inp.limit == 250  # default
        assert inp.contract_type is None
        assert inp.expiration_date_gte is None
        assert inp.strike_price_gte is None

    def test_full_input(self):
        """All fields populated."""
        inp = OptionsChainInput(
            underlying="AAPL",
            expiration_date_gte="2026-03-01",
            expiration_date_lte="2026-04-30",
            strike_price_gte=180.0,
            strike_price_lte=200.0,
            contract_type="call",
            limit=100,
        )
        assert inp.contract_type == "call"
        assert inp.strike_price_gte == 180.0
        assert inp.limit == 100

    def test_underlying_required(self):
        """Underlying is required."""
        with pytest.raises(ValidationError):
            OptionsChainInput()

    def test_contract_type_validation(self):
        """Contract type must be 'call', 'put', or None."""
        # Valid values
        inp = OptionsChainInput(underlying="AAPL", contract_type="call")
        assert inp.contract_type == "call"

        inp = OptionsChainInput(underlying="AAPL", contract_type="put")
        assert inp.contract_type == "put"

        inp = OptionsChainInput(underlying="AAPL", contract_type=None)
        assert inp.contract_type is None

        # Invalid value
        with pytest.raises(ValidationError):
            OptionsChainInput(underlying="AAPL", contract_type="invalid")

    def test_limit_bounds(self):
        """Limit must be between 1 and 250."""
        # Valid
        inp = OptionsChainInput(underlying="AAPL", limit=1)
        assert inp.limit == 1

        inp = OptionsChainInput(underlying="AAPL", limit=250)
        assert inp.limit == 250

        # Invalid
        with pytest.raises(ValidationError):
            OptionsChainInput(underlying="AAPL", limit=0)

        with pytest.raises(ValidationError):
            OptionsChainInput(underlying="AAPL", limit=251)

    def test_strike_price_non_negative(self):
        """Strike prices must be non-negative."""
        inp = OptionsChainInput(underlying="AAPL", strike_price_gte=0)
        assert inp.strike_price_gte == 0

        with pytest.raises(ValidationError):
            OptionsChainInput(underlying="AAPL", strike_price_gte=-10)


class TestShortInterestInput:
    """Tests for ShortInterestInput model."""

    def test_defaults(self):
        """Defaults applied correctly."""
        inp = ShortInterestInput(symbol="GME")
        assert inp.limit == 10
        assert inp.order == "desc"

    def test_symbol_required(self):
        """Symbol is required."""
        with pytest.raises(ValidationError):
            ShortInterestInput()

    def test_order_validation(self):
        """Order must be 'asc' or 'desc'."""
        inp = ShortInterestInput(symbol="GME", order="asc")
        assert inp.order == "asc"

        inp = ShortInterestInput(symbol="GME", order="desc")
        assert inp.order == "desc"

        with pytest.raises(ValidationError):
            ShortInterestInput(symbol="GME", order="invalid")


class TestShortVolumeInput:
    """Tests for ShortVolumeInput model."""

    def test_defaults(self):
        """Defaults applied correctly."""
        inp = ShortVolumeInput(symbol="TSLA")
        assert inp.limit == 30
        assert inp.date_from is None
        assert inp.date_to is None

    def test_date_range(self):
        """Date range fields work."""
        inp = ShortVolumeInput(
            symbol="TSLA",
            date_from="2026-01-01",
            date_to="2026-03-01",
        )
        assert inp.date_from == "2026-01-01"
        assert inp.date_to == "2026-03-01"


class TestEarningsDataInput:
    """Tests for EarningsDataInput model."""

    def test_all_optional(self):
        """All fields are optional."""
        inp = EarningsDataInput()
        assert inp.symbol is None
        assert inp.date_from is None
        assert inp.limit == 50

    def test_importance_bounds(self):
        """Importance must be 0-5."""
        inp = EarningsDataInput(importance=0)
        assert inp.importance == 0

        inp = EarningsDataInput(importance=5)
        assert inp.importance == 5

        with pytest.raises(ValidationError):
            EarningsDataInput(importance=-1)

        with pytest.raises(ValidationError):
            EarningsDataInput(importance=6)


class TestAnalystRatingsInput:
    """Tests for AnalystRatingsInput model."""

    def test_action_filter(self):
        """Action filter accepted."""
        inp = AnalystRatingsInput(symbol="AAPL", action="upgrade")
        assert inp.action == "upgrade"
        assert inp.include_consensus is True  # default

    def test_action_validation(self):
        """Action must be valid value or None."""
        valid_actions = ["upgrade", "downgrade", "initiate", "reiterate", None]
        for action in valid_actions:
            inp = AnalystRatingsInput(symbol="AAPL", action=action)
            assert inp.action == action

        with pytest.raises(ValidationError):
            AnalystRatingsInput(symbol="AAPL", action="invalid")

    def test_include_consensus_default(self):
        """include_consensus defaults to True."""
        inp = AnalystRatingsInput(symbol="AAPL")
        assert inp.include_consensus is True

    def test_include_consensus_false(self):
        """include_consensus can be set to False."""
        inp = AnalystRatingsInput(symbol="AAPL", include_consensus=False)
        assert inp.include_consensus is False


# =============================================================================
# OUTPUT MODEL TESTS
# =============================================================================


class TestGreeksData:
    """Tests for GreeksData model."""

    def test_all_optional(self):
        """All fields are optional."""
        greeks = GreeksData()
        assert greeks.delta is None
        assert greeks.gamma is None

    def test_with_values(self):
        """Fields can be populated."""
        greeks = GreeksData(delta=0.5, gamma=0.03, theta=-0.15, vega=0.3)
        assert greeks.delta == 0.5
        assert greeks.gamma == 0.03


class TestOptionsContract:
    """Tests for OptionsContract model."""

    def test_minimal(self):
        """Minimal required fields."""
        contract = OptionsContract(
            ticker="O:AAPL250321C00185000",
            strike=185.0,
            expiration="2025-03-21",
            contract_type="call",
        )
        assert contract.ticker == "O:AAPL250321C00185000"
        assert contract.strike == 185.0
        assert contract.greeks.delta is None  # default empty

    def test_full(self):
        """Full contract data."""
        contract = OptionsContract(
            ticker="O:AAPL250321C00185000",
            strike=185.0,
            expiration="2025-03-21",
            contract_type="call",
            greeks=GreeksData(delta=0.5, gamma=0.03, theta=-0.15, vega=0.3),
            implied_volatility=0.285,
            open_interest=12450,
            volume=3200,
            bid=4.85,
            ask=5.10,
            midpoint=4.975,
        )
        assert contract.greeks.delta == 0.5
        assert contract.implied_volatility == 0.285


class TestOptionsChainOutput:
    """Tests for OptionsChainOutput model."""

    def test_default_values(self):
        """Default values applied."""
        output = OptionsChainOutput(underlying="AAPL")
        assert output.underlying == "AAPL"
        assert output.contracts_count == 0
        assert output.contracts == []
        assert output.source == "massive"
        assert output.cached is False
        assert output.error is None

    def test_with_contracts(self):
        """Output with contracts."""
        contract = OptionsContract(
            ticker="O:AAPL250321C00185000",
            strike=185.0,
            expiration="2025-03-21",
            contract_type="call",
        )
        output = OptionsChainOutput(
            underlying="AAPL",
            underlying_price=185.42,
            contracts_count=1,
            contracts=[contract],
        )
        assert output.contracts_count == 1
        assert len(output.contracts) == 1


class TestShortInterestOutput:
    """Tests for ShortInterestOutput model."""

    def test_default_values(self):
        """Default values applied."""
        output = ShortInterestOutput(symbol="GME")
        assert output.symbol == "GME"
        assert output.latest is None
        assert output.history == []
        assert output.source == "massive"

    def test_with_data(self):
        """Output with data."""
        record = ShortInterestRecord(
            settlement_date="2026-02-14",
            short_interest=15234567,
            days_to_cover=3.34,
        )
        derived = ShortInterestDerived(
            short_interest_change_pct=2.31,
            trend="increasing",
        )
        output = ShortInterestOutput(
            symbol="GME",
            latest=record,
            history=[record],
            derived=derived,
        )
        assert output.latest.short_interest == 15234567
        assert output.derived.trend == "increasing"


class TestShortVolumeOutput:
    """Tests for ShortVolumeOutput model."""

    def test_with_data(self):
        """Output with data."""
        record = ShortVolumeRecord(
            date="2026-03-01",
            short_volume=12345678,
            total_volume=45678901,
            short_volume_ratio=0.270,
        )
        output = ShortVolumeOutput(
            symbol="TSLA",
            data=[record],
        )
        assert output.data[0].short_volume_ratio == 0.270


class TestEarningsOutput:
    """Tests for EarningsOutput model."""

    def test_default_values(self):
        """Default values applied."""
        output = EarningsOutput()
        assert output.symbol is None
        assert output.earnings == []
        assert output.source == "massive_benzinga"


class TestAnalystRatingsOutput:
    """Tests for AnalystRatingsOutput model."""

    def test_with_actions(self):
        """Output with analyst actions."""
        action = AnalystAction(
            date="2026-02-28",
            firm="Goldman Sachs",
            action="upgrade",
            rating_current="Buy",
        )
        consensus = ConsensusRating(
            buy=35,
            hold=8,
            sell=2,
            mean_target=208.50,
        )
        output = AnalystRatingsOutput(
            symbol="AAPL",
            recent_actions=[action],
            consensus=consensus,
        )
        assert output.recent_actions[0].firm == "Goldman Sachs"
        assert output.consensus.buy == 35


class TestDerivedMetrics:
    """Tests for derived metric models."""

    def test_short_interest_trend_values(self):
        """Trend must be valid value."""
        derived = ShortInterestDerived(trend="increasing")
        assert derived.trend == "increasing"

        derived = ShortInterestDerived(trend="decreasing")
        assert derived.trend == "decreasing"

        derived = ShortInterestDerived(trend="stable")
        assert derived.trend == "stable"

    def test_analyst_sentiment_values(self):
        """Net sentiment must be valid value."""
        derived = AnalystRatingsDerived(net_sentiment="positive")
        assert derived.net_sentiment == "positive"

        derived = AnalystRatingsDerived(net_sentiment="neutral")
        assert derived.net_sentiment == "neutral"

        derived = AnalystRatingsDerived(net_sentiment="negative")
        assert derived.net_sentiment == "negative"
