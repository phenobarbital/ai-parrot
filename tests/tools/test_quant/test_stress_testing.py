"""Unit tests for Stress Testing Framework."""

import pytest
from parrot.tools.quant.models import StressScenario
from parrot.tools.quant.stress_testing import (
    stress_test_portfolio,
    get_predefined_scenario,
    list_predefined_scenarios,
    get_scenario_descriptions,
    create_volatility_shock_scenario,
    create_custom_scenario,
    create_sector_rotation_scenario,
    summarize_stress_results,
    get_concentrated_risk_positions,
    PREDEFINED_SCENARIOS,
)


@pytest.fixture
def sample_portfolio():
    """Sample portfolio for testing."""
    return {
        "SPY": 50000.0,
        "BTC": 30000.0,
        "TLT": 20000.0,
    }


@pytest.fixture
def covid_scenario():
    """COVID crash scenario for testing."""
    return StressScenario(
        name="covid_test",
        description="Test COVID scenario",
        asset_shocks={"SPY": -0.34, "BTC": -0.50, "TLT": 0.20},
    )


@pytest.fixture
def mild_scenario():
    """Mild stress scenario."""
    return StressScenario(
        name="mild",
        description="Mild stress",
        asset_shocks={"SPY": -0.05, "BTC": -0.10, "TLT": 0.02},
    )


@pytest.fixture
def severe_scenario():
    """Severe stress scenario."""
    return StressScenario(
        name="severe",
        description="Severe stress",
        asset_shocks={"SPY": -0.30, "BTC": -0.60, "TLT": 0.10},
    )


# =============================================================================
# STRESS TEST PORTFOLIO TESTS
# =============================================================================


