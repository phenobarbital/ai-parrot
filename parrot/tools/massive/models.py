"""
Pydantic models for MassiveToolkit.

Input models define the schema for agent tool calls.
Output models define the structured response format with derived metrics.
"""

from typing import Literal
from pydantic import BaseModel, Field


# =============================================================================
# INPUT MODELS
# =============================================================================


class OptionsChainInput(BaseModel):
    """Input model for get_options_chain_enriched tool."""

    underlying: str = Field(
        ...,
        description="Underlying ticker symbol (e.g. 'AAPL')",
        min_length=1,
        max_length=10,
    )
    expiration_date_gte: str | None = Field(
        None,
        description="Min expiration date YYYY-MM-DD",
    )
    expiration_date_lte: str | None = Field(
        None,
        description="Max expiration date YYYY-MM-DD",
    )
    strike_price_gte: float | None = Field(
        None,
        description="Min strike price",
        ge=0,
    )
    strike_price_lte: float | None = Field(
        None,
        description="Max strike price",
        ge=0,
    )
    contract_type: Literal["call", "put"] | None = Field(
        None,
        description="'call', 'put', or None for both",
    )
    limit: int = Field(
        250,
        description="Max contracts per page (API max: 250)",
        ge=1,
        le=250,
    )


class ShortInterestInput(BaseModel):
    """Input model for get_short_interest tool."""

    symbol: str = Field(
        ...,
        description="Stock ticker symbol",
        min_length=1,
        max_length=10,
    )
    limit: int = Field(
        10,
        description="Number of settlement periods to return",
        ge=1,
        le=100,
    )
    order: Literal["asc", "desc"] = Field(
        "desc",
        description="'asc' or 'desc' by date",
    )


class ShortVolumeInput(BaseModel):
    """Input model for get_short_volume tool."""

    symbol: str = Field(
        ...,
        description="Stock ticker symbol",
        min_length=1,
        max_length=10,
    )
    date_from: str | None = Field(
        None,
        description="Start date YYYY-MM-DD",
    )
    date_to: str | None = Field(
        None,
        description="End date YYYY-MM-DD",
    )
    limit: int = Field(
        30,
        description="Number of trading days",
        ge=1,
        le=365,
    )


class EarningsDataInput(BaseModel):
    """Input model for get_earnings_data tool."""

    symbol: str | None = Field(
        None,
        description="Filter by ticker",
    )
    date_from: str | None = Field(
        None,
        description="Start date YYYY-MM-DD",
    )
    date_to: str | None = Field(
        None,
        description="End date YYYY-MM-DD",
    )
    importance: int | None = Field(
        None,
        description="Filter by importance (0-5)",
        ge=0,
        le=5,
    )
    limit: int = Field(
        50,
        description="Max results",
        ge=1,
        le=500,
    )


class AnalystRatingsInput(BaseModel):
    """Input model for get_analyst_ratings tool."""

    symbol: str = Field(
        ...,
        description="Stock ticker symbol",
        min_length=1,
        max_length=10,
    )
    action: Literal["upgrade", "downgrade", "initiate", "reiterate"] | None = Field(
        None,
        description="Filter: 'upgrade', 'downgrade', 'initiate', 'reiterate'",
    )
    date_from: str | None = Field(
        None,
        description="Start date YYYY-MM-DD",
    )
    limit: int = Field(
        20,
        description="Max results",
        ge=1,
        le=100,
    )
    include_consensus: bool = Field(
        True,
        description="Also fetch consensus summary",
    )


# =============================================================================
# OUTPUT MODELS - Options Chain
# =============================================================================


class GreeksData(BaseModel):
    """Greeks data for an options contract."""

    delta: float | None = Field(None, description="Delta")
    gamma: float | None = Field(None, description="Gamma")
    theta: float | None = Field(None, description="Theta")
    vega: float | None = Field(None, description="Vega")


class OptionsContract(BaseModel):
    """Single options contract with Greeks and pricing."""

    ticker: str = Field(..., description="Option ticker (e.g. 'O:AAPL250321C00185000')")
    strike: float = Field(..., description="Strike price")
    expiration: str = Field(..., description="Expiration date YYYY-MM-DD")
    contract_type: str = Field(..., description="'call' or 'put'")
    greeks: GreeksData = Field(default_factory=GreeksData, description="Greeks data")
    implied_volatility: float | None = Field(None, description="Implied volatility")
    open_interest: int | None = Field(None, description="Open interest")
    volume: int | None = Field(None, description="Daily volume")
    bid: float | None = Field(None, description="Bid price")
    ask: float | None = Field(None, description="Ask price")
    midpoint: float | None = Field(None, description="Midpoint price")
    last_trade_price: float | None = Field(None, description="Last trade price")
    break_even_price: float | None = Field(None, description="Break-even price")


