---
type: Concept
title: stress_test_portfolio()
id: func:parrot_tools.quant.stress_testing.stress_test_portfolio
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Apply stress scenarios to a portfolio and estimate losses.
---

# stress_test_portfolio

```python
def stress_test_portfolio(portfolio_values: dict[str, float], weights: list[float] | None=None, symbols: list[str] | None=None, scenarios: list[StressScenario] | None=None, total_portfolio_value: float | None=None) -> dict
```

Apply stress scenarios to a portfolio and estimate losses.

Args:
    portfolio_values: {symbol: current_market_value} mapping.
    weights: Position weights (optional, for documentation only).
    symbols: Symbol list (optional, for documentation only).
    scenarios: List of stress scenarios to apply. If None, uses all predefined.
    total_portfolio_value: Total portfolio value. If None, calculated from positions.

Returns:
    Dictionary with structure:
    {
        "scenario_results": {
            "covid_crash_2020": {
                "portfolio_loss_pct": -0.32,
                "portfolio_loss_usd": -32000.0,
                "position_impacts": {
                    "SPY": {"shock": -0.34, "loss_usd": -17000.0},
                    ...
                },
                "worst_position": "BTC",
                "best_position": "TLT",
            },
            ...
        },
        "worst_scenario": "covid_crash_2020",
        "max_loss_pct": -0.35,
    }

Raises:
    ValueError: If portfolio value is not positive.
