"""
Options Analytics Data Models.

This module defines all shared dataclasses and Pydantic input models used by
the Options Analytics Toolkit components:
- Black-Scholes engine (black_scholes.py)
- Spread analyzers (spreads.py)
- PMCC scanner (pmcc.py)

Design principles:
- Dataclasses for internal computation return types (no validation overhead)
- Pydantic models for external tool inputs (with Field descriptions for LLM context)
- All types are immutable-friendly (no mutable default arguments)
"""
from dataclasses import dataclass, field
from typing import Optional, Literal, Tuple

from pydantic import BaseModel, Field


# =============================================================================
# Dataclasses — Internal computation return types
# =============================================================================


@dataclass(frozen=True)
class IVResult:
    """
    Result from implied volatility calculation.

    Attributes:
        iv: The calculated implied volatility (annualized, e.g., 0.25 for 25%).
        converged: Whether the solver converged to a solution.
        iterations: Number of iterations taken by the solver.
        method: The method used to solve ("newton_raphson" or "bisection").
    """
    iv: float
    converged: bool
    iterations: int
    method: Literal["newton_raphson", "bisection"]


@dataclass(frozen=True)
class GreeksResult:
    """
    Greeks for a single option position.

    All values are for a single contract (multiply by contract size and
    quantity for portfolio aggregation).

    Attributes:
        price: Theoretical option price from Black-Scholes.
        delta: Rate of change of option price with respect to underlying price.
               Range: [0, 1] for calls, [-1, 0] for puts.
        gamma: Rate of change of delta with respect to underlying price.
               Always positive, highest at-the-money.
        theta: Rate of time decay per calendar day (negative for long options).
               Expressed as price change per day.
        vega: Sensitivity to 1% change in implied volatility.
              Always positive for long options.
        rho: Sensitivity to 1% change in risk-free rate.
             Positive for calls, negative for puts.
    """
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


@dataclass
class OptionLeg:
    """
    Single leg of a multi-leg option strategy.

    Represents one option contract with its market data. Used as input
    for spread analyzers and strategy evaluations.

    Attributes:
        strike: Strike price of the option.
        option_type: Type of option ("call" or "put").
        bid: Current bid price.
        ask: Current ask price.
        mid: Mid-market price, typically (bid + ask) / 2.
        iv: Implied volatility if available (annualized, e.g., 0.30 for 30%).
    """
    strike: float
    option_type: Literal["call", "put"]
    bid: float
    ask: float
    mid: float
    iv: Optional[float] = None

    def __post_init__(self) -> None:
        """Validate option_type after initialization."""
        if self.option_type not in ("call", "put"):
            raise ValueError(f"option_type must be 'call' or 'put', got '{self.option_type}'")


@dataclass
class PMCCScoringConfig:
    """
    Configuration for PMCC (Poor Man's Covered Call) scoring algorithm.

    The PMCC scanner uses these parameters to score candidate positions
    on an 11-point scale across 6 dimensions. All thresholds and targets
    can be customized based on trading preferences.

    Attributes:
        leaps_delta_target: Target delta for LEAPS (long-term) call.
                           Typical range: 0.70-0.85 (deep ITM).
        short_delta_target: Target delta for short-term call sold against LEAPS.
                           Typical range: 0.15-0.30 (OTM).
        min_leaps_days: Minimum days to expiration for LEAPS selection.
                       Standard is 270+ days (9+ months).
        short_days_range: Acceptable DTE range for short leg (min, max).
                         Typical: 7-21 days for weekly income.
        iv_sweet_spot: Optimal IV range for PMCC (min, max).
                      Too low = poor premium; too high = assignment risk.
        min_annual_yield: Minimum acceptable annualized yield percentage.
        risk_free_rate: Risk-free rate for pricing calculations.
    """
    leaps_delta_target: float = 0.80
    short_delta_target: float = 0.20
    min_leaps_days: int = 270
    short_days_range: Tuple[int, int] = field(default_factory=lambda: (7, 21))
    iv_sweet_spot: Tuple[float, float] = field(default_factory=lambda: (0.25, 0.50))
    min_annual_yield: float = 15.0
    risk_free_rate: float = 0.05