class OptionsChainOutput(BaseModel):
    """Output model for get_options_chain_enriched."""

    underlying: str = Field(..., description="Underlying ticker symbol")
    underlying_price: float | None = Field(None, description="Current underlying price")
    timestamp: str | None = Field(None, description="Data timestamp ISO 8601")
    contracts_count: int = Field(0, description="Number of contracts returned")
    contracts: list[OptionsContract] = Field(
        default_factory=list, description="List of option contracts"
    )
    source: str = Field("massive", description="Data source identifier")
    cached: bool = Field(False, description="Whether data was served from cache")
    error: str | None = Field(None, description="Error message if request failed")
    fallback: str | None = Field(None, description="Fallback suggestion on error")


# =============================================================================
# OUTPUT MODELS - Short Interest
# =============================================================================


class ShortInterestRecord(BaseModel):
    """Single short interest record."""

    settlement_date: str = Field(..., description="Settlement date YYYY-MM-DD")
    short_interest: int = Field(..., description="Total shares short")
    avg_daily_volume: int | None = Field(None, description="Average daily volume")
    days_to_cover: float | None = Field(None, description="Days to cover")


class ShortInterestDerived(BaseModel):
    """Derived metrics for short interest."""

    short_interest_change_pct: float | None = Field(
        None, description="Percentage change vs previous period"
    )
    trend: Literal["increasing", "decreasing", "stable"] | None = Field(
        None, description="Short interest trend"
    )
    days_to_cover_zscore: float | None = Field(
        None, description="Days to cover z-score vs 12-month history"
    )


class ShortInterestOutput(BaseModel):
    """Output model for get_short_interest."""

    symbol: str = Field(..., description="Stock ticker symbol")
    latest: ShortInterestRecord | None = Field(
        None, description="Most recent short interest data"
    )
    history: list[ShortInterestRecord] = Field(
        default_factory=list, description="Historical short interest data"
    )
    derived: ShortInterestDerived = Field(
        default_factory=ShortInterestDerived, description="Derived metrics"
    )
    source: str = Field("massive", description="Data source identifier")
    cached: bool = Field(False, description="Whether data was served from cache")
    error: str | None = Field(None, description="Error message if request failed")
    fallback: str | None = Field(None, description="Fallback suggestion on error")


# =============================================================================
# OUTPUT MODELS - Short Volume
# =============================================================================


class ShortVolumeRecord(BaseModel):
    """Single short volume record."""

    date: str = Field(..., description="Date YYYY-MM-DD")
    short_volume: int = Field(..., description="Short volume")
    short_exempt_volume: int | None = Field(None, description="Short exempt volume")
    total_volume: int = Field(..., description="Total volume")
    short_volume_ratio: float = Field(..., description="Short volume / total volume")


class ShortVolumeDerived(BaseModel):
    """Derived metrics for short volume."""

    avg_short_ratio_5d: float | None = Field(
        None, description="5-day average short volume ratio"
    )
    avg_short_ratio_20d: float | None = Field(
        None, description="20-day average short volume ratio"
    )
    current_vs_20d: Literal["above_average", "normal", "below_average"] | None = Field(
        None, description="Current ratio vs 20-day average"
    )
    trend_5d: Literal["increasing", "decreasing", "stable"] | None = Field(
        None, description="5-day trend direction"
    )


class ShortVolumeOutput(BaseModel):
    """Output model for get_short_volume."""

    symbol: str = Field(..., description="Stock ticker symbol")
    data: list[ShortVolumeRecord] = Field(
        default_factory=list, description="Short volume data"
    )
    derived: ShortVolumeDerived = Field(
        default_factory=ShortVolumeDerived, description="Derived metrics"
    )
    source: str = Field("massive", description="Data source identifier")
    cached: bool = Field(False, description="Whether data was served from cache")
    error: str | None = Field(None, description="Error message if request failed")
    fallback: str | None = Field(None, description="Fallback suggestion on error")


# =============================================================================
# OUTPUT MODELS - Earnings
# =============================================================================


class EarningsRecord(BaseModel):
    """Single earnings record."""

    date: str = Field(..., description="Earnings date YYYY-MM-DD")
    time: str | None = Field(None, description="BMO (Before Market Open) or AMC (After Market Close)")
    period: str | None = Field(None, description="Reporting period (e.g. 'Q1 2026')")
    eps_estimate: float | None = Field(None, description="EPS estimate")
    eps_actual: float | None = Field(None, description="EPS actual")
    eps_surprise_pct: float | None = Field(None, description="EPS surprise percentage")
    revenue_estimate: float | None = Field(None, description="Revenue estimate")
    revenue_actual: float | None = Field(None, description="Revenue actual")
    revenue_surprise_pct: float | None = Field(None, description="Revenue surprise percentage")


