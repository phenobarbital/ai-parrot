"""Strike selection engine for options strategies.

This module provides algorithms for selecting optimal strikes based on
criteria like delta targets, ATM proximity, and liquidity thresholds.

Usage:
    from parrot.finance.tools.strike_selection import StrikeSelectionEngine

    engine = StrikeSelectionEngine()

    # Find ATM strike
    atm = engine.find_atm_strike(puts, 100.0)

    # Find by delta
    short_put = engine.find_strike_by_delta(puts, 0.30, "put")

    # Select full strategy
    strikes = engine.select_iron_butterfly_strikes(
        calls, puts, 100.0, wing_width=5.0
    )
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Any

from navconfig.logging import logging


@dataclass
class SelectedStrikes:
    """Result of strike selection for a multi-leg strategy.

    Attributes:
        long_put: Symbol and details for the long put wing.
        short_put: Symbol and details for the short put.
        short_call: Symbol and details for the short call.
        long_call: Symbol and details for the long call wing.
        underlying_price: Current price of the underlying.
        expiration: Expiration date for all legs.
    """

    long_put: Dict[str, Any]
    short_put: Dict[str, Any]
    short_call: Dict[str, Any]
    long_call: Dict[str, Any]
    underlying_price: float
    expiration: str


class StrikeSelectionError(ValueError):
    """Raised when strike selection fails."""


class StrikeSelectionEngine:
    """Engine for selecting optimal strikes for options strategies.

    Provides methods to find strikes by ATM proximity, delta targeting,
    and liquidity requirements. Used by the options toolkit to build
    multi-leg strategies.
    """

    def __init__(
        self,
        min_open_interest: int = 50,
        max_spread_pct: float = 10.0,
    ):
        """Initialize the strike selection engine.

        Args:
            min_open_interest: Minimum open interest for liquidity (default: 50).
            max_spread_pct: Maximum bid-ask spread as % of mid price (default: 10%).
        """
        self.logger = logging.getLogger("StrikeSelectionEngine")
        self.min_open_interest = min_open_interest
        self.max_spread_pct = max_spread_pct

    def find_atm_strike(
        self,
        options: List[Dict[str, Any]],
        underlying_price: float,
        validate_liquidity: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Find the strike closest to the underlying price (ATM).

        Args:
            options: List of option contracts with 'strike' field.
            underlying_price: Current price of the underlying.
            validate_liquidity: Whether to check liquidity thresholds.

        Returns:
            Option contract closest to ATM, or None if no valid strikes.
        """
        if not options:
            return None

        # Filter by liquidity if required
        candidates = options
        if validate_liquidity:
            candidates = [
                opt for opt in options
                if self.validate_liquidity(opt)
            ]

        if not candidates:
            self.logger.warning("No liquid options found near ATM")
            return None

        # Sort by distance to underlying price
        return min(
            candidates,
            key=lambda opt: abs(opt["strike"] - underlying_price)
        )

    def find_strike_by_delta(
        self,
        options: List[Dict[str, Any]],
        target_delta: float,
        contract_type: str,
        validate_liquidity: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Find the strike closest to the target delta.

        For puts, delta is negative (e.g., -0.30 for 30-delta put).
        For calls, delta is positive (e.g., +0.30 for 30-delta call).

        Args:
            options: List of option contracts with 'delta' field.
            target_delta: Target delta value (absolute, 0-1 range).
            contract_type: Either "call" or "put".
            validate_liquidity: Whether to check liquidity thresholds.

        Returns:
            Option contract closest to target delta, or None if not found.
        """
        if not options:
            return None

        # Filter by liquidity if required
        candidates = options
        if validate_liquidity:
            candidates = [
                opt for opt in options
                if self.validate_liquidity(opt)
            ]

        # Filter to contracts with valid delta
        candidates = [opt for opt in candidates if opt.get("delta") is not None]

        if not candidates:
            self.logger.warning(
                "No liquid options found at delta %.2f", target_delta
            )
            return None

        # For puts, delta is negative; for calls, positive
        # We compare absolute values
        if contract_type == "put":
            # Put deltas are negative, so abs(delta) should match target
            return min(
                candidates,
                key=lambda opt: abs(abs(opt["delta"]) - target_delta)
            )
        else:
            # Call deltas are positive
            return min(
                candidates,
                key=lambda opt: abs(opt["delta"] - target_delta)
            )

    def find_strike_at_offset(
        self,
        options: List[Dict[str, Any]],
        base_strike: float,
        offset: float,
        validate_liquidity: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Find a strike at a specific offset from a base strike.

        Args:
            options: List of option contracts.
            base_strike: The reference strike price.
            offset: Offset from base strike (negative for lower).
            validate_liquidity: Whether to check liquidity thresholds.

        Returns:
            Option contract closest to target strike, or None.
        """
        target_strike = base_strike + offset

        # Filter by liquidity if required
        candidates = options
        if validate_liquidity:
            candidates = [
                opt for opt in options
                if self.validate_liquidity(opt)
            ]

        if not candidates:
            return None

        return min(
            candidates,
            key=lambda opt: abs(opt["strike"] - target_strike)
        )

    def validate_liquidity(self, option: Dict[str, Any]) -> bool:
        """Check if an option meets liquidity requirements.

        Validates:
        - Bid and ask prices exist
        - Bid-ask spread is within threshold

        Args:
            option: Option contract with bid, ask fields.

        Returns:
            True if option meets liquidity requirements.
        """
        bid = option.get("bid")
        ask = option.get("ask")

        # Must have valid quotes
        if bid is None or ask is None:
            return False
        if bid <= 0 or ask <= 0:
            return False

        # Check spread percentage
        mid_price = (bid + ask) / 2
        if mid_price <= 0:
            return False

        spread_pct = ((ask - bid) / mid_price) * 100
        if spread_pct > self.max_spread_pct:
            self.logger.debug(
                "Strike %.2f spread %.1f%% exceeds max %.1f%%",
                option.get("strike", 0),
                spread_pct,
                self.max_spread_pct,
            )
            return False

        return True

    def select_iron_butterfly_strikes(
        self,
        calls: List[Dict[str, Any]],
        puts: List[Dict[str, Any]],
        underlying_price: float,
        wing_width: float = 5.0,
        expiration: Optional[str] = None,
    ) -> SelectedStrikes:
        """Select strikes for an Iron Butterfly strategy.

        Iron Butterfly structure:
        - Long Put at ATM - wing_width
        - Short Put at ATM
        - Short Call at ATM (same strike as short put)
        - Long Call at ATM + wing_width

        Args:
            calls: List of call option contracts.
            puts: List of put option contracts.
            underlying_price: Current price of the underlying.
            wing_width: Distance from ATM to wing strikes.
            expiration: Optional specific expiration to filter.

        Returns:
            SelectedStrikes with all 4 legs.

        Raises:
            StrikeSelectionError: If suitable strikes cannot be found.
        """
        # Filter by expiration if specified
        if expiration:
            calls = [c for c in calls if c.get("expiration") == expiration]
            puts = [p for p in puts if p.get("expiration") == expiration]

        # Find ATM strike using puts (could also use calls)
        atm_put = self.find_atm_strike(puts, underlying_price)
        if not atm_put:
            raise StrikeSelectionError(
                f"No ATM put found near {underlying_price}"
            )

        atm_strike = atm_put["strike"]

        # Find ATM call at same strike
        atm_call = self.find_strike_at_offset(calls, atm_strike, 0)
        if not atm_call:
            raise StrikeSelectionError(
                f"No ATM call found at strike {atm_strike}"
            )

        # Find wing strikes
        long_put = self.find_strike_at_offset(puts, atm_strike, -wing_width)
        if not long_put:
            raise StrikeSelectionError(
                f"No put wing found at strike {atm_strike - wing_width}"
            )

        long_call = self.find_strike_at_offset(calls, atm_strike, wing_width)
        if not long_call:
            raise StrikeSelectionError(
                f"No call wing found at strike {atm_strike + wing_width}"
            )

        selected_expiration = atm_put.get("expiration", expiration or "unknown")

        return SelectedStrikes(
            long_put=long_put,
            short_put=atm_put,
            short_call=atm_call,
            long_call=long_call,
            underlying_price=underlying_price,
            expiration=selected_expiration,
        )

    def select_iron_condor_strikes(
        self,
        calls: List[Dict[str, Any]],
        puts: List[Dict[str, Any]],
        underlying_price: float,
        short_delta: float = 0.30,
        wing_width: float = 5.0,
        expiration: Optional[str] = None,
    ) -> SelectedStrikes:
        """Select strikes for an Iron Condor strategy.

        Iron Condor structure:
        - Long Put at short_put_strike - wing_width
        - Short Put at target delta (OTM)
        - Short Call at target delta (OTM)
        - Long Call at short_call_strike + wing_width

        Args:
            calls: List of call option contracts.
            puts: List of put option contracts.
            underlying_price: Current price of the underlying.
            short_delta: Target delta for short strikes (default: 0.30).
            wing_width: Distance from short strikes to wing strikes.
            expiration: Optional specific expiration to filter.

        Returns:
            SelectedStrikes with all 4 legs.

        Raises:
            StrikeSelectionError: If suitable strikes cannot be found.
        """
        # Filter by expiration if specified
        if expiration:
            calls = [c for c in calls if c.get("expiration") == expiration]
            puts = [p for p in puts if p.get("expiration") == expiration]

        # Find short put by delta (OTM puts have deltas like -0.30)
        short_put = self.find_strike_by_delta(puts, short_delta, "put")
        if not short_put:
            raise StrikeSelectionError(
                f"No short put found at delta {short_delta}"
            )

        # Find short call by delta (OTM calls have deltas like +0.30)
        short_call = self.find_strike_by_delta(calls, short_delta, "call")
        if not short_call:
            raise StrikeSelectionError(
                f"No short call found at delta {short_delta}"
            )

        # Ensure short put is below short call
        if short_put["strike"] >= short_call["strike"]:
            raise StrikeSelectionError(
                f"Short put strike {short_put['strike']} must be below "
                f"short call strike {short_call['strike']}"
            )

        # Find wing strikes
        long_put = self.find_strike_at_offset(
            puts, short_put["strike"], -wing_width
        )
        if not long_put:
            raise StrikeSelectionError(
                f"No put wing found at strike {short_put['strike'] - wing_width}"
            )

        long_call = self.find_strike_at_offset(
            calls, short_call["strike"], wing_width
        )
        if not long_call:
            raise StrikeSelectionError(
                f"No call wing found at strike {short_call['strike'] + wing_width}"
            )

        selected_expiration = short_put.get("expiration", expiration or "unknown")

        return SelectedStrikes(
            long_put=long_put,
            short_put=short_put,
            short_call=short_call,
            long_call=long_call,
            underlying_price=underlying_price,
            expiration=selected_expiration,
        )