# =============================================================================
# Pydantic Models — External tool input schemas
# =============================================================================


class ComputeGreeksInput(BaseModel):
    """
    Input model for computing option Greeks.

    Used by OptionsAnalyticsToolkit.compute_greeks() method.
    Field descriptions are exposed to LLM agents for tool usage.
    """
    spot: float = Field(
        ...,
        description="Current underlying asset price (e.g., stock price)",
        gt=0
    )
    strike: float = Field(
        ...,
        description="Option strike price",
        gt=0
    )
    dte_days: int = Field(
        ...,
        description="Days to expiration (0 for at-expiry)",
        ge=0
    )
    volatility: float = Field(
        ...,
        description="Annualized implied volatility as decimal (e.g., 0.30 for 30%)",
        gt=0,
        le=5.0
    )
    option_type: Literal["call", "put"] = Field(
        ...,
        description="Option type: 'call' or 'put'"
    )
    risk_free_rate: float = Field(
        0.05,
        description="Risk-free interest rate as decimal (e.g., 0.05 for 5%)",
        ge=-0.1,
        le=0.5
    )

    class Config:
        """Pydantic configuration."""
        json_schema_extra = {
            "example": {
                "spot": 100.0,
                "strike": 105.0,
                "dte_days": 30,
                "volatility": 0.25,
                "option_type": "call",
                "risk_free_rate": 0.05
            }
        }


class AnalyzeSpreadInput(BaseModel):
    """
    Input model for analyzing vertical spread strategies.

    Used by OptionsAnalyticsToolkit.analyze_vertical_spread() method.
    Supports bull/bear call/put spreads.
    """
    underlying_price: float = Field(
        ...,
        description="Current price of the underlying asset",
        gt=0
    )
    long_strike: float = Field(
        ...,
        description="Strike price of the long (bought) option",
        gt=0
    )
    long_bid: float = Field(
        ...,
        description="Bid price of the long option",
        ge=0
    )
    long_ask: float = Field(
        ...,
        description="Ask price of the long option",
        ge=0
    )
    short_strike: float = Field(
        ...,
        description="Strike price of the short (sold) option",
        gt=0
    )
    short_bid: float = Field(
        ...,
        description="Bid price of the short option",
        ge=0
    )
    short_ask: float = Field(
        ...,
        description="Ask price of the short option",
        ge=0
    )
    option_type: Literal["call", "put"] = Field(
        ...,
        description="Option type: 'call' or 'put'"
    )
    expiry_days: int = Field(
        ...,
        description="Days until expiration",
        ge=0
    )
    volatility: float = Field(
        ...,
        description="Implied volatility for probability calculations (decimal)",
        gt=0,
        le=5.0
    )
    risk_free_rate: float = Field(
        0.05,
        description="Risk-free rate for present value calculations (decimal)",
        ge=-0.1,
        le=0.5
    )

    class Config:
        """Pydantic configuration."""
        json_schema_extra = {
            "example": {
                "underlying_price": 100.0,
                "long_strike": 95.0,
                "long_bid": 6.50,
                "long_ask": 6.80,
                "short_strike": 105.0,
                "short_bid": 1.40,
                "short_ask": 1.60,
                "option_type": "call",
                "expiry_days": 30,
                "volatility": 0.25,
                "risk_free_rate": 0.05
            }
        }


