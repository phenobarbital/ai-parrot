"""
Research Memory Tools
======================

Tools for research crews and analysts to interact with collective memory.

Crew Tools (Deduplication):
- check_research_exists: Check if research already exists for a period
- store_research: Store completed research to collective memory

Analyst Tools (Query):
- get_latest_research: Get most recent research for a domain
- get_research_history: Get N recent documents for a domain
- get_cross_domain_research: Get latest from multiple domains
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Union

from parrot.tools import tool
from parrot.finance.schemas import ResearchBriefing, ResearchItem

from .abstract import ResearchMemory
from .schemas import (
    ResearchDocument,
    generate_period_key,
    DEFAULT_RESEARCH_SCHEDULES,
)


# =============================================================================
# GLOBAL MEMORY INSTANCE
# =============================================================================


_memory: ResearchMemory | None = None


def set_research_memory(memory: ResearchMemory) -> None:
    """Set the global research memory instance.

    Call this at service startup to inject the memory implementation.

    Args:
        memory: A ResearchMemory implementation (e.g., FileResearchMemory)
    """
    global _memory
    _memory = memory


def get_research_memory() -> ResearchMemory:
    """Get the global research memory instance.

    Returns:
        The configured ResearchMemory instance.

    Raises:
        RuntimeError: If set_research_memory() was not called first.
    """
    if _memory is None:
        raise RuntimeError(
            "Research memory not initialized. Call set_research_memory() first."
        )
    return _memory


# =============================================================================
# CREW TOOLS (DEDUPLICATION)
# =============================================================================


@tool()
async def check_research_exists(
    crew_id: str,
    period_key: str | None = None,
) -> dict[str, Any]:
    """Check if research already exists for this crew and period.

    Use this BEFORE executing research to avoid duplicate work.
    If research exists, skip execution and return early.

    Args:
        crew_id: The research crew identifier (e.g., "research_crew_macro")
        period_key: The period in ISO format. If not provided, uses current period
                    based on the crew's schedule configuration.

    Returns:
        A dict with:
        - exists (bool): Whether research exists for this period
        - message (str): Human-readable status message
        - document_id (str | None): ID of existing document if found
        - period_key (str): The period key that was checked

    Example:
        >>> result = await check_research_exists("research_crew_macro")
        >>> if result["exists"]:
        >>>     return "Research already completed for today"
    """
    memory = get_research_memory()

    # Generate period key if not provided
    if period_key is None:
        config = DEFAULT_RESEARCH_SCHEDULES.get(crew_id)
        granularity = config.period_granularity if config else "daily"
        period_key = generate_period_key(granularity)

    exists = await memory.exists(crew_id, period_key)

    if exists:
        doc = await memory.get(crew_id, period_key)
        return {
            "exists": True,
            "message": f"Research already completed for {crew_id} period {period_key}",
            "document_id": doc.id if doc else None,
            "period_key": period_key,
        }

    return {
        "exists": False,
        "message": f"No research found for {crew_id} period {period_key}. Proceed with execution.",
        "document_id": None,
        "period_key": period_key,
    }


@tool()
async def store_research(
    briefing: Union[dict[str, Any], str],
    crew_id: str,
    domain: str,
) -> dict[str, Any]:
    """Store a completed research briefing in collective memory.

    Call this after completing research to persist the results.
    Other analysts can then retrieve this research.

    Args:
        briefing: The research briefing content as a dict or JSON string (ResearchBriefing structure)
        crew_id: The research crew identifier (e.g., "research_crew_macro")
        domain: The research domain (macro, equity, crypto, sentiment, risk)

    Returns:
        A dict with:
        - success (bool): Whether storage succeeded
        - document_id (str): The stored document's ID
        - period_key (str): The period key used for storage

    Example:
        >>> result = await store_research(
        ...     briefing=my_briefing_dict,
        ...     crew_id="research_crew_macro",
        ...     domain="macro"
        ... )
        >>> print(f"Stored as {result['document_id']}")
    """
    memory = get_research_memory()

    # Parse briefing - handle string (JSON), list, dict, or ResearchBriefing
    if isinstance(briefing, str):
        # LLM may pass JSON string - parse it
        try:
            briefing = json.loads(briefing)
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Invalid JSON in briefing: {e}",
            }

    # Handle case where briefing is a list (research_items array directly)
    if isinstance(briefing, list):
        briefing = {"research_items": briefing}

    if isinstance(briefing, dict):
        # Convert nested research_items dicts to ResearchItem dataclass instances
        research_items = []
        for item in briefing.get("research_items", []):
            if isinstance(item, dict):
                # Handle datetime strings
                if "timestamp" in item and isinstance(item["timestamp"], str):
                    try:
                        item["timestamp"] = datetime.fromisoformat(
                            item["timestamp"].replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        item["timestamp"] = datetime.now(timezone.utc)
                research_items.append(ResearchItem(**item))
            elif isinstance(item, ResearchItem):
                research_items.append(item)

        # Handle generated_at datetime
        generated_at = briefing.get("generated_at")
        if isinstance(generated_at, str):
            try:
                generated_at = datetime.fromisoformat(
                    generated_at.replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                generated_at = datetime.now(timezone.utc)
        elif generated_at is None:
            generated_at = datetime.now(timezone.utc)

        research_briefing = ResearchBriefing(
            id=briefing.get("id", str(uuid.uuid4())),
            analyst_id=briefing.get("analyst_id", ""),
            domain=briefing.get("domain", domain),
            generated_at=generated_at,
            research_items=research_items,
            analyst_track_record=briefing.get("analyst_track_record", {}),
            portfolio_snapshot=briefing.get("portfolio_snapshot", {}),
        )
    elif isinstance(briefing, ResearchBriefing):
        research_briefing = briefing
    else:
        return {
            "success": False,
            "error": f"Invalid briefing type: {type(briefing).__name__}",
        }

    # Generate period key
    config = DEFAULT_RESEARCH_SCHEDULES.get(crew_id)
    granularity = config.period_granularity if config else "daily"
    period_key = generate_period_key(granularity)

    # Create document
    document = ResearchDocument(
        id=uuid.uuid4().hex,
        crew_id=crew_id,
        domain=domain,
        period_key=period_key,
        generated_at=datetime.now(timezone.utc),
        briefing=research_briefing,
        metadata={"sources": []},
    )

    doc_id = await memory.store(document)

    return {
        "success": True,
        "document_id": doc_id,
        "period_key": period_key,
    }


# =============================================================================
# ANALYST TOOLS (QUERY)
# =============================================================================


@tool()
async def get_latest_research(domain: str) -> dict[str, Any]:
    """Get the most recent research for a domain.

    Use this to pull the latest research from collective memory.
    This is the primary way analysts access research data.

    Args:
        domain: The research domain (macro, equity, crypto, sentiment, risk)

    Returns:
        The ResearchDocument as a dict, or an error dict if not found.
        Includes: id, crew_id, domain, period_key, generated_at, briefing, metadata

    Example:
        >>> result = await get_latest_research("macro")
        >>> if "error" not in result:
        >>>     briefing = result["briefing"]
    """
    memory = get_research_memory()

    doc = await memory.get_latest(domain)

    if doc is None:
        return {
            "error": f"No research found for domain '{domain}'",
            "domain": domain,
        }

    return doc.model_dump(mode="json")


@tool()
async def get_research_history(
    domain: str,
    last_n: int = 2,
) -> list[dict[str, Any]]:
    """Get recent research history for a domain.

    Useful for comparing current research with previous periods.
    Returns documents ordered by date descending (newest first).

    Args:
        domain: The research domain (macro, equity, crypto, sentiment, risk)
        last_n: Number of recent documents to retrieve (default: 2)

    Returns:
        List of ResearchDocument dicts ordered by date descending.
        Empty list if no documents found.

    Example:
        >>> history = await get_research_history("macro", last_n=3)
        >>> current = history[0] if history else None
        >>> previous = history[1] if len(history) > 1 else None
    """
    memory = get_research_memory()

    docs = await memory.get_history(domain, last_n=last_n)

    return [doc.model_dump(mode="json") for doc in docs]


@tool()
async def get_cross_domain_research(
    domains: list[str],
) -> dict[str, dict[str, Any]]:
    """Get the latest research from multiple domains.

    Use this for cross-pollination analysis across different research areas.
    Returns a dict mapping each domain to its latest research.

    Args:
        domains: List of domains to query (e.g., ["macro", "sentiment"])

    Returns:
        Dict mapping domain -> latest ResearchDocument dict.
        Domains without research will have an error dict as value.

    Example:
        >>> research = await get_cross_domain_research(["macro", "sentiment"])
        >>> macro_data = research.get("macro", {})
        >>> sentiment_data = research.get("sentiment", {})
    """
    memory = get_research_memory()

    result = {}
    for domain in domains:
        doc = await memory.get_latest(domain)
        if doc:
            result[domain] = doc.model_dump(mode="json")
        else:
            result[domain] = {"error": f"No research found for domain '{domain}'"}

    return result


# =============================================================================
# PER-ASSET RISK TOOLS (Risk Analyst)
# =============================================================================


@tool()
async def get_asset_volatility(
    symbol: str,
    asset_type: str = "stock",
    lookback_days: int = 252,
) -> dict[str, Any]:
    """Get volatility metrics and ATR-based stop-loss levels for an asset.

    Calculates current volatility, ATR, and volatility percentile vs history.
    Returns stop-loss levels for position sizing and risk management.

    Use this tool to assess the risk profile of a specific asset recommended
    by equity or crypto analysts. The output includes ATR-based stop-loss
    levels at 1x (tight), 2x (standard), and 3x (wide) ATR.

    Args:
        symbol: Asset symbol (e.g., "AAPL", "ETH-USD", "BTC-USD")
        asset_type: Type of asset - "stock" or "crypto"
        lookback_days: Number of trading days to analyze (default: 252 = 1 year)

    Returns:
        A dict with:
        - symbol (str): The queried symbol
        - current_price (float): Latest closing price
        - atr_value (float): ATR value in price units
        - atr_percent (float): ATR as percentage of price
        - volatility_20d (float): 20-day annualized volatility
        - volatility_percentile (float): Current vol percentile vs history (0-100)
        - stop_loss_tight (float): Tight stop-loss price (1x ATR below)
        - stop_loss_standard (float): Standard stop-loss price (2x ATR below)
        - stop_loss_wide (float): Wide stop-loss price (3x ATR below)
        - error (str | None): Error message if data fetch failed

    Example:
        >>> result = await get_asset_volatility("CRWD", asset_type="stock")
        >>> print(f"ATR: {result['atr_percent']:.1%}, Stop-loss: ${result['stop_loss_standard']:.2f}")
    """
    import asyncio
    import numpy as np
    import pandas as pd

    try:
        import yfinance as yf
    except ImportError:
        return {
            "symbol": symbol,
            "error": "yfinance not installed. Run: uv pip install yfinance",
        }

    # Normalize symbol for crypto
    if asset_type == "crypto" and not symbol.endswith("-USD"):
        symbol = f"{symbol}-USD"

    try:
        # Fetch OHLCV data via yfinance (run in executor to avoid blocking)
        loop = asyncio.get_running_loop()

        def fetch_data():
            ticker = yf.Ticker(symbol)
            period = f"{lookback_days}d" if lookback_days <= 365 else "1y"
            return ticker.history(period=period, interval="1d")

        df = await loop.run_in_executor(None, fetch_data)

        if df.empty or len(df) < 20:
            return {
                "symbol": symbol,
                "error": f"Insufficient data for {symbol}: got {len(df)} days",
            }

        # Rename columns to lowercase for consistency
        df.columns = [c.lower() for c in df.columns]

        # Current price
        current_price = float(df["close"].iloc[-1])

        # Calculate ATR (14-period)
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr_14 = true_range.rolling(14).mean().iloc[-1]
        atr_percent = (atr_14 / current_price) * 100

        # Calculate returns and volatility
        returns = close.pct_change().dropna()
        annualization = 365 if asset_type == "crypto" else 252

        # 20-day rolling volatility
        rolling_vol = returns.rolling(20).std() * np.sqrt(annualization)
        current_vol = float(rolling_vol.iloc[-1]) if not rolling_vol.empty else 0.0

        # Volatility percentile vs history
        vol_percentile = float((rolling_vol < current_vol).mean() * 100)

        # Stop-loss levels for long positions (below current price)
        stop_loss_tight = current_price - (1.0 * atr_14)
        stop_loss_standard = current_price - (2.0 * atr_14)
        stop_loss_wide = current_price - (3.0 * atr_14)

        return {
            "symbol": symbol,
            "current_price": round(current_price, 4),
            "atr_value": round(float(atr_14), 4),
            "atr_percent": round(float(atr_percent), 2),
            "volatility_20d": round(current_vol, 4),
            "volatility_percentile": round(vol_percentile, 1),
            "stop_loss_tight": round(float(stop_loss_tight), 4),
            "stop_loss_standard": round(float(stop_loss_standard), 4),
            "stop_loss_wide": round(float(stop_loss_wide), 4),
            "error": None,
        }

    except Exception as e:
        return {
            "symbol": symbol,
            "error": f"Failed to fetch volatility data: {str(e)}",
        }


@tool()
async def get_asset_risk_metrics(
    symbol: str,
    asset_type: str = "stock",
    lookback_days: int = 252,
) -> dict[str, Any]:
    """Get comprehensive risk metrics for an asset (VaR, beta, max drawdown).

    Calculates Value at Risk, beta vs benchmark, Sharpe ratio, and max drawdown.
    Use this for detailed risk assessment beyond just volatility.

    Args:
        symbol: Asset symbol (e.g., "AAPL", "ETH-USD")
        asset_type: Type of asset - "stock" or "crypto"
        lookback_days: Number of trading days to analyze (default: 252)

    Returns:
        A dict with:
        - symbol (str): The queried symbol
        - var_1d_95_pct (float): 1-day VaR at 95% confidence as percentage
        - var_1d_99_pct (float): 1-day VaR at 99% confidence as percentage
        - cvar_95_pct (float): Expected Shortfall at 95% as percentage
        - beta (float | None): Beta vs benchmark (SPY for stocks, BTC for crypto)
        - sharpe_ratio (float): Annualized Sharpe ratio
        - max_drawdown (float): Maximum drawdown as percentage
        - volatility_annual (float): Annualized volatility
        - error (str | None): Error message if calculation failed

    Example:
        >>> result = await get_asset_risk_metrics("MRNA", asset_type="stock")
        >>> print(f"VaR(95%): {result['var_1d_95_pct']:.2%}")
    """
    import asyncio
    import numpy as np

    try:
        import yfinance as yf
    except ImportError:
        return {
            "symbol": symbol,
            "error": "yfinance not installed",
        }

    # Import risk metrics utilities
    try:
        from parrot.tools.quant.risk_metrics import (
            compute_returns,
            compute_var_parametric,
            compute_cvar,
            compute_beta,
            compute_sharpe_ratio,
            compute_max_drawdown,
            compute_volatility_annual,
        )
    except ImportError:
        return {
            "symbol": symbol,
            "error": "Risk metrics module not available",
        }

    # Normalize symbol
    original_symbol = symbol
    if asset_type == "crypto" and not symbol.endswith("-USD"):
        symbol = f"{symbol}-USD"

    benchmark_symbol = "BTC-USD" if asset_type == "crypto" else "SPY"

    try:
        loop = asyncio.get_running_loop()

        def fetch_data():
            period = f"{lookback_days}d" if lookback_days <= 365 else "1y"
            asset = yf.Ticker(symbol)
            benchmark = yf.Ticker(benchmark_symbol)
            return (
                asset.history(period=period, interval="1d"),
                benchmark.history(period=period, interval="1d"),
            )

        df_asset, df_benchmark = await loop.run_in_executor(None, fetch_data)

        if df_asset.empty or len(df_asset) < 30:
            return {
                "symbol": original_symbol,
                "error": f"Insufficient data for {symbol}",
            }

        # Calculate returns
        prices_asset = df_asset["Close"].values.tolist()
        returns_asset = compute_returns(prices_asset)

        annualization = 365 if asset_type == "crypto" else 252

        # VaR calculations
        var_95 = compute_var_parametric(returns_asset, 0.95)
        var_99 = compute_var_parametric(returns_asset, 0.99)
        cvar_95 = compute_cvar(returns_asset, 0.95)

        # Beta calculation
        beta = None
        if not df_benchmark.empty and len(df_benchmark) >= 30:
            prices_benchmark = df_benchmark["Close"].values.tolist()
            returns_benchmark = compute_returns(prices_benchmark)
            # Align lengths
            min_len = min(len(returns_asset), len(returns_benchmark))
            if min_len >= 20:
                beta = compute_beta(
                    returns_asset[-min_len:],
                    returns_benchmark[-min_len:]
                )

        # Other metrics
        sharpe = compute_sharpe_ratio(returns_asset, 0.04, annualization)
        max_dd = compute_max_drawdown(returns_asset)
        vol_annual = compute_volatility_annual(returns_asset, annualization)

        return {
            "symbol": original_symbol,
            "var_1d_95_pct": round(abs(var_95) * 100, 2),
            "var_1d_99_pct": round(abs(var_99) * 100, 2),
            "cvar_95_pct": round(abs(cvar_95) * 100, 2),
            "beta": round(beta, 3) if beta is not None else None,
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(abs(max_dd) * 100, 2),
            "volatility_annual": round(vol_annual * 100, 2),
            "benchmark": benchmark_symbol,
            "error": None,
        }

    except Exception as e:
        return {
            "symbol": original_symbol,
            "error": f"Failed to compute risk metrics: {str(e)}",
        }


@tool()
async def calculate_stop_loss(
    symbol: str,
    entry_price: float,
    position_type: str = "long",
    risk_tolerance: str = "standard",
    asset_type: str = "stock",
) -> dict[str, Any]:
    """Calculate ATR-based stop-loss price for a position.

    Computes the optimal stop-loss level based on the asset's ATR
    and the specified risk tolerance level.

    Args:
        symbol: Asset symbol (e.g., "AAPL", "ETH")
        entry_price: The entry price for the position
        position_type: "long" or "short"
        risk_tolerance: Risk level - "tight" (1x ATR), "standard" (2x ATR), "wide" (3x ATR)
        asset_type: Type of asset - "stock" or "crypto"

    Returns:
        A dict with:
        - symbol (str): The queried symbol
        - entry_price (float): The provided entry price
        - stop_loss_price (float): Calculated stop-loss price
        - stop_loss_pct (float): Stop-loss as percentage from entry
        - atr_value (float): ATR value used for calculation
        - atr_multiplier (float): ATR multiplier based on risk_tolerance
        - position_type (str): The position type
        - risk_tolerance (str): The risk tolerance level
        - error (str | None): Error message if calculation failed

    Example:
        >>> result = await calculate_stop_loss("ETH", 3500.0, "long", "standard", "crypto")
        >>> print(f"Stop-loss: ${result['stop_loss_price']:.2f} ({result['stop_loss_pct']:.1%} risk)")
    """
    # First get volatility data
    vol_result = await get_asset_volatility(
        symbol=symbol,
        asset_type=asset_type,
        lookback_days=60,  # Use shorter period for more recent ATR
    )

    if vol_result.get("error"):
        return {
            "symbol": symbol,
            "entry_price": entry_price,
            "error": vol_result["error"],
        }

    atr_value = vol_result["atr_value"]

    # ATR multiplier based on risk tolerance
    multiplier_map = {
        "tight": 1.0,
        "standard": 2.0,
        "wide": 3.0,
    }
    multiplier = multiplier_map.get(risk_tolerance, 2.0)

    # Calculate stop-loss based on position type
    if position_type == "long":
        stop_loss_price = entry_price - (multiplier * atr_value)
        stop_loss_pct = (entry_price - stop_loss_price) / entry_price
    else:  # short
        stop_loss_price = entry_price + (multiplier * atr_value)
        stop_loss_pct = (stop_loss_price - entry_price) / entry_price

    return {
        "symbol": symbol,
        "entry_price": round(entry_price, 4),
        "stop_loss_price": round(stop_loss_price, 4),
        "stop_loss_pct": round(stop_loss_pct * 100, 2),
        "atr_value": round(atr_value, 4),
        "atr_multiplier": multiplier,
        "position_type": position_type,
        "risk_tolerance": risk_tolerance,
        "current_price": vol_result["current_price"],
        "error": None,
    }


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    # Instance management
    "set_research_memory",
    "get_research_memory",
    # Crew tools
    "check_research_exists",
    "store_research",
    # Analyst tools
    "get_latest_research",
    "get_research_history",
    "get_cross_domain_research",
    # Per-asset risk tools
    "get_asset_volatility",
    "get_asset_risk_metrics",
    "calculate_stop_loss",
]
