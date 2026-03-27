"""Unit tests for Piotroski F-Score Calculator."""

import pytest
from parrot.tools.quant.models import PiotroskiInput
from parrot.tools.quant.piotroski import (
    calculate_piotroski_score,
    batch_piotroski_scores,
    _interpret_score,
    get_fscore_summary,
    rank_by_fscore,
)


@pytest.fixture
def complete_financials():
    """Complete financials for all 9 criteria - healthy company."""
    return PiotroskiInput(
        quarterly_financials={
            "net_income": 15_000_000,
            "total_assets": 100_000_000,
            "operating_cash_flow": 18_000_000,
            "current_assets": 40_000_000,
            "current_liabilities": 20_000_000,
            "long_term_debt": 25_000_000,
            "shares_outstanding": 10_000_000,
            "revenue": 80_000_000,
            "gross_profit": 32_000_000,
        },
        prior_year_financials={
            "total_assets": 95_000_000,
            "current_ratio": 1.8,
            "long_term_debt": 28_000_000,
            "shares_outstanding": 10_000_000,
            "asset_turnover": 0.75,
            "gross_margin": 0.38,
        },
    )


@pytest.fixture
def poor_financials():
    """Poor financials for testing low scores."""
    return PiotroskiInput(
        quarterly_financials={
            "net_income": -5_000_000,  # Negative
            "total_assets": 100_000_000,
            "operating_cash_flow": -2_000_000,  # Negative
            "current_assets": 30_000_000,
            "current_liabilities": 40_000_000,  # Low current ratio
            "long_term_debt": 50_000_000,  # Increased
            "shares_outstanding": 12_000_000,  # Diluted
            "revenue": 60_000_000,  # Lower
            "gross_profit": 18_000_000,  # Lower margin
        },
        prior_year_financials={
            "total_assets": 95_000_000,
            "current_ratio": 2.0,
            "long_term_debt": 40_000_000,
            "shares_outstanding": 10_000_000,
            "asset_turnover": 0.80,
            "gross_margin": 0.35,
        },
    )


@pytest.fixture
def excellent_financials():
    """Excellent company hitting all 9 criteria."""
    return PiotroskiInput(
        quarterly_financials={
            "net_income": 20_000_000,
            "total_assets": 100_000_000,
            "operating_cash_flow": 25_000_000,  # > NI
            "current_assets": 50_000_000,
            "current_liabilities": 20_000_000,  # CR = 2.5 > 2.0
            "long_term_debt": 15_000_000,  # Decreased
            "shares_outstanding": 9_000_000,  # Decreased (buyback)
            "revenue": 100_000_000,
            "gross_profit": 45_000_000,  # 45% margin > 40%
        },
        prior_year_financials={
            "total_assets": 95_000_000,
            "current_ratio": 2.0,
            "long_term_debt": 20_000_000,
            "shares_outstanding": 10_000_000,
            "asset_turnover": 0.90,  # Current: 1.0 > 0.9
            "gross_margin": 0.40,
        },
    )


# =============================================================================
# BASIC SCORE TESTS
# =============================================================================


