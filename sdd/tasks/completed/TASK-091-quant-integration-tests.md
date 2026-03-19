# TASK-091: QuantToolkit Integration Tests

**Feature**: FEAT-017 QuantToolkit
**Spec**: `sdd/specs/quant-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-090
**Assigned-to**: a2e5d1ea-a67b-47dd-9439-216d1d078fb1

---

## Context

This task implements end-to-end integration tests for the QuantToolkit. These tests verify that the toolkit works correctly with the finance crew agents and produces output compatible with the deliberation schemas.

Reference: Spec Section 4 (Integration Tests) and Section 5 (Acceptance Criteria).

---

## Scope

- Write integration tests for agent workflows:
  - Risk analyst agent using toolkit for risk summary
  - Equity analyst agent using Piotroski scoring
  - Sentiment analyst using volatility analytics
- Verify output compatibility with finance schemas:
  - `AnalystReport.key_risks` compatibility
  - `AnalystReport.data_points` compatibility
  - `PortfolioSnapshot.max_drawdown_pct` compatibility
- Test data flow from YFinanceTool to QuantToolkit
- Test realistic portfolio scenarios

**NOT in scope**:
- Unit tests for individual modules (covered in TASK-077 through TASK-078)
- Live API integration tests

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/test_quant/test_integration.py` | CREATE | Integration tests |
| `tests/tools/test_quant/conftest.py` | CREATE | Shared fixtures |

---

## Implementation Notes

### Test Structure

```python
# tests/tools/test_quant/conftest.py
import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def realistic_equity_prices():
    """Realistic equity price data simulating 1 year."""
    np.random.seed(42)
    n = 252  # 1 year of trading days
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    # Simulate correlated returns
    cov_matrix = np.array([
        [0.04, 0.02, 0.015],  # AAPL
        [0.02, 0.03, 0.018],  # MSFT
        [0.015, 0.018, 0.02],  # SPY
    ])
    mean_returns = [0.0008, 0.0007, 0.0005]

    returns = np.random.multivariate_normal(mean_returns, cov_matrix / 252, n)

    prices = {}
    prices["AAPL"] = list(175 * np.cumprod(1 + returns[:, 0]))
    prices["MSFT"] = list(380 * np.cumprod(1 + returns[:, 1]))
    prices["SPY"] = list(450 * np.cumprod(1 + returns[:, 2]))

    return {
        "prices": prices,
        "dates": [str(d.date()) for d in dates],
        "returns": {
            "AAPL": list(returns[:, 0]),
            "MSFT": list(returns[:, 1]),
            "SPY": list(returns[:, 2]),
        },
    }


@pytest.fixture
def realistic_crypto_prices():
    """Realistic crypto price data."""
    np.random.seed(123)
    n = 365  # 1 year including weekends
    dates = pd.date_range("2024-01-01", periods=n, freq="D")

    # Crypto has higher vol and less correlation
    returns_btc = np.random.normal(0.001, 0.04, n)
    returns_eth = np.random.normal(0.0012, 0.05, n) + 0.3 * returns_btc  # Correlated

    prices = {
        "BTC": list(42000 * np.cumprod(1 + returns_btc)),
        "ETH": list(2500 * np.cumprod(1 + returns_eth)),
    }

    return {
        "prices": prices,
        "dates": [str(d.date()) for d in dates],
        "returns": {
            "BTC": list(returns_btc),
            "ETH": list(returns_eth),
        },
    }


@pytest.fixture
def sample_portfolio():
    """Sample portfolio for stress testing."""
    return {
        "SPY": 100000,
        "AAPL": 50000,
        "MSFT": 30000,
        "BTC": 15000,
        "ETH": 5000,
    }


@pytest.fixture
def sample_financials():
    """Sample financials for Piotroski scoring."""
    return {
        "AAPL": {
            "quarterly_financials": {
                "net_income": 23_000_000_000,
                "total_assets": 352_000_000_000,
                "operating_cash_flow": 28_000_000_000,
                "current_assets": 135_000_000_000,
                "current_liabilities": 145_000_000_000,
                "long_term_debt": 95_000_000_000,
                "shares_outstanding": 15_800_000_000,
                "revenue": 94_000_000_000,
                "gross_profit": 41_000_000_000,
            },
            "prior_year_financials": {
                "total_assets": 340_000_000_000,
                "current_ratio": 0.88,
                "long_term_debt": 100_000_000_000,
                "shares_outstanding": 16_000_000_000,
                "asset_turnover": 0.27,
                "gross_margin": 0.42,
            },
        },
        "MSFT": {
            "quarterly_financials": {
                "net_income": 18_000_000_000,
                "total_assets": 411_000_000_000,
                "operating_cash_flow": 24_000_000_000,
                "current_assets": 169_000_000_000,
                "current_liabilities": 105_000_000_000,
                "long_term_debt": 42_000_000_000,
                "shares_outstanding": 7_400_000_000,
                "revenue": 56_000_000_000,
                "gross_profit": 39_000_000_000,
            },
            "prior_year_financials": {
                "total_assets": 380_000_000_000,
                "current_ratio": 1.50,
                "long_term_debt": 45_000_000_000,
                "shares_outstanding": 7_500_000_000,
                "asset_turnover": 0.14,
                "gross_margin": 0.68,
            },
        },
    }
```

