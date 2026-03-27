"""Integration tests for IBKRToolkit against IBKR paper trading.

These tests require a running TWS or IB Gateway in paper trading mode
(port 7497). They are marked with @pytest.mark.integration and will NOT
run in normal CI — run explicitly with:

    pytest tests/tools/test_ibkr/test_integration.py -v -m integration

WARNING: These tests interact with a live paper trading account.
Orders are placed with limit prices well below market to avoid fills.
"""
import pytest
from decimal import Decimal

from parrot.tools.ibkr import IBKRConfig, IBKRToolkit, RiskConfig

pytestmark = pytest.mark.integration


@pytest.fixture
async def ibkr_toolkit():
    """Connect to IBKR paper trading and yield toolkit."""
    config = IBKRConfig(
        backend="tws",
        host="127.0.0.1",
        port=7497,
        client_id=99,
    )
    risk_config = RiskConfig(
        max_order_qty=5,
        max_order_value=Decimal("5000"),
        daily_loss_limit=Decimal("1000"),
        require_confirmation=False,
    )
    toolkit = IBKRToolkit(config=config, risk_config=risk_config)
    await toolkit.connect()
    yield toolkit
    await toolkit.disconnect()


# ── Market Data ─────────────────────────────────────────────────


class TestPaperTradingMarketData:
    @pytest.mark.asyncio
    async def test_get_quote(self, ibkr_toolkit):
        """Should return a quote with a last price for AAPL."""
        quote = await ibkr_toolkit.get_quote(symbol="AAPL")
        assert isinstance(quote, dict)
        assert quote["symbol"] == "AAPL"
        assert quote["last"] is not None

    @pytest.mark.asyncio
    async def test_get_historical_bars(self, ibkr_toolkit):
        """Should return at least one bar for a 1-day period."""
        bars = await ibkr_toolkit.get_historical_bars(
            symbol="AAPL", duration="1 D", bar_size="1 hour",
        )
        assert isinstance(bars, list)
        assert len(bars) > 0
        assert "open" in bars[0]
        assert "close" in bars[0]

    @pytest.mark.asyncio
    async def test_search_contracts(self, ibkr_toolkit):
        """Should find AAPL when searching."""
        results = await ibkr_toolkit.search_contracts(pattern="AAPL")
        assert isinstance(results, list)
        assert len(results) > 0
        symbols = [r.get("symbol", "") for r in results]
        assert "AAPL" in symbols


# ── Account & Portfolio ─────────────────────────────────────────


class TestPaperTradingAccount:
    @pytest.mark.asyncio
    async def test_get_account_summary(self, ibkr_toolkit):
        """Should return account summary with positive net liquidation."""
        summary = await ibkr_toolkit.get_account_summary()
        assert isinstance(summary, dict)
        assert summary["account_id"]
        assert Decimal(str(summary["net_liquidation"])) > 0

    @pytest.mark.asyncio
    async def test_get_positions(self, ibkr_toolkit):
        """Should return a list (may be empty)."""
        positions = await ibkr_toolkit.get_positions()
        assert isinstance(positions, list)

    @pytest.mark.asyncio
    async def test_get_pnl(self, ibkr_toolkit):
        """Should return a P&L dict."""
        pnl = await ibkr_toolkit.get_pnl()
        assert isinstance(pnl, dict)


# ── Order Lifecycle ─────────────────────────────────────────────


class TestPaperTradingOrderLifecycle:
    @pytest.mark.asyncio
    async def test_place_and_cancel(self, ibkr_toolkit):
        """Place a limit order well below market, then cancel it."""
        # Place a limit buy at $1.00 — will never fill
        status = await ibkr_toolkit.place_order(
            symbol="AAPL",
            action="BUY",
            quantity=1,
            order_type="LMT",
            limit_price=1.00,
            tif="DAY",
        )
        assert isinstance(status, dict)
        assert status["order_id"] > 0
        assert status["status"] in ("Submitted", "PreSubmitted")

        # Cancel it
        result = await ibkr_toolkit.cancel_order(order_id=status["order_id"])
        assert result is not None

    @pytest.mark.asyncio
    async def test_risk_blocks_large_order(self, ibkr_toolkit):
        """Risk manager should block an order exceeding max_order_qty."""
        with pytest.raises(ValueError, match="Risk check failed"):
            await ibkr_toolkit.place_order(
                symbol="AAPL",
                action="BUY",
                quantity=100,  # Exceeds max_order_qty=5
                order_type="LMT",
                limit_price=1.00,
            )

    @pytest.mark.asyncio
    async def test_get_open_orders(self, ibkr_toolkit):
        """Should return a list of open orders."""
        orders = await ibkr_toolkit.get_open_orders()
        assert isinstance(orders, list)


# ── Info ────────────────────────────────────────────────────────


class TestPaperTradingInfo:
    @pytest.mark.asyncio
    async def test_get_fundamentals(self, ibkr_toolkit):
        """Should return fundamental data for AAPL."""
        data = await ibkr_toolkit.get_fundamentals(symbol="AAPL")
        assert isinstance(data, dict)
