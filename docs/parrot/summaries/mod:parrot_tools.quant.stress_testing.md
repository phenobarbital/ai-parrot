---
type: Wiki Summary
title: parrot_tools.quant.stress_testing
id: mod:parrot_tools.quant.stress_testing
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Stress Testing Framework for QuantToolkit.
relates_to:
- concept: func:parrot_tools.quant.stress_testing.create_custom_scenario
  rel: defines
- concept: func:parrot_tools.quant.stress_testing.create_sector_rotation_scenario
  rel: defines
- concept: func:parrot_tools.quant.stress_testing.create_volatility_shock_scenario
  rel: defines
- concept: func:parrot_tools.quant.stress_testing.get_concentrated_risk_positions
  rel: defines
- concept: func:parrot_tools.quant.stress_testing.get_predefined_scenario
  rel: defines
- concept: func:parrot_tools.quant.stress_testing.get_scenario_descriptions
  rel: defines
- concept: func:parrot_tools.quant.stress_testing.list_predefined_scenarios
  rel: defines
- concept: func:parrot_tools.quant.stress_testing.stress_test_portfolio
  rel: defines
- concept: func:parrot_tools.quant.stress_testing.summarize_stress_results
  rel: defines
- concept: mod:parrot_tools.quant.models
  rel: references
---

# `parrot_tools.quant.stress_testing`

Stress Testing Framework for QuantToolkit.

Provides portfolio stress testing capabilities:
- Apply historical or hypothetical shock scenarios to portfolios
- Calculate portfolio-level and position-level losses
- Identify worst/best performing positions under stress
- Generate custom volatility spike scenarios

Predefined Scenarios:
- covid_crash_2020: March 2020 COVID market crash
- rate_hike_shock: Interest rate increase scenario
- crypto_winter: Major crypto bear market
- black_swan: Generic severe market stress

## Functions

- `def stress_test_portfolio(portfolio_values: dict[str, float], weights: list[float] | None=None, symbols: list[str] | None=None, scenarios: list[StressScenario] | None=None, total_portfolio_value: float | None=None) -> dict` — Apply stress scenarios to a portfolio and estimate losses.
- `def get_predefined_scenario(name: str) -> StressScenario` — Get a predefined stress scenario by name.
- `def list_predefined_scenarios() -> list[str]` — List all available predefined scenario names.
- `def get_scenario_descriptions() -> dict[str, str]` — Get descriptions for all predefined scenarios.
- `def create_volatility_shock_scenario(current_volatilities: dict[str, float], multiplier: float=2.0, vol_to_return_factor: float=-0.5) -> StressScenario` — Create a scenario where volatility spikes by a multiplier.
- `def create_custom_scenario(name: str, asset_shocks: dict[str, float], description: str | None=None) -> StressScenario` — Create a custom stress scenario.
- `def create_sector_rotation_scenario(sector_shocks: dict[str, float], sector_mapping: dict[str, str]) -> StressScenario` — Create a sector rotation scenario.
- `def summarize_stress_results(stress_result: dict) -> str` — Generate a human-readable summary of stress test results.
- `def get_concentrated_risk_positions(stress_result: dict, threshold_pct: float=0.1) -> list[dict]` — Identify positions that contribute disproportionately to losses.