class TestPiotroskiScore:
    """Tests for calculate_piotroski_score function."""

    def test_complete_data_all_criteria(self, complete_financials):
        """All 9 criteria are evaluated with complete data."""
        result = calculate_piotroski_score(complete_financials)
        assert result["data_completeness_pct"] == 100.0
        assert len(result["criteria"]) == 9

    def test_score_range(self, complete_financials):
        """Score is between 0 and 9."""
        result = calculate_piotroski_score(complete_financials)
        assert 0 <= result["total_score"] <= 9

    def test_good_company_scores_high(self, complete_financials):
        """Company with good financials scores 6+."""
        result = calculate_piotroski_score(complete_financials)
        # Our fixture has: positive NI, ROA, OCF, OCF>NI, lower debt,
        # shares not diluted = at least 6 points
        assert result["total_score"] >= 6
        assert result["interpretation"] in ["Excellent", "Good"]

    def test_poor_company_scores_low(self, poor_financials):
        """Company with poor financials scores low."""
        result = calculate_piotroski_score(poor_financials)
        assert result["total_score"] <= 4
        assert result["interpretation"] in ["Fair", "Poor"]

    def test_excellent_company_scores_9(self, excellent_financials):
        """Excellent company hits all 9 criteria."""
        result = calculate_piotroski_score(excellent_financials)
        assert result["total_score"] == 9
        assert result["interpretation"] == "Excellent"

    def test_category_breakdown(self, complete_financials):
        """Category scores add up to total."""
        result = calculate_piotroski_score(complete_financials)
        cat = result["category_scores"]
        category_total = (
            cat["profitability"]
            + cat["leverage_liquidity"]
            + cat["operating_efficiency"]
        )
        assert category_total == result["total_score"]
        assert category_total <= 9

    def test_profitability_max_4(self, excellent_financials):
        """Profitability category has max 4 points."""
        result = calculate_piotroski_score(excellent_financials)
        assert result["category_scores"]["profitability"] <= 4

    def test_leverage_max_3(self, excellent_financials):
        """Leverage/liquidity category has max 3 points."""
        result = calculate_piotroski_score(excellent_financials)
        assert result["category_scores"]["leverage_liquidity"] <= 3

    def test_efficiency_max_2(self, excellent_financials):
        """Operating efficiency category has max 2 points."""
        result = calculate_piotroski_score(excellent_financials)
        assert result["category_scores"]["operating_efficiency"] <= 2


# =============================================================================
# INTERPRETATION TESTS
# =============================================================================


class TestInterpretation:
    """Tests for _interpret_score function."""

    def test_excellent(self):
        """Scores 8-9 are Excellent."""
        assert _interpret_score(9) == "Excellent"
        assert _interpret_score(8) == "Excellent"

    def test_good(self):
        """Scores 6-7 are Good."""
        assert _interpret_score(7) == "Good"
        assert _interpret_score(6) == "Good"

    def test_fair(self):
        """Scores 4-5 are Fair."""
        assert _interpret_score(5) == "Fair"
        assert _interpret_score(4) == "Fair"

    def test_poor(self):
        """Scores 0-3 are Poor."""
        assert _interpret_score(3) == "Poor"
        assert _interpret_score(2) == "Poor"
        assert _interpret_score(1) == "Poor"
        assert _interpret_score(0) == "Poor"


# =============================================================================
# PARTIAL DATA TESTS
# =============================================================================


class TestPartialData:
    """Tests for handling incomplete data."""

    def test_partial_data_still_scores(self):
        """Can score with incomplete data."""
        partial = PiotroskiInput(
            quarterly_financials={
                "net_income": 10_000_000,
                "total_assets": 50_000_000,
                "operating_cash_flow": 12_000_000,
            },
            prior_year_financials={},
        )
        result = calculate_piotroski_score(partial)
        # Should get scores for NI, ROA, OCF, OCF>NI = 4 criteria
        assert result["data_completeness_pct"] < 100
        assert result["data_completeness_pct"] == pytest.approx(44.4, rel=0.1)
        assert result["total_score"] >= 0

    def test_minimal_data(self):
        """Single criterion available."""
        minimal = PiotroskiInput(
            quarterly_financials={"net_income": 1_000_000},
            prior_year_financials={},
        )
        result = calculate_piotroski_score(minimal)
        assert result["data_completeness_pct"] == pytest.approx(11.1, rel=0.1)
        assert result["total_score"] == 1  # Positive NI

    def test_empty_data(self):
        """No data returns 0 score."""
        empty = PiotroskiInput(
            quarterly_financials={},
            prior_year_financials={},
        )
        result = calculate_piotroski_score(empty)
        assert result["total_score"] == 0
        assert result["data_completeness_pct"] == 0.0
        assert len(result["criteria"]) == 0

    def test_only_prior_year_data(self):
        """Prior year data alone doesn't create scores."""
        only_prior = PiotroskiInput(
            quarterly_financials={},
            prior_year_financials={
                "current_ratio": 2.0,
                "long_term_debt": 1_000_000,
            },
        )
        result = calculate_piotroski_score(only_prior)
        # Need current data to compare
        assert result["total_score"] == 0


