"""Options strategy factory for building multi-leg configurations.

This module provides pure functions for constructing options strategy
leg configurations without making any API calls. The factory methods
return lists of StrategyLeg objects that can be used by the toolkit
to place actual orders.

Usage:
    from parrot.finance.tools.options_strategies import StrategyFactory

    # Iron Butterfly at ATM $100 with $5 wings
    legs = StrategyFactory.iron_butterfly(100.0, wing_width=5.0)

    # Iron Condor with short put at $95, short call at $105, $5 wings
    legs = StrategyFactory.iron_condor(95.0, 105.0, wing_width=5.0)
"""
from __future__ import annotations

from typing import List

from ..schemas import StrategyLeg


class StrategyFactoryError(ValueError):
    """Raised when strategy construction fails due to invalid parameters."""


class StrategyFactory:
    """Factory for building options strategy leg configurations.

    All methods are static and pure — they perform no I/O and have no
    side effects. Each method returns exactly 4 legs representing a
    complete options spread.

    Strike Rounding:
        Strikes are rounded to standard increments:
        - Stocks: $1 increments
        - Indices (SPX, NDX, RUT): $5 increments

    Strategy Structures:

        Iron Butterfly (ATM @ $100, wing=$5):
            Long Put  $95   (buy)
            Short Put $100  (sell)
            Short Call $100 (sell)
            Long Call $105  (buy)

        Iron Condor (short put $95, short call $105, wing=$5):
            Long Put  $90   (buy)
            Short Put $95   (sell)
            Short Call $105 (sell)
            Long Call $110  (buy)
    """

    @staticmethod
    def round_strike(strike: float, increment: float = 1.0) -> float:
        """Round strike to standard price increment.

        Args:
            strike: Raw strike price.
            increment: Strike increment (1.0 for stocks, 5.0 for indices).

        Returns:
            Strike rounded to nearest increment.
        """
        return round(strike / increment) * increment

    @staticmethod
    def iron_butterfly(
        underlying_price: float,
        wing_width: float = 5.0,
        strike_increment: float = 1.0,
    ) -> List[StrategyLeg]:
        """Build a 4-leg Iron Butterfly strategy.

        An Iron Butterfly is a neutral strategy with:
        - Short straddle at ATM (sell put + sell call at same strike)
        - Long strangle wings (buy put below, buy call above)

        Maximum profit occurs when underlying closes exactly at short strike.
        Maximum loss is limited to wing_width minus net credit received.

        Args:
            underlying_price: Current price of the underlying asset.
            wing_width: Distance from short strike to long strikes.
            strike_increment: Strike price increment for rounding.

        Returns:
            List of 4 StrategyLeg objects:
            [long_put, short_put, short_call, long_call]

        Raises:
            StrategyFactoryError: If wing_width <= 0.
        """
        if wing_width <= 0:
            raise StrategyFactoryError(
                f"wing_width must be positive, got {wing_width}"
            )

        # ATM strike is rounded underlying price
        atm_strike = StrategyFactory.round_strike(
            underlying_price, strike_increment
        )

        # Calculate wing strikes
        put_wing = atm_strike - wing_width
        call_wing = atm_strike + wing_width

        # Validate strike ordering
        if put_wing >= atm_strike or atm_strike >= call_wing:
            raise StrategyFactoryError(
                f"Invalid strike ordering: {put_wing} < {atm_strike} < {call_wing}"
            )

        return [
            StrategyLeg(
                contract_type="put",
                strike=put_wing,
                side="buy",
                ratio=1,
            ),
            StrategyLeg(
                contract_type="put",
                strike=atm_strike,
                side="sell",
                ratio=1,
            ),
            StrategyLeg(
                contract_type="call",
                strike=atm_strike,
                side="sell",
                ratio=1,
            ),
            StrategyLeg(
                contract_type="call",
                strike=call_wing,
                side="buy",
                ratio=1,
            ),
        ]

    @staticmethod
    def iron_condor(
        short_put_strike: float,
        short_call_strike: float,
        wing_width: float = 5.0,
        strike_increment: float = 1.0,
    ) -> List[StrategyLeg]:
        """Build a 4-leg Iron Condor strategy.

        An Iron Condor is a neutral strategy with:
        - Short strangle (sell OTM put + sell OTM call)
        - Long strangle wings (buy further OTM put + call)

        Maximum profit occurs when underlying closes between short strikes.
        Maximum loss is limited to wing_width minus net credit received.

        Args:
            short_put_strike: Strike price for the short put leg.
            short_call_strike: Strike price for the short call leg.
            wing_width: Distance from short strikes to long strikes.
            strike_increment: Strike price increment for rounding.

        Returns:
            List of 4 StrategyLeg objects:
            [long_put, short_put, short_call, long_call]

        Raises:
            StrategyFactoryError: If wing_width <= 0 or strikes are invalid.
        """
        if wing_width <= 0:
            raise StrategyFactoryError(
                f"wing_width must be positive, got {wing_width}"
            )

        # Round short strikes
        short_put = StrategyFactory.round_strike(
            short_put_strike, strike_increment
        )
        short_call = StrategyFactory.round_strike(
            short_call_strike, strike_increment
        )

        # Short put must be below short call
        if short_put >= short_call:
            raise StrategyFactoryError(
                f"short_put_strike ({short_put}) must be < "
                f"short_call_strike ({short_call})"
            )

        # Calculate wing strikes
        long_put = short_put - wing_width
        long_call = short_call + wing_width

        # Validate full strike ordering
        if not (long_put < short_put < short_call < long_call):
            raise StrategyFactoryError(
                f"Invalid strike ordering: {long_put} < {short_put} < "
                f"{short_call} < {long_call}"
            )

        return [
            StrategyLeg(
                contract_type="put",
                strike=long_put,
                side="buy",
                ratio=1,
            ),
            StrategyLeg(
                contract_type="put",
                strike=short_put,
                side="sell",
                ratio=1,
            ),
            StrategyLeg(
                contract_type="call",
                strike=short_call,
                side="sell",
                ratio=1,
            ),
            StrategyLeg(
                contract_type="call",
                strike=long_call,
                side="buy",
                ratio=1,
            ),
        ]

    @staticmethod
    def validate_legs(legs: List[StrategyLeg]) -> bool:
        """Validate that a list of strategy legs is properly ordered.

        For Iron Butterfly/Condor, validates:
        - Exactly 4 legs
        - Strike ordering: put_wing < short_put <= short_call < call_wing
        - Proper sides: wings are buy, shorts are sell

        Args:
            legs: List of StrategyLeg objects to validate.

        Returns:
            True if legs are valid.

        Raises:
            StrategyFactoryError: If validation fails.
        """
        if len(legs) != 4:
            raise StrategyFactoryError(
                f"Expected 4 legs, got {len(legs)}"
            )

        # Extract legs by position
        long_put, short_put, short_call, long_call = legs

        # Validate contract types
        if long_put.contract_type != "put" or short_put.contract_type != "put":
            raise StrategyFactoryError("First two legs must be puts")
        if short_call.contract_type != "call" or long_call.contract_type != "call":
            raise StrategyFactoryError("Last two legs must be calls")

        # Validate sides
        if long_put.side != "buy" or long_call.side != "buy":
            raise StrategyFactoryError("Wing legs must be 'buy'")
        if short_put.side != "sell" or short_call.side != "sell":
            raise StrategyFactoryError("Short legs must be 'sell'")

        # Validate strike ordering
        if not (long_put.strike < short_put.strike <= short_call.strike < long_call.strike):
            raise StrategyFactoryError(
                f"Invalid strike ordering: {long_put.strike} < {short_put.strike} "
                f"<= {short_call.strike} < {long_call.strike}"
            )

        return True
