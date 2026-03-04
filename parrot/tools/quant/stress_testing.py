"""
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
"""

from .models import StressScenario


# =============================================================================
# PREDEFINED HISTORICAL SCENARIOS
# =============================================================================


PREDEFINED_SCENARIOS: dict[str, StressScenario] = {
    "covid_crash_2020": StressScenario(
        name="covid_crash_2020",
        description="March 2020 COVID-19 market crash",
        asset_shocks={
            # US Equities
            "SPY": -0.34,
            "QQQ": -0.28,
            "IWM": -0.41,
            "DIA": -0.37,
            # International
            "EEM": -0.32,
            "EFA": -0.33,
            # Crypto
            "BTC": -0.50,
            "ETH": -0.60,
            # Bonds (flight to safety)
            "TLT": 0.20,
            "AGG": 0.05,
            # Commodities
            "GLD": 0.03,
            "USO": -0.70,  # Oil crashed hard
        },
    ),
    "rate_hike_shock": StressScenario(
        name="rate_hike_shock",
        description="Aggressive interest rate increase scenario",
        asset_shocks={
            # US Equities (growth hit harder)
            "SPY": -0.10,
            "QQQ": -0.15,
            "IWM": -0.12,
            "DIA": -0.08,
            # Bonds fall on rate hikes
            "TLT": -0.15,
            "AGG": -0.08,
            # Crypto (risk-off)
            "BTC": -0.25,
            "ETH": -0.30,
            # Real estate impacted
            "VNQ": -0.18,
        },
    ),
    "crypto_winter": StressScenario(
        name="crypto_winter",
        description="Severe crypto bear market (2022-style)",
        asset_shocks={
            # Crypto devastated
            "BTC": -0.70,
            "ETH": -0.80,
            "SOL": -0.90,
            "ADA": -0.85,
            "DOT": -0.88,
            "AVAX": -0.87,
            "MATIC": -0.85,
            "LINK": -0.80,
            # Minor equity spillover
            "SPY": -0.05,
            "QQQ": -0.08,
            # Crypto-related stocks
            "COIN": -0.80,
            "MSTR": -0.75,
        },
    ),
    "black_swan": StressScenario(
        name="black_swan",
        description="Generic severe market stress event",
        asset_shocks={
            # Broad equity selloff
            "SPY": -0.25,
            "QQQ": -0.30,
            "IWM": -0.35,
            "DIA": -0.23,
            # International
            "EEM": -0.35,
            "EFA": -0.28,
            # Crypto
            "BTC": -0.40,
            "ETH": -0.50,
            # Safe havens rally
            "TLT": 0.10,
            "GLD": 0.15,
            "AGG": 0.02,
        },
    ),
    "stagflation": StressScenario(
        name="stagflation",
        description="High inflation + low growth scenario",
        asset_shocks={
            # Equities suffer
            "SPY": -0.15,
            "QQQ": -0.20,
            "IWM": -0.18,
            # Bonds hurt by inflation
            "TLT": -0.12,
            "AGG": -0.06,
            # Commodities benefit
            "GLD": 0.20,
            "USO": 0.15,
            "DBA": 0.10,  # Agriculture
            # Crypto mixed
            "BTC": -0.10,
            "ETH": -0.15,
        },
    ),
}


# =============================================================================
# STRESS TEST FUNCTIONS
# =============================================================================


def stress_test_portfolio(
    portfolio_values: dict[str, float],
    weights: list[float] | None = None,
    symbols: list[str] | None = None,
    scenarios: list[StressScenario] | None = None,
    total_portfolio_value: float | None = None,
) -> dict:
    """Apply stress scenarios to a portfolio and estimate losses.

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
    """
    if total_portfolio_value is None:
        total_portfolio_value = sum(portfolio_values.values())

    if total_portfolio_value <= 0:
        raise ValueError("Portfolio value must be positive")

    # Default to all predefined scenarios
    if scenarios is None:
        scenarios = list(PREDEFINED_SCENARIOS.values())

    scenario_results = {}
    max_loss = 0.0
    worst_scenario = None

    for scenario in scenarios:
        result = _apply_scenario_to_portfolio(
            portfolio_values=portfolio_values,
            scenario=scenario,
            total_portfolio_value=total_portfolio_value,
        )
        scenario_results[scenario.name] = result

        if result["portfolio_loss_pct"] < max_loss:
            max_loss = result["portfolio_loss_pct"]
            worst_scenario = scenario.name

    return {
        "scenario_results": scenario_results,
        "worst_scenario": worst_scenario,
        "max_loss_pct": round(max_loss, 4),
    }


