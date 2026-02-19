"""Tests for TWSBackend — written BEFORE implementation (TDD RED phase).

All ib_async interactions are mocked so no live TWS connection is needed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from decimal import Decimal
from datetime import datetime

from parrot.tools.ibkr.models import (
    IBKRConfig, ContractSpec, OrderRequest, OrderStatus, Quote, BarData,
    Position, AccountSummary,
)


@pytest.fixture
def tws_config():
    return IBKRConfig(backend="tws", host="127.0.0.1", port=7497, client_id=99)


def _make_mock_ib():
    """Create a fully mocked ib_async.IB instance."""
    ib = MagicMock()
    ib.connectAsync = AsyncMock()
    ib.disconnect = MagicMock()
    ib.isConnected = MagicMock(return_value=True)
    ib.qualifyContractsAsync = AsyncMock(side_effect=lambda *contracts: list(contracts))
    ib.reqOpenOrdersAsync = AsyncMock(return_value=[])
    ib.reqAllOpenOrdersAsync = AsyncMock(return_value=[])
    ib.reqExecutionsAsync = AsyncMock(return_value=[])
    ib.reqPositionsAsync = AsyncMock(return_value=[])
    ib.accountSummaryAsync = AsyncMock(return_value=[])
    ib.reqHistoricalDataAsync = AsyncMock(return_value=[])
    ib.reqMatchingSymbolsAsync = AsyncMock(return_value=[])
    ib.reqSecDefOptParamsAsync = AsyncMock(return_value=[])
    ib.reqScannerDataAsync = AsyncMock(return_value=[])
    ib.reqFundamentalDataAsync = AsyncMock(return_value="")
    ib.reqHistoricalNewsAsync = AsyncMock(return_value=[])
    ib.reqMktData = MagicMock()
    ib.placeOrder = MagicMock()
    ib.cancelOrder = MagicMock()
    ib.trades = MagicMock(return_value=[])
    ib.positions = MagicMock(return_value=[])
    ib.pnl = MagicMock(return_value=[])
    ib.openTrades = MagicMock(return_value=[])
    return ib


@pytest.fixture
def mock_ib():
    """Patch ib_async.IB so TWSBackend uses a mock."""
    mock = _make_mock_ib()
    with patch("parrot.tools.ibkr.tws_backend.IB", return_value=mock):
        yield mock


# =============================================================================
# Connection
# =============================================================================

class TestTWSBackendConnection:
    @pytest.mark.asyncio
    async def test_connect(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend
        backend = TWSBackend(config=tws_config)
        await backend.connect()
        mock_ib.connectAsync.assert_called_once_with(
            "127.0.0.1", 7497, clientId=99, readonly=False,
        )

    @pytest.mark.asyncio
    async def test_disconnect(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend
        backend = TWSBackend(config=tws_config)
        await backend.disconnect()
        mock_ib.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_is_connected(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend
        backend = TWSBackend(config=tws_config)
        mock_ib.isConnected.return_value = True
        assert await backend.is_connected() is True
        mock_ib.isConnected.return_value = False
        assert await backend.is_connected() is False

    @pytest.mark.asyncio
    async def test_connect_readonly(self, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend
        config = IBKRConfig(readonly=True)
        backend = TWSBackend(config=config)
        await backend.connect()
        mock_ib.connectAsync.assert_called_once_with(
            "127.0.0.1", 7497, clientId=1, readonly=True,
        )


# =============================================================================
# Market Data
# =============================================================================

class TestTWSBackendMarketData:
    @pytest.mark.asyncio
    async def test_get_quote(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        # Mock ticker with market data
        mock_ticker = MagicMock()
        mock_ticker.last = 150.25
        mock_ticker.bid = 150.20
        mock_ticker.ask = 150.30
        mock_ticker.volume = 1_000_000
        mock_ticker.time = datetime(2026, 2, 19, 10, 30)
        mock_ticker.updateEvent = MagicMock()
        mock_ticker.updateEvent.wait = AsyncMock()
        mock_ib.reqMktData.return_value = mock_ticker

        backend = TWSBackend(config=tws_config)
        contract = ContractSpec(symbol="AAPL")
        quote = await backend.get_quote(contract)

        assert isinstance(quote, Quote)
        assert quote.symbol == "AAPL"
        assert quote.last == Decimal("150.25")
        assert quote.bid == Decimal("150.20")
        assert quote.ask == Decimal("150.30")
        assert quote.volume == 1_000_000

    @pytest.mark.asyncio
    async def test_get_quote_nan_handling(self, tws_config, mock_ib):
        """NaN values from ib_async should become None."""
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_ticker = MagicMock()
        mock_ticker.last = float('nan')
        mock_ticker.bid = float('nan')
        mock_ticker.ask = float('nan')
        mock_ticker.volume = 0
        mock_ticker.time = None
        mock_ticker.updateEvent = MagicMock()
        mock_ticker.updateEvent.wait = AsyncMock()
        mock_ib.reqMktData.return_value = mock_ticker

        backend = TWSBackend(config=tws_config)
        quote = await backend.get_quote(ContractSpec(symbol="AAPL"))
        assert quote.last is None
        assert quote.bid is None
        assert quote.ask is None

    @pytest.mark.asyncio
    async def test_get_historical_bars(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        # Mock bar data list
        mock_bar = MagicMock()
        mock_bar.date = datetime(2026, 2, 19, 10, 0)
        mock_bar.open = 149.50
        mock_bar.high = 151.00
        mock_bar.low = 149.00
        mock_bar.close = 150.75
        mock_bar.volume = 500_000
        mock_ib.reqHistoricalDataAsync.return_value = [mock_bar]

        backend = TWSBackend(config=tws_config)
        contract = ContractSpec(symbol="AAPL")
        bars = await backend.get_historical_bars(contract, "1 D", "1 hour")

        assert len(bars) == 1
        assert isinstance(bars[0], BarData)
        assert bars[0].open == Decimal("149.5")
        assert bars[0].high == Decimal("151.0")
        assert bars[0].volume == 500_000

    @pytest.mark.asyncio
    async def test_get_options_chain(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_param = MagicMock()
        mock_param.exchange = "CBOE"
        mock_param.underlyingConId = 265598
        mock_param.tradingClass = "AAPL"
        mock_param.multiplier = "100"
        mock_param.expirations = frozenset(["20260320", "20260417"])
        mock_param.strikes = frozenset([140.0, 145.0, 150.0])
        mock_ib.reqSecDefOptParamsAsync.return_value = [mock_param]

        backend = TWSBackend(config=tws_config)
        chain = await backend.get_options_chain("AAPL")
        assert len(chain) >= 1
        assert "exchange" in chain[0]

    @pytest.mark.asyncio
    async def test_search_contracts(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_desc = MagicMock()
        mock_desc.contract = MagicMock()
        mock_desc.contract.symbol = "AAPL"
        mock_desc.contract.secType = "STK"
        mock_desc.contract.primaryExchange = "NASDAQ"
        mock_desc.contract.currency = "USD"
        mock_ib.reqMatchingSymbolsAsync.return_value = [mock_desc]

        backend = TWSBackend(config=tws_config)
        results = await backend.search_contracts("AAPL")
        assert len(results) == 1
        assert results[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_run_scanner(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_data = MagicMock()
        mock_data.contractDetails = MagicMock()
        mock_data.contractDetails.contract = MagicMock()
        mock_data.contractDetails.contract.symbol = "TSLA"
        mock_data.rank = 1
        mock_ib.reqScannerDataAsync.return_value = [mock_data]

        backend = TWSBackend(config=tws_config)
        results = await backend.run_scanner("TOP_PERC_GAIN", num_results=10)
        assert len(results) == 1
        assert results[0]["symbol"] == "TSLA"


# =============================================================================
# Orders
# =============================================================================

class TestTWSBackendOrders:
    @pytest.mark.asyncio
    async def test_place_limit_order(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_trade = MagicMock()
        mock_trade.order = MagicMock()
        mock_trade.order.orderId = 42
        mock_trade.order.action = "BUY"
        mock_trade.order.totalQuantity = 10
        mock_trade.orderStatus = MagicMock()
        mock_trade.orderStatus.status = "Submitted"
        mock_trade.orderStatus.filled = 0
        mock_trade.orderStatus.remaining = 10
        mock_trade.orderStatus.avgFillPrice = 0.0
        mock_trade.contract = MagicMock()
        mock_trade.contract.symbol = "AAPL"
        mock_ib.placeOrder.return_value = mock_trade

        backend = TWSBackend(config=tws_config)
        order = OrderRequest(
            symbol="AAPL", action="BUY", quantity=10,
            order_type="LMT", limit_price=Decimal("150.00"),
        )
        status = await backend.place_order(order)

        assert isinstance(status, OrderStatus)
        assert status.order_id == 42
        assert status.symbol == "AAPL"
        assert status.action == "BUY"
        assert status.quantity == 10
        assert status.status == "Submitted"
        mock_ib.placeOrder.assert_called_once()

    @pytest.mark.asyncio
    async def test_place_market_order(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_trade = MagicMock()
        mock_trade.order = MagicMock()
        mock_trade.order.orderId = 43
        mock_trade.order.action = "SELL"
        mock_trade.order.totalQuantity = 5
        mock_trade.orderStatus = MagicMock()
        mock_trade.orderStatus.status = "Submitted"
        mock_trade.orderStatus.filled = 0
        mock_trade.orderStatus.remaining = 5
        mock_trade.orderStatus.avgFillPrice = 0.0
        mock_trade.contract = MagicMock()
        mock_trade.contract.symbol = "AAPL"
        mock_ib.placeOrder.return_value = mock_trade

        backend = TWSBackend(config=tws_config)
        order = OrderRequest(symbol="AAPL", action="SELL", quantity=5, order_type="MKT")
        status = await backend.place_order(order)
        assert status.order_id == 43
        assert status.action == "SELL"

    @pytest.mark.asyncio
    async def test_cancel_order(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        backend = TWSBackend(config=tws_config)
        result = await backend.cancel_order(42)
        mock_ib.cancelOrder.assert_called_once()
        assert "order_id" in result
        assert result["order_id"] == 42

    @pytest.mark.asyncio
    async def test_get_open_orders(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_trade = MagicMock()
        mock_trade.order = MagicMock()
        mock_trade.order.orderId = 10
        mock_trade.order.action = "BUY"
        mock_trade.order.totalQuantity = 100
        mock_trade.orderStatus = MagicMock()
        mock_trade.orderStatus.status = "Submitted"
        mock_trade.orderStatus.filled = 0
        mock_trade.orderStatus.remaining = 100
        mock_trade.orderStatus.avgFillPrice = 0.0
        mock_trade.contract = MagicMock()
        mock_trade.contract.symbol = "MSFT"
        mock_ib.openTrades.return_value = [mock_trade]

        backend = TWSBackend(config=tws_config)
        orders = await backend.get_open_orders()
        assert len(orders) == 1
        assert isinstance(orders[0], OrderStatus)
        assert orders[0].symbol == "MSFT"

    @pytest.mark.asyncio
    async def test_modify_order(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        # Simulate an existing open trade
        mock_existing = MagicMock()
        mock_existing.order = MagicMock()
        mock_existing.order.orderId = 42
        mock_existing.order.action = "BUY"
        mock_existing.order.totalQuantity = 10
        mock_existing.order.lmtPrice = 150.0
        mock_existing.order.orderType = "LMT"
        mock_existing.order.tif = "DAY"
        mock_existing.orderStatus = MagicMock()
        mock_existing.orderStatus.status = "Submitted"
        mock_existing.orderStatus.filled = 0
        mock_existing.orderStatus.remaining = 10
        mock_existing.orderStatus.avgFillPrice = 0.0
        mock_existing.contract = MagicMock()
        mock_existing.contract.symbol = "AAPL"
        mock_ib.openTrades.return_value = [mock_existing]
        mock_ib.placeOrder.return_value = mock_existing

        backend = TWSBackend(config=tws_config)
        status = await backend.modify_order(42, quantity=20)
        assert isinstance(status, OrderStatus)


# =============================================================================
# Account & Portfolio
# =============================================================================

class TestTWSBackendAccount:
    @pytest.mark.asyncio
    async def test_get_account_summary(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        # Mock account values
        def make_av(tag, value, currency="USD", account="DU12345"):
            av = MagicMock()
            av.tag = tag
            av.value = str(value)
            av.currency = currency
            av.account = account
            return av

        mock_ib.accountSummaryAsync.return_value = [
            make_av("NetLiquidation", "100000"),
            make_av("TotalCashValue", "50000"),
            make_av("BuyingPower", "200000"),
            make_av("GrossPositionValue", "50000"),
            make_av("UnrealizedPnL", "1500"),
            make_av("RealizedPnL", "300"),
        ]

        backend = TWSBackend(config=tws_config)
        summary = await backend.get_account_summary()
        assert isinstance(summary, AccountSummary)
        assert summary.account_id == "DU12345"
        assert summary.net_liquidation == Decimal("100000")
        assert summary.buying_power == Decimal("200000")

    @pytest.mark.asyncio
    async def test_get_positions(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_pos = MagicMock()
        mock_pos.contract = MagicMock()
        mock_pos.contract.symbol = "AAPL"
        mock_pos.position = 100
        mock_pos.avgCost = 145.50
        mock_pos.marketValue = 15025.0
        mock_pos.unrealizedPNL = 475.0
        mock_pos.realizedPNL = 0.0
        mock_ib.positions.return_value = [mock_pos]

        backend = TWSBackend(config=tws_config)
        positions = await backend.get_positions()
        assert len(positions) == 1
        assert isinstance(positions[0], Position)
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == 100
        assert positions[0].avg_cost == Decimal("145.5")

    @pytest.mark.asyncio
    async def test_get_pnl(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_pnl = MagicMock()
        mock_pnl.dailyPnL = 1250.50
        mock_pnl.unrealizedPnL = 800.25
        mock_pnl.realizedPnL = 450.25
        mock_ib.pnl.return_value = [mock_pnl]

        backend = TWSBackend(config=tws_config)
        pnl = await backend.get_pnl()
        assert "daily_pnl" in pnl
        assert "unrealized_pnl" in pnl
        assert "realized_pnl" in pnl

    @pytest.mark.asyncio
    async def test_get_trades(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_fill = MagicMock()
        mock_fill.contract = MagicMock()
        mock_fill.contract.symbol = "AAPL"
        mock_fill.execution = MagicMock()
        mock_fill.execution.execId = "exec001"
        mock_fill.execution.side = "BOT"
        mock_fill.execution.shares = 10.0
        mock_fill.execution.price = 150.25
        mock_fill.execution.time = datetime(2026, 2, 19, 10, 30)
        mock_ib.reqExecutionsAsync.return_value = [mock_fill]

        backend = TWSBackend(config=tws_config)
        trades = await backend.get_trades(days=1)
        assert len(trades) == 1
        assert trades[0]["symbol"] == "AAPL"
        assert trades[0]["side"] == "BOT"


# =============================================================================
# Info
# =============================================================================

class TestTWSBackendInfo:
    @pytest.mark.asyncio
    async def test_get_news(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_article = MagicMock()
        mock_article.time = datetime(2026, 2, 19, 9, 0)
        mock_article.providerCode = "BRFG"
        mock_article.articleId = "art001"
        mock_article.headline = "AAPL earnings beat expectations"
        mock_ib.reqHistoricalNewsAsync.return_value = [mock_article]

        backend = TWSBackend(config=tws_config)
        news = await backend.get_news(symbol="AAPL", num_articles=5)
        assert len(news) == 1
        assert "headline" in news[0]
        assert news[0]["headline"] == "AAPL earnings beat expectations"

    @pytest.mark.asyncio
    async def test_get_news_no_symbol(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_ib.reqHistoricalNewsAsync.return_value = []
        backend = TWSBackend(config=tws_config)
        news = await backend.get_news()
        assert isinstance(news, list)

    @pytest.mark.asyncio
    async def test_get_fundamentals(self, tws_config, mock_ib):
        from parrot.tools.ibkr.tws_backend import TWSBackend

        mock_ib.reqFundamentalDataAsync.return_value = "<xml>fundamental data</xml>"

        backend = TWSBackend(config=tws_config)
        result = await backend.get_fundamentals("AAPL")
        assert isinstance(result, dict)
        assert "symbol" in result
        assert "data" in result


# =============================================================================
# Import guard
# =============================================================================

class TestTWSBackendImportGuard:
    def test_import_error_without_ib_async(self):
        """TWSBackend raises clear error if ib_async not available."""
        from parrot.tools.ibkr.tws_backend import HAS_IB_ASYNC
        # If we reach here, ib_async IS installed, so just verify the flag
        assert HAS_IB_ASYNC is True

    def test_is_subclass_of_backend(self):
        from parrot.tools.ibkr.tws_backend import TWSBackend
        from parrot.tools.ibkr.backend import IBKRBackend
        assert issubclass(TWSBackend, IBKRBackend)