class TestStressTestPortfolio:
    """Tests for stress_test_portfolio function."""

    def test_basic_stress_test(self, sample_portfolio, covid_scenario):
        """Basic stress test calculation."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            weights=[0.5, 0.3, 0.2],
            symbols=["SPY", "BTC", "TLT"],
            scenarios=[covid_scenario],
        )
        assert "scenario_results" in result
        assert "covid_test" in result["scenario_results"]
        scenario = result["scenario_results"]["covid_test"]
        assert scenario["portfolio_loss_pct"] < 0  # Should be a loss
        # SPY: $50k * -34% = -$17k (worst USD loss)
        # BTC: $30k * -50% = -$15k
        assert scenario["worst_position"] == "SPY"  # Largest USD loss
        assert scenario["best_position"] == "TLT"  # +20% gain

    def test_position_impacts(self, sample_portfolio, covid_scenario):
        """Position-level impacts are calculated correctly."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            weights=[0.5, 0.3, 0.2],
            symbols=["SPY", "BTC", "TLT"],
            scenarios=[covid_scenario],
        )
        impacts = result["scenario_results"]["covid_test"]["position_impacts"]
        # SPY: 50000 * -0.34 = -17000
        assert impacts["SPY"]["loss_usd"] == -17000.0
        # BTC: 30000 * -0.50 = -15000
        assert impacts["BTC"]["loss_usd"] == -15000.0
        # TLT: 20000 * 0.20 = 4000
        assert impacts["TLT"]["loss_usd"] == 4000.0

    def test_portfolio_loss_calculation(self, sample_portfolio, covid_scenario):
        """Total portfolio loss is correct."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            weights=[0.5, 0.3, 0.2],
            symbols=["SPY", "BTC", "TLT"],
            scenarios=[covid_scenario],
        )
        scenario = result["scenario_results"]["covid_test"]
        # Total: -17000 + -15000 + 4000 = -28000
        assert scenario["portfolio_loss_usd"] == -28000.0
        # Percentage: -28000 / 100000 = -0.28
        assert scenario["portfolio_loss_pct"] == -0.28

    def test_missing_symbol_gets_zero_shock(self):
        """Symbols not in scenario get 0% shock."""
        portfolio = {"SPY": 50000.0, "AAPL": 50000.0}  # AAPL not in scenario
        scenario = StressScenario(
            name="test",
            asset_shocks={"SPY": -0.20},
        )
        result = stress_test_portfolio(
            portfolio_values=portfolio,
            weights=[0.5, 0.5],
            symbols=["SPY", "AAPL"],
            scenarios=[scenario],
        )
        impacts = result["scenario_results"]["test"]["position_impacts"]
        assert impacts["AAPL"]["shock"] == 0
        assert impacts["AAPL"]["loss_usd"] == 0

    def test_zero_portfolio_value_raises(self):
        """Zero portfolio value raises error."""
        with pytest.raises(ValueError, match="Portfolio value must be positive"):
            stress_test_portfolio(
                portfolio_values={},
                scenarios=[],
            )

    def test_negative_portfolio_value_raises(self):
        """Negative portfolio value raises error."""
        with pytest.raises(ValueError, match="Portfolio value must be positive"):
            stress_test_portfolio(
                portfolio_values={"SPY": -10000.0},
                total_portfolio_value=-10000.0,
                scenarios=[],
            )

    def test_explicit_total_value(self, sample_portfolio, covid_scenario):
        """Explicit total portfolio value is used."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=[covid_scenario],
            total_portfolio_value=200000.0,  # Override calculated value
        )
        scenario = result["scenario_results"]["covid_test"]
        # Loss % should be calculated against 200000, not 100000
        # -28000 / 200000 = -0.14
        assert scenario["portfolio_loss_pct"] == -0.14

    def test_default_uses_all_predefined_scenarios(self, sample_portfolio):
        """When no scenarios provided, uses all predefined."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=None,
        )
        # Should have results for all predefined scenarios
        assert len(result["scenario_results"]) == len(PREDEFINED_SCENARIOS)
        for name in PREDEFINED_SCENARIOS:
            assert name in result["scenario_results"]


# =============================================================================
# PREDEFINED SCENARIOS TESTS
# =============================================================================


class TestPredefinedScenarios:
    """Tests for predefined scenario management."""

    def test_list_scenarios(self):
        """All predefined scenarios are listed."""
        scenarios = list_predefined_scenarios()
        assert "covid_crash_2020" in scenarios
        assert "rate_hike_shock" in scenarios
        assert "crypto_winter" in scenarios
        assert "black_swan" in scenarios
        assert "stagflation" in scenarios

    def test_get_scenario(self):
        """Get predefined scenario by name."""
        scenario = get_predefined_scenario("covid_crash_2020")
        assert scenario.name == "covid_crash_2020"
        assert "SPY" in scenario.asset_shocks
        assert scenario.asset_shocks["SPY"] < 0  # Negative shock
        assert scenario.description is not None

    def test_unknown_scenario_raises(self):
        """Unknown scenario raises error."""
        with pytest.raises(ValueError, match="Unknown scenario"):
            get_predefined_scenario("made_up_scenario")

    def test_unknown_scenario_shows_available(self):
        """Unknown scenario error includes available list."""
        with pytest.raises(ValueError) as exc_info:
            get_predefined_scenario("made_up_scenario")
        assert "covid_crash_2020" in str(exc_info.value)

    def test_get_scenario_descriptions(self):
        """Get descriptions for all scenarios."""
        descriptions = get_scenario_descriptions()
        assert "covid_crash_2020" in descriptions
        assert "March 2020" in descriptions["covid_crash_2020"]

    def test_covid_scenario_structure(self):
        """COVID scenario has expected assets."""
        scenario = get_predefined_scenario("covid_crash_2020")
        assert scenario.asset_shocks["SPY"] == -0.34
        assert scenario.asset_shocks["TLT"] == 0.20  # Bonds rallied
        assert scenario.asset_shocks["BTC"] == -0.50

    def test_rate_hike_scenario_structure(self):
        """Rate hike scenario has expected assets."""
        scenario = get_predefined_scenario("rate_hike_shock")
        assert scenario.asset_shocks["QQQ"] < scenario.asset_shocks["SPY"]  # Growth hit harder
        assert scenario.asset_shocks["TLT"] < 0  # Bonds fall on rate hikes

    def test_crypto_winter_scenario_structure(self):
        """Crypto winter scenario has expected assets."""
        scenario = get_predefined_scenario("crypto_winter")
        assert scenario.asset_shocks["BTC"] == -0.70
        assert scenario.asset_shocks["ETH"] == -0.80
        assert abs(scenario.asset_shocks["SPY"]) < 0.10  # Minor spillover


# =============================================================================
# VOLATILITY SHOCK SCENARIO TESTS
# =============================================================================


class TestVolatilityShockScenario:
    """Tests for create_volatility_shock_scenario function."""

    def test_vol_shock_generation(self):
        """Volatility shock scenario is generated correctly."""
        current_vols = {"SPY": 0.20, "BTC": 0.60}
        scenario = create_volatility_shock_scenario(
            current_volatilities=current_vols,
            multiplier=2.0,
        )
        assert "vol_spike_2.0x" in scenario.name
        # Higher vol assets should have bigger shocks
        assert abs(scenario.asset_shocks["BTC"]) > abs(scenario.asset_shocks["SPY"])

    def test_shock_capped_at_95(self):
        """Shocks are capped at -95%."""
        extreme_vol = {"MEME": 5.0}  # 500% annualized vol
        scenario = create_volatility_shock_scenario(
            current_volatilities=extreme_vol,
            multiplier=3.0,
        )
        assert scenario.asset_shocks["MEME"] >= -0.95

    def test_custom_multiplier(self):
        """Custom multiplier is applied."""
        current_vols = {"SPY": 0.20}
        scenario_2x = create_volatility_shock_scenario(current_vols, multiplier=2.0)
        scenario_3x = create_volatility_shock_scenario(current_vols, multiplier=3.0)
        # 3x should produce larger shock
        assert abs(scenario_3x.asset_shocks["SPY"]) > abs(scenario_2x.asset_shocks["SPY"])

    def test_custom_vol_to_return_factor(self):
        """Custom vol_to_return_factor is applied."""
        current_vols = {"SPY": 0.20}
        scenario_default = create_volatility_shock_scenario(current_vols, vol_to_return_factor=-0.5)
        scenario_custom = create_volatility_shock_scenario(current_vols, vol_to_return_factor=-1.0)
        # -1.0 factor should produce larger shock
        assert abs(scenario_custom.asset_shocks["SPY"]) > abs(scenario_default.asset_shocks["SPY"])

    def test_scenario_has_description(self):
        """Generated scenario has description."""
        scenario = create_volatility_shock_scenario({"SPY": 0.20}, multiplier=2.0)
        assert scenario.description is not None
        assert "2.0x" in scenario.description


# =============================================================================
# CUSTOM SCENARIO TESTS
# =============================================================================


class TestCustomScenario:
    """Tests for create_custom_scenario function."""

    def test_create_custom_scenario(self):
        """Create a custom scenario."""
        scenario = create_custom_scenario(
            name="my_scenario",
            asset_shocks={"SPY": -0.15, "BTC": -0.30},
            description="My custom stress test",
        )
        assert scenario.name == "my_scenario"
        assert scenario.asset_shocks["SPY"] == -0.15
        assert scenario.description == "My custom stress test"

    def test_custom_scenario_default_description(self):
        """Custom scenario gets default description if not provided."""
        scenario = create_custom_scenario(
            name="unnamed",
            asset_shocks={"SPY": -0.10},
        )
        assert "unnamed" in scenario.description


class TestSectorRotationScenario:
    """Tests for create_sector_rotation_scenario function."""

    def test_sector_rotation_scenario(self):
        """Create a sector rotation scenario."""
        sector_shocks = {"tech": -0.15, "energy": 0.10, "utilities": 0.05}
        sector_mapping = {
            "AAPL": "tech",
            "MSFT": "tech",
            "XOM": "energy",
            "NEE": "utilities",
        }
        scenario = create_sector_rotation_scenario(sector_shocks, sector_mapping)
        assert scenario.asset_shocks["AAPL"] == -0.15
        assert scenario.asset_shocks["MSFT"] == -0.15
        assert scenario.asset_shocks["XOM"] == 0.10
        assert scenario.asset_shocks["NEE"] == 0.05

    def test_unmapped_sector_gets_zero(self):
        """Symbols with unmapped sectors get zero shock."""
        sector_shocks = {"tech": -0.15}
        sector_mapping = {"AAPL": "tech", "UNKNOWN": "other"}
        scenario = create_sector_rotation_scenario(sector_shocks, sector_mapping)
        assert scenario.asset_shocks["UNKNOWN"] == 0.0


# =============================================================================
# MULTIPLE SCENARIOS TESTS
# =============================================================================


class TestMultipleScenarios:
    """Tests for running multiple scenarios."""

    def test_worst_scenario_identified(self, sample_portfolio, mild_scenario, severe_scenario):
        """Worst scenario is correctly identified."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=[mild_scenario, severe_scenario],
        )
        assert result["worst_scenario"] == "severe"
        assert result["max_loss_pct"] < -0.20  # Significant loss

    def test_multiple_scenario_results(self, sample_portfolio, mild_scenario, severe_scenario):
        """Multiple scenarios all have results."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=[mild_scenario, severe_scenario],
        )
        assert "mild" in result["scenario_results"]
        assert "severe" in result["scenario_results"]

    def test_scenario_order_independence(self, sample_portfolio, mild_scenario, severe_scenario):
        """Scenario order doesn't affect worst identification."""
        result1 = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=[mild_scenario, severe_scenario],
        )
        result2 = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=[severe_scenario, mild_scenario],
        )
        assert result1["worst_scenario"] == result2["worst_scenario"]
        assert result1["max_loss_pct"] == result2["max_loss_pct"]