def _apply_scenario_to_portfolio(
    portfolio_values: dict[str, float],
    scenario: StressScenario,
    total_portfolio_value: float,
) -> dict:
    """Apply a single scenario to portfolio and calculate impacts.

    Args:
        portfolio_values: {symbol: current_market_value} mapping.
        scenario: Stress scenario to apply.
        total_portfolio_value: Total portfolio value for percentage calculation.

    Returns:
        Dictionary with scenario results.
    """
    position_impacts = {}
    total_loss = 0.0

    for symbol, value in portfolio_values.items():
        # Get shock for this symbol, default to 0 if not in scenario
        shock = scenario.asset_shocks.get(symbol, 0.0)
        loss_usd = value * shock  # shock is negative for losses
        position_impacts[symbol] = {
            "shock": shock,
            "loss_usd": round(loss_usd, 2),
        }
        total_loss += loss_usd

    portfolio_loss_pct = total_loss / total_portfolio_value

    # Find worst and best positions
    worst_position = None
    best_position = None

    if position_impacts:
        impacts_list = [(s, d["loss_usd"]) for s, d in position_impacts.items()]
        worst_position = min(impacts_list, key=lambda x: x[1])[0]
        best_position = max(impacts_list, key=lambda x: x[1])[0]

    return {
        "portfolio_loss_pct": round(portfolio_loss_pct, 4),
        "portfolio_loss_usd": round(total_loss, 2),
        "position_impacts": position_impacts,
        "worst_position": worst_position,
        "best_position": best_position,
    }


# =============================================================================
# SCENARIO MANAGEMENT
# =============================================================================


def get_predefined_scenario(name: str) -> StressScenario:
    """Get a predefined stress scenario by name.

    Args:
        name: Scenario name (e.g., "covid_crash_2020").

    Returns:
        StressScenario object.

    Raises:
        ValueError: If scenario name is unknown.
    """
    if name not in PREDEFINED_SCENARIOS:
        available = list(PREDEFINED_SCENARIOS.keys())
        raise ValueError(f"Unknown scenario: {name}. Available: {available}")
    return PREDEFINED_SCENARIOS[name]


def list_predefined_scenarios() -> list[str]:
    """List all available predefined scenario names.

    Returns:
        List of scenario names.
    """
    return list(PREDEFINED_SCENARIOS.keys())


def get_scenario_descriptions() -> dict[str, str]:
    """Get descriptions for all predefined scenarios.

    Returns:
        {scenario_name: description} mapping.
    """
    return {
        name: scenario.description or ""
        for name, scenario in PREDEFINED_SCENARIOS.items()
    }


# =============================================================================
# CUSTOM SCENARIO GENERATORS
# =============================================================================


def create_volatility_shock_scenario(
    current_volatilities: dict[str, float],
    multiplier: float = 2.0,
    vol_to_return_factor: float = -0.5,
) -> StressScenario:
    """Create a scenario where volatility spikes by a multiplier.

    Higher vol typically correlates with negative returns.
    Rule of thumb: 2x vol spike ~ -10% to -20% return for equities.

    Args:
        current_volatilities: {symbol: current_annual_vol} mapping.
        multiplier: How much vol increases (2.0 = doubles).
        vol_to_return_factor: Conversion factor (negative = vol up means returns down).

    Returns:
        StressScenario with estimated return shocks.

    Example:
        >>> current_vols = {"SPY": 0.20, "BTC": 0.60}
        >>> scenario = create_volatility_shock_scenario(current_vols, multiplier=2.0)
        >>> # BTC will have larger shock due to higher base volatility
    """
    shocks = {}
    for symbol, vol in current_volatilities.items():
        # Estimate return shock from vol spike
        # Higher vol assets get hit harder
        vol_increase = vol * (multiplier - 1)
        shock = vol_increase * vol_to_return_factor
        # Cap at -95% (complete wipeout protection)
        shocks[symbol] = round(max(shock, -0.95), 4)

    return StressScenario(
        name=f"vol_spike_{multiplier}x",
        description=f"Volatility spike scenario ({multiplier}x current vol)",
        asset_shocks=shocks,
    )


