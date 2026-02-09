"""
Tests for the Anti-Hallucination Deterministic Guard Architecture.

Covers:
    - ExecutionMandate creation
    - DeterministicGuard validation (symbol, side, qty, price, value, cash,
      daily limits, tool auth, extra orders, companion orders, halt)
    - Post-execution reconciliation
    - SafeToolWrapper integration
    - wrap_tools_with_guards factory
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from parrot.finance.guards import (
    CRITICAL_VIOLATIONS,
    DeterministicGuard,
    ExecutionAuditEntry,
    ExecutionMandate,
    GuardResult,
    GuardViolation,
    SafeToolWrapper,
    ViolationType,
    create_mandate_from_order,
    wrap_tools_with_guards,
)
from parrot.tools.abstract import AbstractTool, ToolResult


# =============================================================================
# FIXTURES — lightweight fakes (no network, no LLM)
# =============================================================================

@dataclass
class FakeTradingOrder:
    """Minimal stand-in for TradingOrder."""
    id: str = "order-001"
    asset: str = "AAPL"
    action: str = "BUY"
    order_type: str = "limit"
    quantity: float | None = 10.0
    sizing_pct: float = 2.0
    limit_price: float | None = 150.0
    stop_price: float | None = None
    stop_loss: float | None = 145.0
    take_profit: float | None = 160.0


@dataclass
class FakePortfolioSnapshot:
    """Minimal stand-in for PortfolioSnapshot."""
    total_value_usd: float = 25_000.0
    cash_available_usd: float = 8_000.0
    daily_trades_executed: int = 2
    daily_volume_usd: float = 500.0


@dataclass
class FakeConstraints:
    """Minimal stand-in for ExecutorConstraints."""
    max_order_pct: float = 2.0
    max_order_value_usd: float = 500.0
    max_daily_trades: int = 10
    max_daily_volume_usd: float = 2_000.0


class FakeTool(AbstractTool):
    """Concrete AbstractTool for testing — returns params as result."""

    name = "alpaca_place_order"
    description = "Place a stock order via Alpaca."

    def __init__(self, tool_name: str = "alpaca_place_order") -> None:
        self.name = tool_name
        self.description = f"Fake tool: {tool_name}"
        self.args_schema = None
        self.return_direct = False
        self._init_kwargs = {}
        self.logger = __import__("logging").getLogger(f"FakeTool.{tool_name}")

    async def _execute(self, **kwargs) -> Any:
        return {"executed": True, **kwargs}

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "side": {"type": "string"},
                    "qty": {"type": "number"},
                    "price": {"type": "number"},
                },
                "required": ["symbol", "side", "qty"],
                "additionalProperties": False,
            },
        }

    def validate_args(self, **kwargs):
        return type("Obj", (), kwargs)()


def _default_mandate(**overrides) -> ExecutionMandate:
    """Build a standard mandate for tests, with optional overrides."""
    defaults = dict(
        order_id="order-001",
        symbol="AAPL",
        side="buy",
        max_quantity=10.0,
        min_quantity=0.0,
        limit_price=150.0,
        price_band_pct=2.0,
        max_value_usd=2_000.0,
        available_cash_usd=8_000.0,
        daily_trades_remaining=8,
        daily_volume_remaining_usd=5_000.0,
        allowed_tools=frozenset({
            "alpaca_place_order",
            "alpaca_get_quote",
            "alpaca_get_account",
            "alpaca_cancel_order",
            "set_stop_loss",
            "set_take_profit",
        }),
        max_place_order_calls=1,
        stop_loss=145.0,
        take_profit=160.0,
    )
    defaults.update(overrides)
    return ExecutionMandate(**defaults)


def _guard(**mandate_kw) -> DeterministicGuard:
    return DeterministicGuard(mandate=_default_mandate(**mandate_kw))


# =============================================================================
# 1. EXECUTION MANDATE CREATION
# =============================================================================

class TestExecutionMandate:
    """Tests for create_mandate_from_order()."""

    def test_basic_creation(self):
        order = FakeTradingOrder()
        portfolio = FakePortfolioSnapshot()
        constraints = FakeConstraints()

        mandate = create_mandate_from_order(
            order=order,
            portfolio=portfolio,
            constraints=constraints,
            allowed_tools={"alpaca_place_order", "alpaca_get_quote"},
        )

        assert mandate.order_id == "order-001"
        assert mandate.symbol == "AAPL"
        assert mandate.side == "buy"
        assert mandate.limit_price == 150.0
        assert mandate.stop_loss == 145.0
        assert mandate.take_profit == 160.0
        assert mandate.max_place_order_calls == 1

    def test_max_value_capped_by_constraint(self):
        """sizing_pct * portfolio = $500, constraint cap = $500 → $500."""
        order = FakeTradingOrder(sizing_pct=2.0)
        portfolio = FakePortfolioSnapshot(total_value_usd=25_000.0)
        constraints = FakeConstraints(max_order_value_usd=500.0)

        mandate = create_mandate_from_order(order, portfolio, constraints)
        assert mandate.max_value_usd == 500.0

    def test_max_value_capped_by_sizing(self):
        """sizing_pct * portfolio = $250 < constraint cap $500 → $250."""
        order = FakeTradingOrder(sizing_pct=1.0)
        portfolio = FakePortfolioSnapshot(total_value_usd=25_000.0)
        constraints = FakeConstraints(max_order_value_usd=500.0)

        mandate = create_mandate_from_order(order, portfolio, constraints)
        assert mandate.max_value_usd == 250.0

    def test_daily_trades_remaining(self):
        portfolio = FakePortfolioSnapshot(daily_trades_executed=7)
        constraints = FakeConstraints(max_daily_trades=10)

        mandate = create_mandate_from_order(
            FakeTradingOrder(), portfolio, constraints,
        )
        assert mandate.daily_trades_remaining == 3

    def test_daily_volume_remaining(self):
        portfolio = FakePortfolioSnapshot(daily_volume_usd=1200.0)
        constraints = FakeConstraints(max_daily_volume_usd=2000.0)

        mandate = create_mandate_from_order(
            FakeTradingOrder(), portfolio, constraints,
        )
        assert mandate.daily_volume_remaining_usd == 800.0

    def test_immutability(self):
        mandate = _default_mandate()
        with pytest.raises(AttributeError):
            mandate.symbol = "MSFT"

    def test_allowed_tools_frozen(self):
        mandate = _default_mandate()
        assert isinstance(mandate.allowed_tools, frozenset)


# =============================================================================
# 2. SYMBOL VALIDATION
# =============================================================================

class TestDeterministicGuardSymbol:

    def test_correct_symbol_passes(self):
        guard = _guard()
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert result.allowed

    def test_wrong_symbol_blocked(self):
        guard = _guard()
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "TSLA", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert not result.allowed
        assert result.has_critical
        assert any(
            v.violation_type == ViolationType.SYMBOL_MISMATCH
            for v in result.violations
        )

    def test_case_insensitive_match(self):
        guard = _guard()
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "aapl", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert result.allowed


# =============================================================================
# 3. SIDE VALIDATION
# =============================================================================

class TestDeterministicGuardSide:

    def test_correct_side_passes(self):
        guard = _guard(side="buy")
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert result.allowed

    def test_wrong_side_blocked(self):
        guard = _guard(side="buy")
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "sell", "qty": 5, "price": 150.0},
        )
        assert not result.allowed
        assert any(
            v.violation_type == ViolationType.SIDE_MISMATCH
            for v in result.violations
        )


# =============================================================================
# 4. QUANTITY VALIDATION
# =============================================================================

class TestDeterministicGuardQuantity:

    def test_within_limit_passes(self):
        guard = _guard(max_quantity=10.0)
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 8, "price": 150.0},
        )
        assert result.allowed
        assert not result.violations

    def test_slight_overage_auto_corrected(self):
        """≤5% overage: auto-correct, non-critical."""
        guard = _guard(max_quantity=10.0)
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 10.4, "price": 150.0},
        )
        assert result.allowed
        assert result.corrected_params is not None
        assert result.corrected_params["qty"] == 10.0
        assert any(
            v.violation_type == ViolationType.QUANTITY_EXCEEDED
            and v.corrected_to == 10.0
            for v in result.violations
        )

    def test_large_overage_blocked(self):
        """>5% overage: critical, blocked."""
        guard = _guard(max_quantity=10.0)
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 20, "price": 150.0},
        )
        assert not result.allowed
        assert any(
            v.violation_type == ViolationType.QUANTITY_EXCEEDED and v.is_critical
            for v in result.violations
        )


# =============================================================================
# 5. PRICE VALIDATION
# =============================================================================

class TestDeterministicGuardPrice:

    def test_price_within_band(self):
        guard = _guard(limit_price=150.0, price_band_pct=2.0)
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 151.0},
        )
        assert result.allowed

    def test_price_out_of_band_warns(self):
        """Outside the 2% band — non-critical warning."""
        guard = _guard(limit_price=150.0, price_band_pct=2.0)
        # Band: [147, 153]. 155 is outside.
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 155.0},
        )
        assert any(
            v.violation_type == ViolationType.PRICE_OUT_OF_BAND
            for v in result.violations
        )

    def test_negative_price_blocked(self):
        guard = _guard()
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": -10.0},
        )
        assert not result.allowed
        assert any(
            v.violation_type == ViolationType.HALLUCINATED_PRICE
            for v in result.violations
        )

    def test_zero_price_blocked(self):
        guard = _guard()
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 0},
        )
        assert not result.allowed


# =============================================================================
# 6. VALUE + CASH CHECKS
# =============================================================================

class TestDeterministicGuardValueCash:

    def test_value_within_limit(self):
        guard = _guard(max_value_usd=1000.0, available_cash_usd=5000.0)
        # 5 * 150 = 750 < 1000
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert result.allowed

    def test_value_exceeds_max(self):
        guard = _guard(max_value_usd=500.0)
        # 5 * 150 = 750 > 500
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert not result.allowed
        assert any(
            v.violation_type == ViolationType.MAX_VALUE_EXCEEDED
            for v in result.violations
        )

    def test_insufficient_cash(self):
        guard = _guard(
            max_value_usd=50_000.0,
            available_cash_usd=100.0,
            side="buy",
        )
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert not result.allowed
        assert any(
            v.violation_type == ViolationType.INSUFFICIENT_CASH
            for v in result.violations
        )

    def test_insufficient_cash_not_checked_for_sells(self):
        guard = _guard(
            max_value_usd=50_000.0,
            available_cash_usd=1.0,
            side="sell",
        )
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "sell", "qty": 5, "price": 150.0},
        )
        # No cash check for sells
        assert not any(
            v.violation_type == ViolationType.INSUFFICIENT_CASH
            for v in result.violations
        )


# =============================================================================
# 7. DAILY LIMITS
# =============================================================================

class TestDeterministicGuardDailyLimits:

    def test_daily_trade_limit_exhausted(self):
        guard = _guard(daily_trades_remaining=0)
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 1, "price": 150.0},
        )
        assert not result.allowed
        assert any(
            v.violation_type == ViolationType.DAILY_TRADE_LIMIT
            for v in result.violations
        )

    def test_daily_volume_exceeded(self):
        guard = _guard(daily_volume_remaining_usd=100.0, max_value_usd=50_000.0)
        # 5 * 150 = 750 > 100
        result = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert not result.allowed
        assert any(
            v.violation_type == ViolationType.DAILY_VOLUME_LIMIT
            for v in result.violations
        )


# =============================================================================
# 8. TOOL AUTHORIZATION
# =============================================================================

class TestDeterministicGuardToolAuth:

    def test_authorized_tool_passes(self):
        guard = _guard()
        result = guard.validate_tool_call(
            "alpaca_get_quote",
            {"symbol": "AAPL"},
        )
        assert result.allowed

    def test_unauthorized_tool_blocked(self):
        guard = _guard()
        result = guard.validate_tool_call(
            "binance_place_order",
            {"symbol": "BTC/USDT", "side": "buy", "qty": 1},
        )
        assert not result.allowed
        assert any(
            v.violation_type == ViolationType.UNAUTHORIZED_TOOL
            for v in result.violations
        )

    def test_extra_order_blocked(self):
        """Second place_order call is blocked."""
        guard = _guard(max_place_order_calls=1)
        # First call succeeds
        r1 = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert r1.allowed

        # Second call blocked
        r2 = guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert not r2.allowed
        assert any(
            v.violation_type == ViolationType.EXTRA_ORDER
            for v in r2.violations
        )


# =============================================================================
# 9. COMPANION ORDERS
# =============================================================================

class TestDeterministicGuardCompanion:

    def test_valid_stop_loss(self):
        guard = _guard(stop_loss=145.0)
        result = guard.validate_tool_call(
            "set_stop_loss",
            {"symbol": "AAPL", "stop_price": 145.0},
        )
        assert result.allowed

    def test_stop_loss_symbol_mismatch(self):
        guard = _guard(stop_loss=145.0)
        result = guard.validate_tool_call(
            "set_stop_loss",
            {"symbol": "TSLA", "stop_price": 145.0},
        )
        assert not result.allowed
        assert any(
            v.violation_type == ViolationType.INVALID_COMPANION_ORDER
            for v in result.violations
        )

    def test_stop_loss_large_deviation_warns(self):
        guard = _guard(stop_loss=145.0)
        # 120 deviates >10% from 145
        result = guard.validate_tool_call(
            "set_stop_loss",
            {"symbol": "AAPL", "stop_price": 120.0},
        )
        assert any(
            v.violation_type == ViolationType.INVALID_COMPANION_ORDER
            for v in result.violations
        )

    def test_negative_stop_loss_blocked(self):
        guard = _guard()
        result = guard.validate_tool_call(
            "set_stop_loss",
            {"symbol": "AAPL", "stop_price": -5.0},
        )
        assert not result.allowed


# =============================================================================
# 10. EMERGENCY HALT
# =============================================================================

class TestDeterministicGuardHalt:

    def test_halt_blocks_everything(self):
        guard = _guard()
        guard.halt()

        result = guard.validate_tool_call(
            "alpaca_get_quote",
            {"symbol": "AAPL"},
        )
        assert not result.allowed
        assert any(
            v.violation_type == ViolationType.EMERGENCY_HALT
            for v in result.violations
        )

    def test_read_tool_blocked_after_halt(self):
        guard = _guard()
        guard.halt()

        result = guard.validate_tool_call(
            "alpaca_get_account",
            {},
        )
        assert not result.allowed


# =============================================================================
# 11. POST-EXECUTION RECONCILIATION
# =============================================================================

class TestReconcileExecution:

    def test_perfect_fill_passes(self):
        guard = _guard()
        result = guard.reconcile_execution(
            requested_symbol="AAPL",
            requested_side="buy",
            requested_qty=10.0,
            requested_price=150.0,
            filled_symbol="AAPL",
            filled_side="buy",
            filled_qty=10.0,
            filled_price=150.0,
        )
        assert result.allowed
        assert not result.violations

    def test_symbol_mismatch_is_critical(self):
        guard = _guard()
        result = guard.reconcile_execution(
            requested_symbol="AAPL",
            requested_side="buy",
            requested_qty=10.0,
            requested_price=150.0,
            filled_symbol="TSLA",
            filled_side="buy",
            filled_qty=10.0,
            filled_price=150.0,
        )
        assert not result.allowed
        assert result.has_critical

    def test_side_mismatch_is_critical(self):
        guard = _guard()
        result = guard.reconcile_execution(
            requested_symbol="AAPL",
            requested_side="buy",
            requested_qty=10.0,
            requested_price=150.0,
            filled_symbol="AAPL",
            filled_side="sell",
            filled_qty=10.0,
            filled_price=150.0,
        )
        assert not result.allowed

    def test_small_qty_deviation_passes(self):
        guard = _guard()
        result = guard.reconcile_execution(
            requested_symbol="AAPL",
            requested_side="buy",
            requested_qty=10.0,
            requested_price=150.0,
            filled_symbol="AAPL",
            filled_side="buy",
            filled_qty=9.5,  # 5% deviation
            filled_price=150.0,
        )
        assert result.allowed

    def test_large_qty_deviation_warns(self):
        guard = _guard()
        result = guard.reconcile_execution(
            requested_symbol="AAPL",
            requested_side="buy",
            requested_qty=10.0,
            requested_price=150.0,
            filled_symbol="AAPL",
            filled_side="buy",
            filled_qty=5.0,  # 50% deviation
            filled_price=150.0,
        )
        # Non-critical but flagged
        assert result.allowed
        assert any(
            v.violation_type == ViolationType.EXECUTION_MISMATCH
            for v in result.violations
        )

    def test_high_slippage_warns(self):
        guard = _guard()
        result = guard.reconcile_execution(
            requested_symbol="AAPL",
            requested_side="buy",
            requested_qty=10.0,
            requested_price=150.0,
            filled_symbol="AAPL",
            filled_side="buy",
            filled_qty=10.0,
            filled_price=165.0,  # 10% slippage
        )
        assert any(
            v.violation_type == ViolationType.EXECUTION_MISMATCH
            for v in result.violations
        )

    def test_none_fill_fields_ignored(self):
        """Reconciliation tolerates None for optional filled fields."""
        guard = _guard()
        result = guard.reconcile_execution(
            requested_symbol="AAPL",
            requested_side="buy",
            requested_qty=10.0,
            requested_price=150.0,
            filled_symbol=None,
            filled_side=None,
            filled_qty=None,
            filled_price=None,
        )
        assert result.allowed
        assert not result.violations


# =============================================================================
# 12. SAFE TOOL WRAPPER
# =============================================================================

class TestSafeToolWrapper:

    @pytest.fixture
    def setup(self):
        tool = FakeTool("alpaca_place_order")
        guard = _guard()
        wrapper = SafeToolWrapper(wrapped_tool=tool, guard=guard)
        return tool, guard, wrapper

    def test_wrapper_identity(self, setup):
        tool, _, wrapper = setup
        assert wrapper.name == tool.name
        assert wrapper.description == tool.description

    def test_wrapper_schema(self, setup):
        tool, _, wrapper = setup
        assert wrapper.get_schema() == tool.get_schema()

    @pytest.mark.asyncio
    async def test_valid_call_passes_through(self, setup):
        _, _, wrapper = setup
        result = await wrapper.execute(
            symbol="AAPL", side="buy", qty=5, price=150.0,
        )
        assert result.status == "success"
        assert result.result["executed"] is True

    @pytest.mark.asyncio
    async def test_invalid_call_blocked(self, setup):
        _, _, wrapper = setup
        result = await wrapper.execute(
            symbol="TSLA", side="buy", qty=5, price=150.0,
        )
        assert result.status == "blocked_by_guard"
        assert result.success is False
        assert "BLOCKED" in result.error

    @pytest.mark.asyncio
    async def test_auto_corrected_params(self, setup):
        _, _, wrapper = setup
        # qty=10.4 is ≤5% over max_quantity=10.0 → auto-correct to 10.0
        result = await wrapper.execute(
            symbol="AAPL", side="buy", qty=10.4, price=150.0,
        )
        assert result.status == "success"
        assert result.result["qty"] == 10.0

    @pytest.mark.asyncio
    async def test_read_only_tool_always_passes(self):
        tool = FakeTool("alpaca_get_quote")
        guard = _guard()
        wrapper = SafeToolWrapper(wrapped_tool=tool, guard=guard)

        result = await wrapper.execute(symbol="AAPL")
        assert result.status == "success"


# =============================================================================
# 13. WRAP TOOLS FACTORY
# =============================================================================

class TestWrapToolsFactory:

    def test_wraps_all_abstract_tools(self):
        tools = [
            FakeTool("alpaca_place_order"),
            FakeTool("alpaca_get_quote"),
            FakeTool("alpaca_cancel_order"),
        ]
        guard = _guard()
        wrapped = wrap_tools_with_guards(tools, guard)

        assert len(wrapped) == 3
        assert all(isinstance(w, SafeToolWrapper) for w in wrapped)
        names = {w.name for w in wrapped}
        assert names == {"alpaca_place_order", "alpaca_get_quote", "alpaca_cancel_order"}

    def test_preserves_schema(self):
        tool = FakeTool("alpaca_place_order")
        guard = _guard()
        wrapped = wrap_tools_with_guards([tool], guard)

        assert wrapped[0].get_schema() == tool.get_schema()


# =============================================================================
# 14. GUARD RESULT SUMMARY
# =============================================================================

class TestGuardResultSummary:

    def test_pass_summary(self):
        r = GuardResult(allowed=True)
        assert r.summary() == "PASS: all checks passed"

    def test_blocked_summary(self):
        v = GuardViolation(
            violation_type=ViolationType.SYMBOL_MISMATCH,
            message="Symbol 'TSLA' != mandated 'AAPL'",
            is_critical=True,
        )
        r = GuardResult(allowed=False, violations=[v])
        assert "BLOCKED" in r.summary()

    def test_warn_summary(self):
        v = GuardViolation(
            violation_type=ViolationType.PRICE_OUT_OF_BAND,
            message="Price outside band",
            is_critical=False,
        )
        r = GuardResult(allowed=True, violations=[v])
        assert "WARN" in r.summary()


# =============================================================================
# 15. VIOLATION TAXONOMY
# =============================================================================

class TestViolationTaxonomy:

    def test_critical_violations_are_defined(self):
        assert ViolationType.SYMBOL_MISMATCH in CRITICAL_VIOLATIONS
        assert ViolationType.SIDE_MISMATCH in CRITICAL_VIOLATIONS
        assert ViolationType.UNAUTHORIZED_TOOL in CRITICAL_VIOLATIONS
        assert ViolationType.EXTRA_ORDER in CRITICAL_VIOLATIONS
        assert ViolationType.HALLUCINATED_PRICE in CRITICAL_VIOLATIONS
        assert ViolationType.EMERGENCY_HALT in CRITICAL_VIOLATIONS

    def test_non_critical_not_in_set(self):
        assert ViolationType.PRICE_OUT_OF_BAND not in CRITICAL_VIOLATIONS
        assert ViolationType.QUANTITY_EXCEEDED not in CRITICAL_VIOLATIONS


# =============================================================================
# 16. AUDIT ENTRY
# =============================================================================

class TestAuditEntry:

    def test_from_guard(self):
        guard = _guard()
        guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 150.0},
        )

        audit = ExecutionAuditEntry.from_guard(
            guard, blocked=False, reconciliation_passed=True,
        )
        assert audit.order_id == "order-001"
        assert audit.execution_blocked is False
        assert audit.reconciliation_passed is True
        assert audit.tool_calls_intercepted == 1
        assert isinstance(audit.violations, list)

    def test_audit_captures_violations(self):
        guard = _guard()
        guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "TSLA", "side": "buy", "qty": 5, "price": 150.0},
        )

        audit = ExecutionAuditEntry.from_guard(guard, blocked=True)
        assert audit.execution_blocked is True
        assert len(audit.violations) > 0
        assert audit.violations[0]["type"] == "symbol_mismatch"


# =============================================================================
# 17. READ-ONLY TOOL DETECTION
# =============================================================================

class TestReadOnlyDetection:

    @pytest.mark.parametrize("name", [
        "alpaca_get_account",
        "alpaca_get_positions",
        "alpaca_get_quote",
        "binance_get_account",
        "binance_get_ticker",
    ])
    def test_read_tools_pass_without_validation(self, name):
        guard = _guard(allowed_tools=frozenset({name}))
        result = guard.validate_tool_call(name, {"symbol": "ANYTHING"})
        assert result.allowed
        assert not result.violations

    def test_cancel_tool_passes(self):
        guard = _guard(allowed_tools=frozenset({"alpaca_cancel_order"}))
        result = guard.validate_tool_call(
            "alpaca_cancel_order", {"order_id": "abc123"},
        )
        assert result.allowed


# =============================================================================
# 18. GUARD ACCUMULATES VIOLATIONS
# =============================================================================

class TestGuardAccumulation:

    def test_violations_accumulate_across_calls(self):
        guard = _guard()
        # Read-only call — no violations
        guard.validate_tool_call("alpaca_get_quote", {"symbol": "AAPL"})
        assert len(guard.violations) == 0

        # Valid order — no violations
        guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert len(guard.violations) == 0

        # Extra order — 1 violation
        guard.validate_tool_call(
            "alpaca_place_order",
            {"symbol": "AAPL", "side": "buy", "qty": 5, "price": 150.0},
        )
        assert len(guard.violations) == 1
        assert guard.violations[0].violation_type == ViolationType.EXTRA_ORDER