class AnalyzeStraddleInput(BaseModel):
    """
    Input model for analyzing straddle strategies.

    A straddle involves buying (or selling) both a call and put
    at the same strike price and expiration.
    """
    underlying_price: float = Field(
        ...,
        description="Current price of the underlying asset",
        gt=0
    )
    strike: float = Field(
        ...,
        description="Strike price for both call and put",
        gt=0
    )
    call_bid: float = Field(
        ...,
        description="Bid price of the call option",
        ge=0
    )
    call_ask: float = Field(
        ...,
        description="Ask price of the call option",
        ge=0
    )
    put_bid: float = Field(
        ...,
        description="Bid price of the put option",
        ge=0
    )
    put_ask: float = Field(
        ...,
        description="Ask price of the put option",
        ge=0
    )
    expiry_days: int = Field(
        ...,
        description="Days until expiration",
        ge=0
    )
    volatility: float = Field(
        ...,
        description="Implied volatility for probability calculations (decimal)",
        gt=0,
        le=5.0
    )
    risk_free_rate: float = Field(
        0.05,
        description="Risk-free rate for calculations (decimal)",
        ge=-0.1,
        le=0.5
    )


class AnalyzeStrangleInput(BaseModel):
    """
    Input model for analyzing strangle strategies.

    A strangle involves buying (or selling) an OTM call and OTM put
    at different strike prices with the same expiration.
    """
    underlying_price: float = Field(
        ...,
        description="Current price of the underlying asset",
        gt=0
    )
    put_strike: float = Field(
        ...,
        description="Strike price of the put option (typically below current price)",
        gt=0
    )
    call_strike: float = Field(
        ...,
        description="Strike price of the call option (typically above current price)",
        gt=0
    )
    put_bid: float = Field(
        ...,
        description="Bid price of the put option",
        ge=0
    )
    put_ask: float = Field(
        ...,
        description="Ask price of the put option",
        ge=0
    )
    call_bid: float = Field(
        ...,
        description="Bid price of the call option",
        ge=0
    )
    call_ask: float = Field(
        ...,
        description="Ask price of the call option",
        ge=0
    )
    expiry_days: int = Field(
        ...,
        description="Days until expiration",
        ge=0
    )
    volatility: float = Field(
        ...,
        description="Implied volatility for probability calculations (decimal)",
        gt=0,
        le=5.0
    )
    risk_free_rate: float = Field(
        0.05,
        description="Risk-free rate for calculations (decimal)",
        ge=-0.1,
        le=0.5
    )


class AnalyzeIronCondorInput(BaseModel):
    """
    Input model for analyzing iron condor strategies.

    An iron condor combines a bull put spread and a bear call spread,
    profiting when the underlying stays within a range.
    """
    underlying_price: float = Field(
        ...,
        description="Current price of the underlying asset",
        gt=0
    )
    put_buy_strike: float = Field(
        ...,
        description="Strike of the long (bought) put - lowest strike",
        gt=0
    )
    put_sell_strike: float = Field(
        ...,
        description="Strike of the short (sold) put",
        gt=0
    )
    call_sell_strike: float = Field(
        ...,
        description="Strike of the short (sold) call",
        gt=0
    )
    call_buy_strike: float = Field(
        ...,
        description="Strike of the long (bought) call - highest strike",
        gt=0
    )
    put_buy_price: float = Field(
        ...,
        description="Premium paid for the long put (mid price)",
        ge=0
    )
    put_sell_price: float = Field(
        ...,
        description="Premium received for the short put (mid price)",
        ge=0
    )
    call_sell_price: float = Field(
        ...,
        description="Premium received for the short call (mid price)",
        ge=0
    )
    call_buy_price: float = Field(
        ...,
        description="Premium paid for the long call (mid price)",
        ge=0
    )
    expiry_days: int = Field(
        ...,
        description="Days until expiration",
        ge=0
    )
    volatility: float = Field(
        ...,
        description="Implied volatility for probability calculations (decimal)",
        gt=0,
        le=5.0
    )
    risk_free_rate: float = Field(
        0.05,
        description="Risk-free rate for calculations (decimal)",
        ge=-0.1,
        le=0.5
    )


# =============================================================================
# Export list for __all__
# =============================================================================

__all__ = [
    # Dataclasses
    "IVResult",
    "GreeksResult",
    "OptionLeg",
    "PMCCScoringConfig",
    # Pydantic models
    "ComputeGreeksInput",
    "AnalyzeSpreadInput",
    "AnalyzeStraddleInput",
    "AnalyzeStrangleInput",
    "AnalyzeIronCondorInput",
]
