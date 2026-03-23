"""Pre-trade risk management for IBKR agent-driven trading.

Implements configurable guardrails that intercept order operations before
they reach the backend. All monetary comparisons use Decimal arithmetic.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Awaitable, Callable, Optional

from navconfig.logging import logging
from pydantic import BaseModel, Field

from .models import OrderRequest, Position, RiskConfig


class RiskCheckResult(BaseModel):
    """Result of a risk check."""

    passed: bool = Field(..., description="Whether the check passed.")
    reason: Optional[str] = Field(
        None, description="Explanation when the check fails."
    )
    check_name: str = Field(..., description="Name of the check that produced this result.")


class RiskManager:
    """Pre-trade risk management for IBKR orders.

    Runs configurable guardrails against incoming orders and returns
    the first failure or an all-pass result. Tracks daily P&L for
    loss-limit enforcement.

    Args:
        config: Risk configuration with thresholds.
        confirmation_callback: Optional async callback invoked before
            order execution. Must return True to approve.
    """

    def __init__(
        self,
        config: RiskConfig,
        confirmation_callback: Optional[
            Callable[[OrderRequest], Awaitable[bool]]
        ] = None,
    ) -> None:
        self.config = config
        self._confirmation_callback = confirmation_callback
        self._daily_realized_pnl: Decimal = Decimal("0")
        self._daily_unrealized_pnl: Decimal = Decimal("0")
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger("IBKRRiskManager")

    # ── Public API ────────────────────────────────────────────────

    async def validate_order(
        self,
        order: OrderRequest,
        current_positions: Optional[list[Position]] = None,
        current_price: Optional[Decimal] = None,
    ) -> RiskCheckResult:
        """Run all risk checks on an order.

        Checks are executed in order; the first failure is returned
        immediately. If all pass, the optional confirmation callback
        is invoked last.

        Args:
            order: The order to validate.
            current_positions: Current portfolio positions (for position limit check).
            current_price: Current market price of the instrument.

        Returns:
            RiskCheckResult indicating pass or first failure.
        """
        checks = [
            self._check_order_quantity(order),
            self._check_order_value(order, current_price),
            self._check_position_limit(order, current_positions, current_price),
            self._check_daily_loss(),
        ]
        for check in checks:
            if not check.passed:
                self.logger.warning(
                    "Risk check failed: %s — %s", check.check_name, check.reason
                )
                return check

        # Confirmation hook (last check)
        if self._confirmation_callback and self.config.require_confirmation:
            approved = await self._confirmation_callback(order)
            if not approved:
                return RiskCheckResult(
                    passed=False,
                    reason="Order rejected by confirmation hook",
                    check_name="confirmation",
                )

        return RiskCheckResult(passed=True, check_name="all_checks")

    def update_pnl(
        self,
        realized: Decimal = Decimal("0"),
        unrealized: Decimal = Decimal("0"),
    ) -> None:
        """Update daily P&L tracking.

        Args:
            realized: Realized P&L delta to add.
            unrealized: New unrealized P&L snapshot (replaces previous).
        """
        self._daily_realized_pnl += realized
        self._daily_unrealized_pnl = unrealized

    def reset_daily_pnl(self) -> None:
        """Reset daily P&L counters (call at start of trading day)."""
        self._daily_realized_pnl = Decimal("0")
        self._daily_unrealized_pnl = Decimal("0")
        self.logger.info("Daily P&L counters reset.")

    # ── Private check methods ─────────────────────────────────────

    def _check_order_quantity(self, order: OrderRequest) -> RiskCheckResult:
        """Check that order quantity does not exceed max_order_qty."""
        if order.quantity > self.config.max_order_qty:
            return RiskCheckResult(
                passed=False,
                reason=(
                    f"Order quantity {order.quantity} exceeds maximum "
                    f"{self.config.max_order_qty}"
                ),
                check_name="max_order_quantity",
            )
        return RiskCheckResult(passed=True, check_name="max_order_quantity")

    def _check_order_value(
        self,
        order: OrderRequest,
        current_price: Optional[Decimal] = None,
    ) -> RiskCheckResult:
        """Check that order notional value does not exceed max_order_value."""
        price = self._effective_price(order, current_price)
        if price is None:
            # Cannot compute value without price — pass the check
            return RiskCheckResult(passed=True, check_name="max_order_value")

        order_value = Decimal(str(order.quantity)) * price
        if order_value > self.config.max_order_value:
            return RiskCheckResult(
                passed=False,
                reason=(
                    f"Order value {order_value} exceeds maximum "
                    f"{self.config.max_order_value}"
                ),
                check_name="max_order_value",
            )
        return RiskCheckResult(passed=True, check_name="max_order_value")

    def _check_position_limit(
        self,
        order: OrderRequest,
        current_positions: Optional[list[Position]] = None,
        current_price: Optional[Decimal] = None,
    ) -> RiskCheckResult:
        """Check that the order would not push position value beyond limit."""
        price = self._effective_price(order, current_price)
        if price is None:
            return RiskCheckResult(passed=True, check_name="max_position_value")

        # Compute existing position value for this symbol
        existing_value = Decimal("0")
        if current_positions:
            for pos in current_positions:
                if pos.symbol.upper() == order.symbol.upper():
                    if pos.market_value is not None:
                        existing_value += abs(pos.market_value)

        # New order contribution
        new_order_value = Decimal(str(order.quantity)) * price
        total_position_value = existing_value + new_order_value

        if total_position_value > self.config.max_position_value:
            return RiskCheckResult(
                passed=False,
                reason=(
                    f"Total position value {total_position_value} would exceed "
                    f"maximum {self.config.max_position_value}"
                ),
                check_name="max_position_value",
            )
        return RiskCheckResult(passed=True, check_name="max_position_value")

    def _check_daily_loss(self) -> RiskCheckResult:
        """Check that cumulative daily loss has not exceeded threshold."""
        total_loss = self._daily_realized_pnl + self._daily_unrealized_pnl
        # Loss is negative; limit is a positive threshold
        if total_loss < Decimal("0") and abs(total_loss) > self.config.daily_loss_limit:
            return RiskCheckResult(
                passed=False,
                reason=(
                    f"Daily loss {total_loss} exceeds limit "
                    f"-{self.config.daily_loss_limit}"
                ),
                check_name="daily_loss_limit",
            )
        return RiskCheckResult(passed=True, check_name="daily_loss_limit")

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _effective_price(
        order: OrderRequest,
        current_price: Optional[Decimal] = None,
    ) -> Optional[Decimal]:
        """Determine the best available price for value calculations.

        Prefers limit_price from the order, falls back to current_price.
        """
        if order.limit_price is not None:
            return order.limit_price
        return current_price
