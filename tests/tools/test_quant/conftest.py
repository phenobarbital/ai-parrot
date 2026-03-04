"""Shared fixtures for QuantToolkit integration tests."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def realistic_equity_prices():
    """Realistic equity price data simulating 1 year of trading days."""
    np.random.seed(42)
    n = 252
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    cov_matrix = np.array([
        [0.04, 0.02, 0.015],
        [0.02, 0.03, 0.018],
        [0.015, 0.018, 0.02],
    ])
    mean_returns = [0.0008, 0.0007, 0.0005]

    returns = np.random.multivariate_normal(mean_returns, cov_matrix / 252, n)

    prices = {
        "AAPL": list(175 * np.cumprod(1 + returns[:, 0])),
        "MSFT": list(380 * np.cumprod(1 + returns[:, 1])),
        "SPY": list(450 * np.cumprod(1 + returns[:, 2])),
    }

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
    """Realistic crypto price data (365 calendar days)."""
    np.random.seed(123)
    n = 365
    dates = pd.date_range("2024-01-01", periods=n, freq="D")

    returns_btc = np.random.normal(0.001, 0.04, n)
    returns_eth = np.random.normal(0.0012, 0.05, n) + 0.3 * returns_btc

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
    """Sample multi-asset portfolio with market values."""
    return {
        "SPY": 100000,
        "AAPL": 50000,
        "MSFT": 30000,
        "BTC": 15000,
        "ETH": 5000,
    }


@pytest.fixture
def sample_financials():
    """Sample financials for Piotroski scoring (AAPL + MSFT)."""
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