def create_custom_scenario(
    name: str,
    asset_shocks: dict[str, float],
    description: str | None = None,
) -> StressScenario:
    """Create a custom stress scenario.

    Args:
        name: Scenario name.
        asset_shocks: {symbol: shock_pct} mapping (e.g., -0.20 = -20%).
        description: Optional description.

    Returns:
        StressScenario object.
    """
    return StressScenario(
        name=name,
        description=description or f"Custom scenario: {name}",
        asset_shocks=asset_shocks,
    )


def create_sector_rotation_scenario(
    sector_shocks: dict[str, float],
    sector_mapping: dict[str, str],
) -> StressScenario:
    """Create a sector rotation scenario.

    Args:
        sector_shocks: {sector: shock_pct} mapping.
            Example: {"tech": -0.15, "energy": 0.10, "utilities": 0.05}
        sector_mapping: {symbol: sector} mapping.
            Example: {"AAPL": "tech", "XOM": "energy", "NEE": "utilities"}

    Returns:
        StressScenario with symbol-level shocks derived from sectors.
    """
    asset_shocks = {}
    for symbol, sector in sector_mapping.items():
        if sector in sector_shocks:
            asset_shocks[symbol] = sector_shocks[sector]
        else:
            asset_shocks[symbol] = 0.0  # No shock for unmapped sectors

    return StressScenario(
        name="sector_rotation",
        description="Sector rotation scenario",
        asset_shocks=asset_shocks,
    )


# =============================================================================
# STRESS TEST ANALYSIS
# =============================================================================


def summarize_stress_results(stress_result: dict) -> str:
    """Generate a human-readable summary of stress test results.

    Args:
        stress_result: Output from stress_test_portfolio().

    Returns:
        Formatted summary string.
    """
    lines = ["STRESS TEST SUMMARY", "=" * 40]

    worst = stress_result.get("worst_scenario")
    max_loss = stress_result.get("max_loss_pct", 0)

    lines.append(f"Worst Scenario: {worst} ({max_loss:.1%} loss)")
    lines.append("")

    for scenario_name, result in stress_result.get("scenario_results", {}).items():
        loss_pct = result.get("portfolio_loss_pct", 0)
        loss_usd = result.get("portfolio_loss_usd", 0)
        worst_pos = result.get("worst_position", "N/A")
        best_pos = result.get("best_position", "N/A")

        lines.append(f"{scenario_name}:")
        lines.append(f"  Portfolio Loss: {loss_pct:.2%} (${loss_usd:,.2f})")
        lines.append(f"  Worst Position: {worst_pos}")
        lines.append(f"  Best Position:  {best_pos}")
        lines.append("")

    return "\n".join(lines)


def get_concentrated_risk_positions(
    stress_result: dict,
    threshold_pct: float = 0.10,
) -> list[dict]:
    """Identify positions that contribute disproportionately to losses.

    Args:
        stress_result: Output from stress_test_portfolio().
        threshold_pct: Loss threshold as fraction of portfolio (default 10%).

    Returns:
        List of positions with high stress impact:
        [{"symbol": "BTC", "scenario": "covid_crash_2020", "loss_pct": -0.15}, ...]
    """
    concentrated = []

    for scenario_name, result in stress_result.get("scenario_results", {}).items():
        total_value = abs(result.get("portfolio_loss_usd", 0))
        if total_value == 0:
            continue

        for symbol, impact in result.get("position_impacts", {}).items():
            loss_usd = impact.get("loss_usd", 0)
            if loss_usd < 0:  # Only losses
                # Calculate loss as % of total portfolio loss
                loss_contribution = abs(loss_usd) / total_value if total_value > 0 else 0
                if loss_contribution >= threshold_pct:
                    concentrated.append({
                        "symbol": symbol,
                        "scenario": scenario_name,
                        "loss_usd": loss_usd,
                        "loss_contribution": round(loss_contribution, 4),
                        "shock": impact.get("shock", 0),
                    })

    # Sort by loss contribution (highest first)
    return sorted(concentrated, key=lambda x: x["loss_contribution"], reverse=True)