# =============================================================================
# ANALYSIS FUNCTIONS TESTS
# =============================================================================


class TestSummarizeStressResults:
    """Tests for summarize_stress_results function."""

    def test_summary_format(self, sample_portfolio, covid_scenario):
        """Summary has expected format."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=[covid_scenario],
        )
        summary = summarize_stress_results(result)
        assert "STRESS TEST SUMMARY" in summary
        assert "Worst Scenario" in summary
        assert "covid_test" in summary
        assert "Portfolio Loss" in summary

    def test_summary_shows_worst_position(self, sample_portfolio, covid_scenario):
        """Summary shows worst position."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=[covid_scenario],
        )
        summary = summarize_stress_results(result)
        assert "Worst Position" in summary
        # SPY has largest USD loss ($17k vs $15k for BTC)
        assert "SPY" in summary

    def test_summary_shows_best_position(self, sample_portfolio, covid_scenario):
        """Summary shows best position."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=[covid_scenario],
        )
        summary = summarize_stress_results(result)
        assert "Best Position" in summary
        assert "TLT" in summary


class TestConcentratedRiskPositions:
    """Tests for get_concentrated_risk_positions function."""

    def test_identifies_concentrated_positions(self, sample_portfolio, covid_scenario):
        """Identifies positions with concentrated risk."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=[covid_scenario],
        )
        concentrated = get_concentrated_risk_positions(result, threshold_pct=0.30)
        # SPY and BTC should both be significant contributors
        symbols = [c["symbol"] for c in concentrated]
        assert "SPY" in symbols or "BTC" in symbols

    def test_sorted_by_contribution(self, sample_portfolio, covid_scenario):
        """Results are sorted by loss contribution."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=[covid_scenario],
        )
        concentrated = get_concentrated_risk_positions(result, threshold_pct=0.10)
        if len(concentrated) > 1:
            for i in range(len(concentrated) - 1):
                assert concentrated[i]["loss_contribution"] >= concentrated[i + 1]["loss_contribution"]

    def test_excludes_gains(self, sample_portfolio, covid_scenario):
        """Gains (positive impacts) are excluded."""
        result = stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenarios=[covid_scenario],
        )
        concentrated = get_concentrated_risk_positions(result, threshold_pct=0.01)
        symbols = [c["symbol"] for c in concentrated]
        # TLT has positive impact, should not be in list
        assert "TLT" not in symbols

    def test_high_threshold_filters_out(self):
        """High threshold filters out most positions."""
        portfolio = {"SPY": 50000.0, "BTC": 50000.0}
        scenario = StressScenario(
            name="equal",
            asset_shocks={"SPY": -0.10, "BTC": -0.10},  # Equal shocks
        )
        result = stress_test_portfolio(
            portfolio_values=portfolio,
            scenarios=[scenario],
        )
        # Each contributes 50%, so threshold of 60% should filter both
        concentrated = get_concentrated_risk_positions(result, threshold_pct=0.60)
        assert len(concentrated) == 0


# =============================================================================
# EDGE CASES TESTS
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases."""

    def test_single_position_portfolio(self, covid_scenario):
        """Single position portfolio works."""
        result = stress_test_portfolio(
            portfolio_values={"SPY": 100000.0},
            scenarios=[covid_scenario],
        )
        scenario = result["scenario_results"]["covid_test"]
        assert scenario["portfolio_loss_pct"] == -0.34
        assert scenario["worst_position"] == "SPY"
        assert scenario["best_position"] == "SPY"

    def test_all_positive_shocks(self):
        """Scenario with all positive shocks (gains)."""
        portfolio = {"TLT": 50000.0, "GLD": 50000.0}
        scenario = StressScenario(
            name="flight_to_safety",
            asset_shocks={"TLT": 0.15, "GLD": 0.20},
        )
        result = stress_test_portfolio(
            portfolio_values=portfolio,
            scenarios=[scenario],
        )
        scenario_result = result["scenario_results"]["flight_to_safety"]
        assert scenario_result["portfolio_loss_pct"] > 0  # Actually a gain
        assert scenario_result["portfolio_loss_usd"] > 0

    def test_empty_scenario_list(self):
        """Empty scenario list returns empty results."""
        result = stress_test_portfolio(
            portfolio_values={"SPY": 100000.0},
            scenarios=[],
        )
        assert result["scenario_results"] == {}
        assert result["worst_scenario"] is None
        assert result["max_loss_pct"] == 0

    def test_scenario_with_no_matching_symbols(self):
        """Scenario with no matching portfolio symbols."""
        portfolio = {"AAPL": 100000.0}  # Not in scenario
        scenario = StressScenario(
            name="no_match",
            asset_shocks={"SPY": -0.20, "BTC": -0.30},
        )
        result = stress_test_portfolio(
            portfolio_values=portfolio,
            scenarios=[scenario],
        )
        scenario_result = result["scenario_results"]["no_match"]
        assert scenario_result["portfolio_loss_pct"] == 0
        assert scenario_result["portfolio_loss_usd"] == 0

    def test_very_small_portfolio(self):
        """Very small portfolio values work."""
        result = stress_test_portfolio(
            portfolio_values={"SPY": 0.01},
            scenarios=[StressScenario(name="test", asset_shocks={"SPY": -0.50})],
        )
        scenario = result["scenario_results"]["test"]
        assert scenario["portfolio_loss_pct"] == -0.50

    def test_large_portfolio(self):
        """Large portfolio values work."""
        result = stress_test_portfolio(
            portfolio_values={"SPY": 10_000_000_000.0},  # $10B
            scenarios=[StressScenario(name="test", asset_shocks={"SPY": -0.20})],
        )
        scenario = result["scenario_results"]["test"]
        assert scenario["portfolio_loss_pct"] == -0.20
        assert scenario["portfolio_loss_usd"] == -2_000_000_000.0


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestIntegration:
    """Integration tests with realistic scenarios."""

    def test_realistic_portfolio_all_scenarios(self):
        """Test realistic portfolio against all predefined scenarios."""
        portfolio = {
            "SPY": 200000.0,
            "QQQ": 100000.0,
            "BTC": 50000.0,
            "TLT": 100000.0,
            "GLD": 50000.0,
        }
        result = stress_test_portfolio(
            portfolio_values=portfolio,
            scenarios=None,  # Use all predefined
        )
        # Should have results for all scenarios
        assert len(result["scenario_results"]) == len(PREDEFINED_SCENARIOS)
        # Worst scenario should be identified
        assert result["worst_scenario"] is not None
        # Max loss should be negative (it's a loss)
        assert result["max_loss_pct"] < 0

    def test_crypto_heavy_portfolio_crypto_winter(self):
        """Crypto-heavy portfolio in crypto winter."""
        portfolio = {
            "BTC": 300000.0,
            "ETH": 200000.0,
            "SOL": 100000.0,
        }
        scenario = get_predefined_scenario("crypto_winter")
        result = stress_test_portfolio(
            portfolio_values=portfolio,
            scenarios=[scenario],
        )
        scenario_result = result["scenario_results"]["crypto_winter"]
        # Should be devastating loss
        assert scenario_result["portfolio_loss_pct"] < -0.70

    def test_bond_heavy_portfolio_rate_hike(self):
        """Bond-heavy portfolio in rate hike scenario."""
        portfolio = {
            "TLT": 400000.0,
            "AGG": 300000.0,
            "VNQ": 200000.0,
        }
        scenario = get_predefined_scenario("rate_hike_shock")
        result = stress_test_portfolio(
            portfolio_values=portfolio,
            scenarios=[scenario],
        )
        scenario_result = result["scenario_results"]["rate_hike_shock"]
        # Should have moderate loss
        assert scenario_result["portfolio_loss_pct"] < 0
        assert scenario_result["portfolio_loss_pct"] > -0.30  # Not catastrophic

    def test_hedged_portfolio_black_swan(self):
        """Hedged portfolio in black swan event."""
        portfolio = {
            "SPY": 300000.0,
            "TLT": 150000.0,  # Hedge
            "GLD": 150000.0,  # Hedge
        }
        scenario = get_predefined_scenario("black_swan")
        result = stress_test_portfolio(
            portfolio_values=portfolio,
            scenarios=[scenario],
        )
        scenario_result = result["scenario_results"]["black_swan"]
        # Hedges should reduce total loss
        # SPY alone: -0.25 * 300000 / 600000 = -12.5%
        # With hedges, should be better
        assert scenario_result["portfolio_loss_pct"] > -0.20