### Integration Tests

```python
# tests/tools/test_quant/test_integration.py
import pytest
import numpy as np
from parrot.tools.quant import QuantToolkit


@pytest.fixture
def toolkit():
    return QuantToolkit()


class TestRiskAnalystWorkflow:
    """Tests simulating risk analyst agent workflow."""

    @pytest.mark.asyncio
    async def test_full_risk_analysis(
        self, toolkit, realistic_equity_prices, sample_portfolio
    ):
        """
        Risk analyst workflow:
        1. Compute portfolio risk metrics
        2. Check correlation regime
        3. Run stress tests
        4. Produce risk summary compatible with AnalystReport
        """
        returns = realistic_equity_prices["returns"]

        # Step 1: Portfolio risk
        portfolio_returns = {
            k: v for k, v in returns.items() if k in sample_portfolio
        }
        total_value = sum(sample_portfolio.values())
        weights = [
            sample_portfolio[s] / total_value
            for s in portfolio_returns.keys()
        ]

        risk_metrics = await toolkit.compute_portfolio_risk(
            returns_data=portfolio_returns,
            weights=weights,
            symbols=list(portfolio_returns.keys()),
        )

        # Verify output structure for AnalystReport
        assert "portfolio_volatility" in risk_metrics
        assert isinstance(risk_metrics["portfolio_volatility"], float)

        # Step 2: Correlation regime
        regime = await toolkit.detect_correlation_regimes(
            price_data=realistic_equity_prices["prices"],
            short_window=20,
            long_window=60,
        )

        assert "regime_alerts" in regime
        assert isinstance(regime["regime_alerts"], list)

        # Step 3: Stress test
        stress = await toolkit.stress_test_portfolio(
            portfolio_values=sample_portfolio,
            scenario_names=["covid_crash_2020", "rate_hike_shock"],
        )

        assert "worst_scenario" in stress
        assert "max_loss_pct" in stress
        assert stress["max_loss_pct"] < 0  # Should be a loss

    @pytest.mark.asyncio
    async def test_risk_summary_for_analyst_report(
        self, toolkit, realistic_equity_prices
    ):
        """
        Verify output can populate AnalystReport.portfolio_risk_summary.

        Expected fields:
        - var_1d_95_usd
        - max_position_weight
        - top_correlation_pair
        - risk_budget_used
        """
        returns = realistic_equity_prices["returns"]
        prices = realistic_equity_prices["prices"]

        # Compute risk
        risk = await toolkit.compute_portfolio_risk(
            returns_data=returns,
            weights=[0.4, 0.35, 0.25],
            symbols=["AAPL", "MSFT", "SPY"],
        )

        # Compute correlation
        corr = await toolkit.compute_correlation_matrix(prices)

        # Build risk summary
        risk_summary = {
            "var_1d_95_pct": risk.get("var_1d_95_usd", risk.get("var_1d_95_pct")),
            "portfolio_volatility": risk["portfolio_volatility"],
            "max_drawdown": risk.get("max_drawdown"),
        }

        # Find top correlation pair
        matrix = corr["matrix"]
        max_corr = 0
        top_pair = None
        symbols = list(matrix.keys())
        for i, s1 in enumerate(symbols):
            for s2 in symbols[i+1:]:
                c = abs(matrix[s1][s2])
                if c > max_corr:
                    max_corr = c
                    top_pair = f"{s1}-{s2}"

        risk_summary["top_correlation_pair"] = top_pair
        risk_summary["top_correlation"] = max_corr

        # Verify all fields present
        assert all(k in risk_summary for k in [
            "var_1d_95_pct", "portfolio_volatility", "top_correlation_pair"
        ])


class TestEquityAnalystWorkflow:
    """Tests simulating equity analyst agent workflow."""

    @pytest.mark.asyncio
    async def test_piotroski_screening(self, toolkit, sample_financials):
        """
        Equity analyst workflow:
        1. Score multiple stocks with Piotroski
        2. Rank by score
        3. Produce recommendations
        """
        # Batch score
        results = await toolkit.batch_piotroski_scores(sample_financials)

        assert "AAPL" in results
        assert "MSFT" in results

        # Rank by score
        ranked = sorted(
            results.items(),
            key=lambda x: x[1]["total_score"],
            reverse=True,
        )

        # Verify scores are valid
        for symbol, data in ranked:
            assert 0 <= data["total_score"] <= 9
            assert data["interpretation"] in ["Excellent", "Good", "Fair", "Poor"]

    @pytest.mark.asyncio
    async def test_piotroski_for_data_points(self, toolkit, sample_financials):
        """
        Verify Piotroski output can populate AnalystReport.data_points.
        """
        result = await toolkit.calculate_piotroski_score(
            quarterly_financials=sample_financials["AAPL"]["quarterly_financials"],
            prior_year_financials=sample_financials["AAPL"]["prior_year_financials"],
        )

        # Build data point string
        data_point = (
            f"Piotroski F-Score: {result['total_score']}/9 "
            f"({result['interpretation']}), "
            f"Profitability: {result['category_scores']['profitability']}/4, "
            f"Leverage: {result['category_scores']['leverage_liquidity']}/3, "
            f"Efficiency: {result['category_scores']['operating_efficiency']}/2"
        )

        assert "Piotroski F-Score:" in data_point
        assert result['interpretation'] in data_point


class TestSentimentAnalystWorkflow:
    """Tests simulating sentiment analyst workflow."""

    @pytest.mark.asyncio
    async def test_volatility_analysis(self, toolkit, realistic_equity_prices):
        """
        Sentiment analyst workflow:
        1. Compute volatility cone
        2. Compare to implied vol
        3. Identify regime
        """
        returns = realistic_equity_prices["returns"]["SPY"]

        # Volatility cone
        cone = await toolkit.compute_volatility_cone(returns)

        assert isinstance(cone, dict)
        assert 20 in cone or len(cone) > 0

        # Check percentile interpretation
        for window, data in cone.items():
            if data["percentile"] > 90:
                vol_regime = "elevated"
            elif data["percentile"] < 10:
                vol_regime = "depressed"
            else:
                vol_regime = "normal"

            assert vol_regime in ["elevated", "depressed", "normal"]

    @pytest.mark.asyncio
    async def test_iv_rv_analysis(self, toolkit, realistic_equity_prices):
        """
        Test IV vs RV spread analysis.
        """
        # Compute realized vol series
        returns = realistic_equity_prices["returns"]["SPY"]
        rv_series = await toolkit.compute_realized_volatility(
            returns=returns,
            window=20,
        )

        # Compare to a hypothetical IV
        implied_vol = 0.25  # 25% annualized IV

        spread = await toolkit.compute_iv_rv_spread(
            implied_vol=implied_vol,
            realized_vol_series=rv_series,
        )

        assert "regime" in spread
        assert spread["regime"] in ["fear_premium", "complacent", "normal"]


class TestCrossAssetCorrelation:
    """Tests for cross-asset correlation between equities and crypto."""

    @pytest.mark.asyncio
    async def test_equity_crypto_correlation(
        self, toolkit, realistic_equity_prices, realistic_crypto_prices
    ):
        """
        Test correlation analysis across asset classes.
        """
        result = await toolkit.compute_cross_asset_correlation(
            equity_prices=realistic_equity_prices["prices"],
            crypto_prices=realistic_crypto_prices["prices"],
            timestamps_equity=realistic_equity_prices["dates"],
            timestamps_crypto=realistic_crypto_prices["dates"],
        )

        assert "cross_asset_correlations" in result
        assert result["common_dates_count"] > 0

        # Check that cross-correlations exist
        cross = result["cross_asset_correlations"]
        assert any("BTC" in k for k in cross.keys())


class TestSchemaCompatibility:
    """Verify output compatibility with finance schemas."""

    @pytest.mark.asyncio
    async def test_portfolio_snapshot_compatibility(
        self, toolkit, realistic_equity_prices
    ):
        """
        Verify output can populate PortfolioSnapshot fields:
        - max_drawdown_pct
        - daily_pnl_pct context
        """
        returns = realistic_equity_prices["returns"]

        risk = await toolkit.compute_portfolio_risk(
            returns_data=returns,
            weights=[0.4, 0.35, 0.25],
            symbols=list(returns.keys()),
        )

        # PortfolioSnapshot expects max_drawdown_pct
        max_dd = risk.get("max_drawdown")
        assert max_dd is not None
        assert isinstance(max_dd, float)
        assert max_dd <= 0  # Drawdown is negative

    @pytest.mark.asyncio
    async def test_analyst_report_key_risks(self, toolkit, realistic_equity_prices):
        """
        Verify correlation regime alerts can populate AnalystReport.key_risks.
        """
        regime = await toolkit.detect_correlation_regimes(
            price_data=realistic_equity_prices["prices"],
            short_window=20,
            long_window=60,
            z_threshold=1.5,  # Lower threshold to get alerts
        )

        # Convert alerts to key_risks format
        key_risks = []
        for alert in regime["regime_alerts"]:
            risk = (
                f"Correlation {alert['alert']}: {alert['pair']} "
                f"(short={alert['short_corr']:.2f}, long={alert['long_corr']:.2f}, "
                f"z={alert['z_score']:.1f})"
            )
            key_risks.append(risk)

        # Each risk should be a string
        assert all(isinstance(r, str) for r in key_risks)


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_single_asset_portfolio(self, toolkit):
        """Portfolio with single asset."""
        np.random.seed(42)
        returns = list(np.random.normal(0.001, 0.02, 60))

        result = await toolkit.compute_portfolio_risk(
            returns_data={"AAPL": returns},
            weights=[1.0],
            symbols=["AAPL"],
        )

        assert "portfolio_volatility" in result

    @pytest.mark.asyncio
    async def test_stress_test_missing_symbols(self, toolkit):
        """Stress test with portfolio symbols not in scenario."""
        portfolio = {"UNKNOWN_TICKER": 100000}

        result = await toolkit.stress_test_portfolio(
            portfolio_values=portfolio,
            scenario_names=["covid_crash_2020"],
        )

        # Unknown symbol should get 0 shock
        impacts = result["scenario_results"]["covid_crash_2020"]["position_impacts"]
        assert impacts["UNKNOWN_TICKER"]["shock"] == 0
```