# =============================================================================
# INDIVIDUAL CRITERIA TESTS
# =============================================================================


class TestIndividualCriteria:
    """Tests for each of the 9 criteria."""

    def test_positive_net_income_pass(self):
        """Positive net income scores 1."""
        data = PiotroskiInput(
            quarterly_financials={"net_income": 100},
            prior_year_financials={},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["positive_net_income"]["score"] == 1

    def test_positive_net_income_fail(self):
        """Negative net income scores 0."""
        data = PiotroskiInput(
            quarterly_financials={"net_income": -100},
            prior_year_financials={},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["positive_net_income"]["score"] == 0

    def test_positive_roa_pass(self):
        """Positive ROA scores 1."""
        data = PiotroskiInput(
            quarterly_financials={"net_income": 100, "total_assets": 1000},
            prior_year_financials={},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["positive_roa"]["score"] == 1
        assert result["criteria"]["positive_roa"]["value"] == 0.1

    def test_positive_roa_fail(self):
        """Negative ROA scores 0."""
        data = PiotroskiInput(
            quarterly_financials={"net_income": -100, "total_assets": 1000},
            prior_year_financials={},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["positive_roa"]["score"] == 0

    def test_ocf_greater_than_ni_pass(self):
        """OCF > NI scores 1 (quality of earnings)."""
        data = PiotroskiInput(
            quarterly_financials={
                "net_income": 100,
                "operating_cash_flow": 150,
            },
            prior_year_financials={},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["ocf_greater_than_ni"]["score"] == 1

    def test_ocf_greater_than_ni_fail(self):
        """OCF < NI scores 0."""
        data = PiotroskiInput(
            quarterly_financials={
                "net_income": 150,
                "operating_cash_flow": 100,
            },
            prior_year_financials={},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["ocf_greater_than_ni"]["score"] == 0

    def test_lower_debt_pass(self):
        """Lower debt YoY scores 1."""
        data = PiotroskiInput(
            quarterly_financials={"long_term_debt": 800},
            prior_year_financials={"long_term_debt": 1000},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["lower_debt"]["score"] == 1

    def test_lower_debt_fail(self):
        """Higher debt YoY scores 0."""
        data = PiotroskiInput(
            quarterly_financials={"long_term_debt": 1200},
            prior_year_financials={"long_term_debt": 1000},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["lower_debt"]["score"] == 0

    def test_no_dilution_pass(self):
        """No new shares scores 1."""
        data = PiotroskiInput(
            quarterly_financials={"shares_outstanding": 100},
            prior_year_financials={"shares_outstanding": 100},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["no_dilution"]["score"] == 1

    def test_no_dilution_buyback(self):
        """Share buyback scores 1."""
        data = PiotroskiInput(
            quarterly_financials={"shares_outstanding": 90},
            prior_year_financials={"shares_outstanding": 100},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["no_dilution"]["score"] == 1

    def test_dilution_fail(self):
        """Share issuance scores 0."""
        data = PiotroskiInput(
            quarterly_financials={"shares_outstanding": 120},
            prior_year_financials={"shares_outstanding": 100},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["no_dilution"]["score"] == 0


# =============================================================================
# BATCH SCORING TESTS
# =============================================================================


class TestBatchScoring:
    """Tests for batch_piotroski_scores function."""

    def test_batch_multiple_symbols(self, complete_financials, poor_financials):
        """Batch scoring works for multiple symbols."""
        results = batch_piotroski_scores({
            "AAPL": complete_financials,
            "BADCO": poor_financials,
        })
        assert "AAPL" in results
        assert "BADCO" in results
        assert results["AAPL"]["total_score"] > results["BADCO"]["total_score"]

    def test_batch_empty(self):
        """Empty batch returns empty dict."""
        results = batch_piotroski_scores({})
        assert results == {}

    def test_batch_single_symbol(self, complete_financials):
        """Single symbol batch works."""
        results = batch_piotroski_scores({"AAPL": complete_financials})
        assert len(results) == 1
        assert "AAPL" in results


# =============================================================================
# UTILITY FUNCTION TESTS
# =============================================================================


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_get_fscore_summary(self, complete_financials):
        """Summary generation works."""
        result = calculate_piotroski_score(complete_financials)
        summary = get_fscore_summary(result)
        assert "Piotroski F-Score:" in summary
        assert "Data Completeness:" in summary
        assert "Profitability:" in summary

    def test_rank_by_fscore(self, excellent_financials, complete_financials, poor_financials):
        """Ranking sorts by score descending."""
        ranked = rank_by_fscore({
            "BADCO": poor_financials,
            "GOODCO": complete_financials,
            "BESTCO": excellent_financials,
        })
        # Should be sorted by score descending
        # Both BESTCO and GOODCO might score 9, so check score values
        assert ranked[0][1] >= ranked[1][1] >= ranked[2][1]  # Descending order
        assert ranked[-1][0] == "BADCO"  # Poor company should be last
        assert ranked[-1][1] < ranked[0][1]  # Poor score < top scores
        # Check structure
        for symbol, score, interp in ranked:
            assert isinstance(symbol, str)
            assert isinstance(score, int)
            assert interp in ["Excellent", "Good", "Fair", "Poor"]


# =============================================================================
# EDGE CASES
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_zero_total_assets(self):
        """Zero total assets doesn't crash (division by zero)."""
        data = PiotroskiInput(
            quarterly_financials={
                "net_income": 100,
                "total_assets": 0,  # Edge case
            },
            prior_year_financials={},
        )
        result = calculate_piotroski_score(data)
        # Should skip ROA criterion
        assert "positive_roa" not in result["criteria"]
        assert "positive_net_income" in result["criteria"]

    def test_zero_revenue(self):
        """Zero revenue doesn't crash (division by zero)."""
        data = PiotroskiInput(
            quarterly_financials={
                "gross_profit": 100,
                "revenue": 0,  # Edge case
            },
            prior_year_financials={"gross_margin": 0.3},
        )
        result = calculate_piotroski_score(data)
        # Should skip gross margin criterion
        assert "higher_gross_margin" not in result["criteria"]

    def test_zero_current_liabilities(self):
        """Zero current liabilities doesn't crash."""
        data = PiotroskiInput(
            quarterly_financials={
                "current_assets": 1000,
                "current_liabilities": 0,  # Edge case
            },
            prior_year_financials={"current_ratio": 2.0},
        )
        result = calculate_piotroski_score(data)
        # Should skip current ratio criterion
        assert "higher_current_ratio" not in result["criteria"]

    def test_large_numbers(self):
        """Large numbers work correctly."""
        data = PiotroskiInput(
            quarterly_financials={
                "net_income": 50_000_000_000,  # $50B
                "total_assets": 500_000_000_000,  # $500B
                "operating_cash_flow": 75_000_000_000,
            },
            prior_year_financials={},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["positive_net_income"]["score"] == 1
        assert result["criteria"]["positive_roa"]["value"] == 0.1

    def test_break_even(self):
        """Net income of exactly 0 scores 0."""
        data = PiotroskiInput(
            quarterly_financials={"net_income": 0},
            prior_year_financials={},
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["positive_net_income"]["score"] == 0

    def test_same_values_yoy(self):
        """Same values YoY handled correctly."""
        data = PiotroskiInput(
            quarterly_financials={
                "long_term_debt": 1000,
                "shares_outstanding": 100,
            },
            prior_year_financials={
                "long_term_debt": 1000,  # Same = pass (<=)
                "shares_outstanding": 100,  # Same = pass (<=)
            },
        )
        result = calculate_piotroski_score(data)
        assert result["criteria"]["lower_debt"]["score"] == 1
        assert result["criteria"]["no_dilution"]["score"] == 1
