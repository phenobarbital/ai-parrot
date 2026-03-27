"""Unit tests for IBKR Risk Manager guardrails."""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock

from parrot.tools.ibkr.models import RiskConfig, OrderRequest, Position
from parrot.tools.ibkr.risk import RiskManager, RiskCheckResult


@pytest.fixture
def strict_config():
    return RiskConfig(
        max_order_qty=10,
        max_order_value=Decimal("5000"),
        max_position_value=Decimal("20000"),
        daily_loss_limit=Decimal("1000"),
        require_confirmation=False,
    )


@pytest.fixture
def risk_manager(strict_config):
    return RiskManager(config=strict_config)


class TestRiskCheckResult:
    def test_pass_result(self):
        result = RiskCheckResult(passed=True, check_name="test")
        assert result.passed
        assert result.reason is None

    def test_fail_result(self):
        result = RiskCheckResult(
            passed=False, reason="exceeded limit", check_name="test"
        )
        assert not result.passed
        assert result.reason == "exceeded limit"


class TestOrderQuantityCheck:
    @pytest.mark.asyncio
    async def test_within_limit(self, risk_manager):
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=5)
        result = await risk_manager.validate_order(order)
        assert result.passed

    @pytest.mark.asyncio
    async def test_at_limit(self, risk_manager):
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=10)
        result = await risk_manager.validate_order(order)
        assert result.passed

    @pytest.mark.asyncio
    async def test_exceeds_limit(self, risk_manager):
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=50)
        result = await risk_manager.validate_order(order)
        assert not result.passed
        assert "quantity" in result.reason.lower()


class TestOrderValueCheck:
    @pytest.mark.asyncio
    async def test_within_limit(self, risk_manager):
        order = OrderRequest(
            symbol="AAPL", action="BUY", quantity=5,
            limit_price=Decimal("150.00"),
        )
        result = await risk_manager.validate_order(
            order, current_price=Decimal("150.00")
        )
        assert result.passed

    @pytest.mark.asyncio
    async def test_exceeds_limit(self, risk_manager):
        order = OrderRequest(
            symbol="AAPL", action="BUY", quantity=10,
            limit_price=Decimal("600.00"),
        )
        result = await risk_manager.validate_order(
            order, current_price=Decimal("600.00")
        )
        assert not result.passed
        assert "value" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_uses_current_price_when_no_limit(self, risk_manager):
        order = OrderRequest(
            symbol="AAPL", action="BUY", quantity=10, order_type="MKT",
        )
        result = await risk_manager.validate_order(
            order, current_price=Decimal("600.00")
        )
        assert not result.passed
        assert "value" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_no_price_skips_check(self, risk_manager):
        order = OrderRequest(
            symbol="AAPL", action="BUY", quantity=5, order_type="MKT",
        )
        result = await risk_manager.validate_order(order)
        assert result.passed


class TestDailyLossLimit:
    @pytest.mark.asyncio
    async def test_within_limit(self, risk_manager):
        risk_manager.update_pnl(
            realized=Decimal("-500"), unrealized=Decimal("-200")
        )
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=1)
        result = await risk_manager.validate_order(order)
        assert result.passed

    @pytest.mark.asyncio
    async def test_exceeds_limit(self, risk_manager):
        risk_manager.update_pnl(
            realized=Decimal("-800"), unrealized=Decimal("-300")
        )
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=1)
        result = await risk_manager.validate_order(order)
        assert not result.passed
        assert "daily loss" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_reset_daily_pnl(self, risk_manager):
        risk_manager.update_pnl(
            realized=Decimal("-2000"), unrealized=Decimal("0")
        )
        risk_manager.reset_daily_pnl()
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=1)
        result = await risk_manager.validate_order(order)
        assert result.passed

    @pytest.mark.asyncio
    async def test_cumulative_realized(self, risk_manager):
        risk_manager.update_pnl(realized=Decimal("-600"))
        risk_manager.update_pnl(realized=Decimal("-500"))
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=1)
        result = await risk_manager.validate_order(order)
        assert not result.passed


class TestConfirmationHook:
    @pytest.mark.asyncio
    async def test_approved(self, strict_config):
        callback = AsyncMock(return_value=True)
        strict_config.require_confirmation = True
        rm = RiskManager(config=strict_config, confirmation_callback=callback)
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=1)
        result = await rm.validate_order(order)
        assert result.passed
        callback.assert_called_once_with(order)

    @pytest.mark.asyncio
    async def test_rejected(self, strict_config):
        callback = AsyncMock(return_value=False)
        strict_config.require_confirmation = True
        rm = RiskManager(config=strict_config, confirmation_callback=callback)
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=1)
        result = await rm.validate_order(order)
        assert not result.passed
        assert "confirmation" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_no_callback_skips(self, strict_config):
        strict_config.require_confirmation = True
        rm = RiskManager(config=strict_config)
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=1)
        result = await rm.validate_order(order)
        assert result.passed

    @pytest.mark.asyncio
    async def test_callback_not_called_when_not_required(self, strict_config):
        callback = AsyncMock(return_value=True)
        strict_config.require_confirmation = False
        rm = RiskManager(config=strict_config, confirmation_callback=callback)
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=1)
        result = await rm.validate_order(order)
        assert result.passed
        callback.assert_not_called()


class TestPositionLimit:
    @pytest.mark.asyncio
    async def test_new_position_within_limit(self, risk_manager):
        order = OrderRequest(
            symbol="AAPL", action="BUY", quantity=5,
            limit_price=Decimal("150.00"),
        )
        result = await risk_manager.validate_order(
            order, current_positions=[], current_price=Decimal("150.00")
        )
        assert result.passed

    @pytest.mark.asyncio
    async def test_existing_position_exceeds_limit(self, risk_manager):
        positions = [
            Position(
                symbol="AAPL", quantity=100,
                avg_cost=Decimal("150.00"),
                market_value=Decimal("15000"),
            )
        ]
        order = OrderRequest(
            symbol="AAPL", action="BUY", quantity=10,
            limit_price=Decimal("600.00"),
        )
        result = await risk_manager.validate_order(
            order, current_positions=positions, current_price=Decimal("600.00")
        )
        assert not result.passed

    @pytest.mark.asyncio
    async def test_different_symbol_not_counted(self, risk_manager):
        positions = [
            Position(
                symbol="MSFT", quantity=100,
                avg_cost=Decimal("300.00"),
                market_value=Decimal("19000"),
            )
        ]
        order = OrderRequest(
            symbol="AAPL", action="BUY", quantity=5,
            limit_price=Decimal("150.00"),
        )
        result = await risk_manager.validate_order(
            order, current_positions=positions, current_price=Decimal("150.00")
        )
        assert result.passed

    @pytest.mark.asyncio
    async def test_no_positions_provided(self, risk_manager):
        order = OrderRequest(
            symbol="AAPL", action="BUY", quantity=5,
            limit_price=Decimal("150.00"),
        )
        result = await risk_manager.validate_order(
            order, current_price=Decimal("150.00")
        )
        assert result.passed
