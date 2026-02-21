"""Tests for IBKRToolkit — the main integration layer."""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.tools.ibkr.models import (
    IBKRConfig,
    RiskConfig,
    OrderRequest,
    OrderStatus,
    Quote,
    BarData,
    Position,
    AccountSummary,
)


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def mock_backend():
    """Create a fully mocked IBKRBackend."""
    backend = MagicMock()
    backend.connect = AsyncMock()
    backend.disconnect = AsyncMock()
    backend.is_connected = AsyncMock(return_value=True)
    backend.get_quote = AsyncMock(return_value=Quote(
        symbol="AAPL", last=Decimal("150.25"),
        bid=Decimal("150.20"), ask=Decimal("150.30"), volume=1000000,
    ))
    backend.get_historical_bars = AsyncMock(return_value=[])
    backend.get_options_chain = AsyncMock(return_value=[])
    backend.search_contracts = AsyncMock(return_value=[])
    backend.run_scanner = AsyncMock(return_value=[])
    backend.place_order = AsyncMock(return_value=OrderStatus(
        order_id=1, symbol="AAPL", action="BUY",
        quantity=5, status="Submitted",
    ))
    backend.modify_order = AsyncMock(return_value=OrderStatus(
        order_id=1, symbol="AAPL", action="BUY",
        quantity=10, status="Modified",
    ))
    backend.cancel_order = AsyncMock(return_value={"order_id": 1, "status": "cancel_requested"})
    backend.get_open_orders = AsyncMock(return_value=[])
    backend.get_account_summary = AsyncMock(return_value=AccountSummary(
        account_id="U1234567", net_liquidation=Decimal("100000"),
        total_cash=Decimal("50000"), buying_power=Decimal("200000"),
        gross_position_value=Decimal("50000"),
        unrealized_pnl=Decimal("1500"), realized_pnl=Decimal("500"),
    ))
    backend.get_positions = AsyncMock(return_value=[])
    backend.get_pnl = AsyncMock(return_value={"daily_pnl": 0})
    backend.get_trades = AsyncMock(return_value=[])
    backend.get_news = AsyncMock(return_value=[])
    backend.get_fundamentals = AsyncMock(return_value={"symbol": "AAPL"})
    return backend


def _make_toolkit(config=None, risk_config=None, backend=None):
    """Create an IBKRToolkit with optional overrides."""
    from parrot.tools.ibkr import IBKRToolkit
    tk = IBKRToolkit(
        config=config or IBKRConfig(),
        risk_config=risk_config or RiskConfig(require_confirmation=False),
    )
    if backend:
        tk._backend = backend
    return tk


# ── Init Tests ──────────────────────────────────────────────────


class TestIBKRToolkitInit:
    def test_default_config(self):
        from parrot.tools.ibkr import IBKRToolkit
        toolkit = IBKRToolkit()
        assert toolkit.config.backend == "tws"

    def test_portal_backend_selected(self):
        from parrot.tools.ibkr import IBKRToolkit
        config = IBKRConfig(backend="portal", portal_url="https://localhost:5000/v1/api")
        toolkit = IBKRToolkit(config=config)
        assert toolkit.config.backend == "portal"
        from parrot.tools.ibkr.portal_backend import PortalBackend
        assert isinstance(toolkit._backend, PortalBackend)

    def test_tws_backend_selected(self):
        from parrot.tools.ibkr import IBKRToolkit
        toolkit = IBKRToolkit(config=IBKRConfig(backend="tws"))
        from parrot.tools.ibkr.tws_backend import TWSBackend
        assert isinstance(toolkit._backend, TWSBackend)


# ── Tool Exposure Tests ─────────────────────────────────────────