class NextEarnings(BaseModel):
    """Next scheduled earnings."""

    date: str = Field(..., description="Next earnings date YYYY-MM-DD")
    time: str | None = Field(None, description="BMO or AMC")
    eps_estimate: float | None = Field(None, description="EPS estimate")
    revenue_estimate: float | None = Field(None, description="Revenue estimate")


class EarningsDerived(BaseModel):
    """Derived metrics for earnings."""

    beat_rate_4q: float | None = Field(
        None, description="Beat rate last 4 quarters (0.0-1.0)"
    )
    avg_eps_surprise_4q: float | None = Field(
        None, description="Average EPS surprise % last 4 quarters"
    )
    avg_revenue_surprise_4q: float | None = Field(
        None, description="Average revenue surprise % last 4 quarters"
    )
    trend: Literal["consistent_beater", "mixed", "consistent_misser"] | None = Field(
        None, description="Earnings trend classification"
    )


class EarningsOutput(BaseModel):
    """Output model for get_earnings_data."""

    symbol: str | None = Field(None, description="Stock ticker symbol (if filtered)")
    earnings: list[EarningsRecord] = Field(
        default_factory=list, description="Historical earnings data"
    )
    next_earnings: NextEarnings | None = Field(
        None, description="Next scheduled earnings"
    )
    derived: EarningsDerived = Field(
        default_factory=EarningsDerived, description="Derived metrics"
    )
    source: str = Field("massive_benzinga", description="Data source identifier")
    cached: bool = Field(False, description="Whether data was served from cache")
    error: str | None = Field(None, description="Error message if request failed")
    fallback: str | None = Field(None, description="Fallback suggestion on error")


# =============================================================================
# OUTPUT MODELS - Analyst Ratings
# =============================================================================


class AnalystAction(BaseModel):
    """Single analyst rating action."""

    date: str = Field(..., description="Action date YYYY-MM-DD")
    analyst: str | None = Field(None, description="Analyst name")
    firm: str = Field(..., description="Firm name")
    action: str = Field(
        ..., description="Action type: upgrade, downgrade, initiate, reiterate"
    )
    rating_prior: str | None = Field(None, description="Prior rating")
    rating_current: str = Field(..., description="Current rating")
    price_target_prior: float | None = Field(None, description="Prior price target")
    price_target_current: float | None = Field(None, description="Current price target")


class ConsensusRating(BaseModel):
    """Consensus rating summary."""

    buy: int = Field(0, description="Number of buy ratings")
    hold: int = Field(0, description="Number of hold ratings")
    sell: int = Field(0, description="Number of sell ratings")
    strong_buy: int = Field(0, description="Number of strong buy ratings")
    strong_sell: int = Field(0, description="Number of strong sell ratings")
    mean_target: float | None = Field(None, description="Mean price target")
    high_target: float | None = Field(None, description="Highest price target")
    low_target: float | None = Field(None, description="Lowest price target")
    consensus_rating: str | None = Field(
        None, description="Consensus rating (e.g. 'Buy', 'Hold', 'Sell')"
    )


class AnalystRatingsDerived(BaseModel):
    """Derived metrics for analyst ratings."""

    upgrades_30d: int = Field(0, description="Number of upgrades in last 30 days")
    downgrades_30d: int = Field(0, description="Number of downgrades in last 30 days")
    net_sentiment: Literal["positive", "neutral", "negative"] | None = Field(
        None, description="Net sentiment based on upgrade/downgrade ratio"
    )
    target_upside_pct: float | None = Field(
        None, description="Upside to mean target from current price"
    )
    recent_momentum: Literal["improving", "stable", "deteriorating"] | None = Field(
        None, description="Recent momentum based on action trend"
    )


class AnalystRatingsOutput(BaseModel):
    """Output model for get_analyst_ratings."""

    symbol: str = Field(..., description="Stock ticker symbol")
    recent_actions: list[AnalystAction] = Field(
        default_factory=list, description="Recent analyst actions"
    )
    consensus: ConsensusRating | None = Field(
        None, description="Consensus rating summary"
    )
    derived: AnalystRatingsDerived = Field(
        default_factory=AnalystRatingsDerived, description="Derived metrics"
    )
    source: str = Field("massive_benzinga", description="Data source identifier")
    cached: bool = Field(False, description="Whether data was served from cache")
    error: str | None = Field(None, description="Error message if request failed")
    fallback: str | None = Field(None, description="Fallback suggestion on error")