### Key Constraints
- Tests should use realistic data (correlated returns, proper price levels)
- Verify output structures match what agents expect
- Test full workflows, not just individual functions
- Include edge cases (single asset, missing data, etc.)

### References in Codebase
- `parrot/finance/schemas.py` — `AnalystReport`, `PortfolioSnapshot`
- `parrot/finance/prompts.py` — risk crew instructions
- `tests/tools/test_ibkr/` — similar integration test patterns

---

## Acceptance Criteria

- [ ] Integration tests for risk analyst workflow
- [ ] Integration tests for equity analyst workflow
- [ ] Integration tests for sentiment analyst workflow
- [ ] Output compatibility with `AnalystReport` schema verified
- [ ] Output compatibility with `PortfolioSnapshot` schema verified
- [ ] Cross-asset correlation test passes
- [ ] Edge cases handled (single asset, missing symbols)
- [ ] All tests pass: `pytest tests/tools/test_quant/test_integration.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/quant-toolkit.spec.md` for full context
2. **Check dependencies** — verify TASK-079 is in `tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-084-quant-integration-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: a2e5d1ea-a67b-47dd-9439-216d1d078fb1
**Date**: 2026-03-02
**Notes**: Created `conftest.py` with 4 shared fixtures (realistic equity/crypto prices, sample portfolio, sample financials) and `test_integration.py` with 13 integration tests across 6 classes. All tests pass in ~0.7s.

**Deviations from spec**:
- Used actual API field names (`var_1d_95_pct` instead of `var_1d_95_usd`, `rolling_vol` instead of `rolling_volatility`).
- `stress_test_portfolio` uses `portfolio_values` + `scenario_names` (not `portfolio_returns`/`weights`/`scenarios`).
- Added extra tests: `test_stress_test_all_predefined_scenarios`, `test_rolling_metrics_workflow`.