class TestIBKRToolkitTools:
    def test_get_tools_returns_all(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        tools = toolkit.get_tools()
        tool_names = [t.name for t in tools]
        # Market data
        assert "get_quote" in tool_names
        assert "get_historical_bars" in tool_names
        assert "get_options_chain" in tool_names
        assert "search_contracts" in tool_names
        assert "run_scanner" in tool_names
        # Orders
        assert "place_order" in tool_names
        assert "modify_order" in tool_names
        assert "cancel_order" in tool_names
        assert "get_open_orders" in tool_names
        # Account
        assert "get_account_summary" in tool_names
        assert "get_positions" in tool_names
        assert "get_pnl" in tool_names
        assert "get_trades" in tool_names
        # Info
        assert "get_news" in tool_names
        assert "get_fundamentals" in tool_names

    def test_readonly_excludes_order_tools(self, mock_backend):
        toolkit = _make_toolkit(
            config=IBKRConfig(readonly=True),
            backend=mock_backend,
        )
        tools = toolkit.get_tools()
        tool_names = [t.name for t in tools]
        # Order-mutating tools should be excluded
        assert "place_order" not in tool_names
        assert "modify_order" not in tool_names
        assert "cancel_order" not in tool_names
        # Non-mutating tools should remain
        assert "get_quote" in tool_names
        assert "get_open_orders" in tool_names
        assert "get_positions" in tool_names

    def test_tools_have_descriptions(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"


# ── Context Manager Tests ───────────────────────────────────────


class TestIBKRToolkitContextManager:
    @pytest.mark.asyncio
    async def test_context_manager(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        async with toolkit:
            pass
        mock_backend.connect.assert_called_once()
        mock_backend.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_disconnect(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        await toolkit.connect()
        mock_backend.connect.assert_called_once()
        await toolkit.disconnect()
        mock_backend.disconnect.assert_called_once()


# ── Market Data Tests ───────────────────────────────────────────


class TestIBKRToolkitMarketData:
    @pytest.mark.asyncio
    async def test_get_quote(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.get_quote(symbol="AAPL")
        assert isinstance(result, dict)
        assert result["symbol"] == "AAPL"
        mock_backend.get_quote.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_historical_bars(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.get_historical_bars(
            symbol="AAPL", duration="1 D", bar_size="1 hour",
        )
        assert isinstance(result, list)
        mock_backend.get_historical_bars.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_options_chain(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.get_options_chain(symbol="AAPL", expiry="20260320")
        assert isinstance(result, list)
        mock_backend.get_options_chain.assert_called_once_with("AAPL", "20260320")

    @pytest.mark.asyncio
    async def test_search_contracts(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.search_contracts(pattern="AAPL")
        assert isinstance(result, list)
        mock_backend.search_contracts.assert_called_once_with("AAPL", "STK")

    @pytest.mark.asyncio
    async def test_run_scanner(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.run_scanner(scan_code="TOP_PERC_GAIN", num_results=10)
        mock_backend.run_scanner.assert_called_once_with("TOP_PERC_GAIN", 10)


# ── Order Management Tests ──────────────────────────────────────


class TestIBKRToolkitOrders:
    @pytest.mark.asyncio
    async def test_place_order_passes_risk(self, mock_backend):
        toolkit = _make_toolkit(
            risk_config=RiskConfig(max_order_qty=100, require_confirmation=False),
            backend=mock_backend,
        )
        result = await toolkit.place_order(
            symbol="AAPL", action="BUY", quantity=5, limit_price=150.0,
        )
        assert isinstance(result, dict)
        assert result["symbol"] == "AAPL"
        assert result["status"] == "Submitted"
        mock_backend.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_place_order_fails_risk(self, mock_backend):
        toolkit = _make_toolkit(
            risk_config=RiskConfig(max_order_qty=5, require_confirmation=False),
            backend=mock_backend,
        )
        with pytest.raises(ValueError, match="Risk check failed"):
            await toolkit.place_order(
                symbol="AAPL", action="BUY", quantity=50, limit_price=150.0,
            )
        mock_backend.place_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_place_market_order(self, mock_backend):
        toolkit = _make_toolkit(
            risk_config=RiskConfig(max_order_qty=100, require_confirmation=False),
            backend=mock_backend,
        )
        result = await toolkit.place_order(
            symbol="AAPL", action="SELL", quantity=10, order_type="MKT",
        )
        assert isinstance(result, dict)
        mock_backend.place_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_modify_order(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.modify_order(order_id=1, quantity=10)
        assert isinstance(result, dict)
        mock_backend.modify_order.assert_called_once_with(1, quantity=10)

    @pytest.mark.asyncio
    async def test_cancel_order(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.cancel_order(order_id=1)
        assert result["order_id"] == 1
        mock_backend.cancel_order.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_get_open_orders(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.get_open_orders()
        assert isinstance(result, list)
        mock_backend.get_open_orders.assert_called_once()


# ── Account & Portfolio Tests ───────────────────────────────────


class TestIBKRToolkitAccount:
    @pytest.mark.asyncio
    async def test_get_account_summary(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.get_account_summary()
        assert isinstance(result, dict)
        assert result["account_id"] == "U1234567"
        mock_backend.get_account_summary.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_positions(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.get_positions()
        assert isinstance(result, list)
        mock_backend.get_positions.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_pnl(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.get_pnl()
        assert isinstance(result, dict)
        mock_backend.get_pnl.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_trades(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.get_trades(days=3)
        assert isinstance(result, list)
        mock_backend.get_trades.assert_called_once_with(3)


# ── Info Tests ──────────────────────────────────────────────────


class TestIBKRToolkitInfo:
    @pytest.mark.asyncio
    async def test_get_news(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.get_news(symbol="AAPL", num_articles=3)
        assert isinstance(result, list)
        mock_backend.get_news.assert_called_once_with("AAPL", 3)

    @pytest.mark.asyncio
    async def test_get_fundamentals(self, mock_backend):
        toolkit = _make_toolkit(backend=mock_backend)
        result = await toolkit.get_fundamentals(symbol="AAPL")
        assert isinstance(result, dict)
        mock_backend.get_fundamentals.assert_called_once_with("AAPL")


# ── Import Tests ────────────────────────────────────────────────


class TestIBKRToolkitImports:
    def test_clean_imports(self):
        from parrot.tools.ibkr import IBKRToolkit, IBKRConfig, RiskConfig
        assert IBKRToolkit is not None
        assert IBKRConfig is not None
        assert RiskConfig is not None

    def test_all_exports(self):
        import parrot.tools.ibkr as ibkr_module
        assert hasattr(ibkr_module, '__all__')
        assert "IBKRToolkit" in ibkr_module.__all__
        assert "IBKRConfig" in ibkr_module.__all__
        assert "RiskConfig" in ibkr_module.__all__

    def test_is_abstract_toolkit_subclass(self):
        from parrot.tools.ibkr import IBKRToolkit
        from parrot.tools.toolkit import AbstractToolkit
        assert issubclass(IBKRToolkit, AbstractToolkit)
