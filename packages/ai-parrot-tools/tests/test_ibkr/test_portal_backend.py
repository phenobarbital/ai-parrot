"""Mocked unit tests for IBKR Client Portal REST backend."""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

from parrot.tools.ibkr.models import IBKRConfig, ContractSpec, OrderRequest
from parrot.tools.ibkr.portal_backend import PortalBackend


# ── Helpers ──────────────────────────────────────────────────────


def _mock_response(json_data, status=200):
    """Create a mock aiohttp response context manager."""
    resp = AsyncMock()
    resp.json = AsyncMock(return_value=json_data)
    resp.status = status
    resp.raise_for_status = MagicMock()
    return resp


@asynccontextmanager
async def _mock_cm(resp):
    """Wrap a mock response in an async context manager."""
    yield resp


@pytest.fixture
def portal_config():
    return IBKRConfig(
        backend="portal",
        portal_url="https://localhost:5000/v1/api",
    )


@pytest.fixture
def backend(portal_config):
    """Create a PortalBackend with mocked session."""
    b = PortalBackend(config=portal_config)
    b._session = MagicMock()
    b._session.closed = False
    b._authenticated = True
    b._account_id = "U1234567"
    return b


def _setup_request(backend, return_value):
    """Replace _request with an AsyncMock returning the given value."""
    backend._request = AsyncMock(return_value=return_value)


def _setup_resolve_conid(backend, conid=265598):
    """Replace _resolve_conid with an AsyncMock."""
    backend._resolve_conid = AsyncMock(return_value=conid)


# ── Connection Tests ─────────────────────────────────────────────


class TestConnection:
    @pytest.mark.asyncio
    async def test_connect_creates_session(self, portal_config):
        backend = PortalBackend(config=portal_config)
        auth_resp = _mock_response({"authenticated": True})

        with patch("aiohttp.ClientSession") as MockSession:
            mock_session = MagicMock()
            mock_session.post = MagicMock(
                return_value=_mock_cm(auth_resp)
            )
            MockSession.return_value = mock_session
            await backend.connect()
            assert backend._session is not None
            assert backend._authenticated is True

    @pytest.mark.asyncio
    async def test_disconnect_closes_session(self, backend):
        mock_close = AsyncMock()
        backend._session.close = mock_close
        backend._session.closed = False
        await backend.disconnect()
        mock_close.assert_called_once()
        assert backend._session is None
        assert backend._authenticated is False

    @pytest.mark.asyncio
    async def test_disconnect_noop_when_no_session(self, portal_config):
        b = PortalBackend(config=portal_config)
        await b.disconnect()  # Should not raise

    @pytest.mark.asyncio
    async def test_is_connected_true(self, backend):
        _setup_request(backend, {"authenticated": True})
        assert await backend.is_connected() is True

    @pytest.mark.asyncio
    async def test_is_connected_false_no_session(self, portal_config):
        b = PortalBackend(config=portal_config)
        assert await b.is_connected() is False


# ── Market Data Tests ────────────────────────────────────────────


class TestMarketData:
    @pytest.mark.asyncio
    async def test_get_quote(self, backend):
        _setup_resolve_conid(backend, 265598)
        _setup_request(backend, [
            {"55": "AAPL", "31": "150.25", "84": "150.20", "86": "150.30", "7282": "50000000"}
        ])
        contract = ContractSpec(symbol="AAPL")
        quote = await backend.get_quote(contract)
        assert quote.symbol == "AAPL"
        assert quote.last == Decimal("150.25")
        assert quote.bid == Decimal("150.20")
        assert quote.ask == Decimal("150.30")
        assert quote.volume == 50000000

    @pytest.mark.asyncio
    async def test_get_quote_empty_response(self, backend):
        _setup_resolve_conid(backend, 265598)
        _setup_request(backend, [])
        contract = ContractSpec(symbol="AAPL")
        quote = await backend.get_quote(contract)
        assert quote.symbol == "AAPL"
        assert quote.last is None

    @pytest.mark.asyncio
    async def test_get_historical_bars(self, backend):
        _setup_resolve_conid(backend, 265598)
        _setup_request(backend, {
            "data": [
                {"t": 1700000000000, "o": 150.0, "h": 155.0, "l": 149.0, "c": 153.0, "v": 1000000},
                {"t": 1700086400000, "o": 153.0, "h": 158.0, "l": 152.0, "c": 157.0, "v": 1200000},
            ]
        })
        contract = ContractSpec(symbol="AAPL")
        bars = await backend.get_historical_bars(contract, duration="2d", bar_size="1d")
        assert len(bars) == 2
        assert bars[0].open == Decimal("150.0")
        assert bars[0].close == Decimal("153.0")
        assert bars[0].volume == 1000000
        assert bars[1].high == Decimal("158.0")

    @pytest.mark.asyncio
    async def test_get_historical_bars_empty(self, backend):
        _setup_resolve_conid(backend, 265598)
        _setup_request(backend, {"data": []})
        contract = ContractSpec(symbol="AAPL")
        bars = await backend.get_historical_bars(contract, duration="1d", bar_size="1h")
        assert bars == []

    @pytest.mark.asyncio
    async def test_search_contracts(self, backend):
        _setup_request(backend, [
            {"conid": 265598, "companyName": "Apple Inc", "symbol": "AAPL"},
        ])
        results = await backend.search_contracts("AAPL")
        assert len(results) == 1
        assert results[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_get_options_chain(self, backend):
        _setup_request(backend, [{"strike": 150, "expiry": "20260320"}])
        result = await backend.get_options_chain("AAPL", expiry="20260320")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_run_scanner(self, backend):
        _setup_request(backend, [
            {"conid": 265598, "symbol": "AAPL"},
            {"conid": 272093, "symbol": "MSFT"},
        ])
        results = await backend.run_scanner("TOP_PERC_GAIN", num_results=2)
        assert len(results) == 2


# ── Order Management Tests ───────────────────────────────────────


class TestOrderManagement:
    @pytest.mark.asyncio
    async def test_place_order(self, backend):
        _setup_resolve_conid(backend, 265598)
        _setup_request(backend, [
            {"order_id": 12345, "order_status": "Submitted"}
        ])
        order = OrderRequest(
            symbol="AAPL", action="BUY", quantity=10,
            order_type="LMT", limit_price=Decimal("150.00"),
        )
        status = await backend.place_order(order)
        assert status.order_id == 12345
        assert status.symbol == "AAPL"
        assert status.action == "BUY"
        assert status.quantity == 10
        assert status.status == "Submitted"

    @pytest.mark.asyncio
    async def test_place_market_order(self, backend):
        _setup_resolve_conid(backend, 265598)
        _setup_request(backend, [
            {"order_id": 12346, "order_status": "Submitted"}
        ])
        order = OrderRequest(
            symbol="AAPL", action="SELL", quantity=5, order_type="MKT",
        )
        status = await backend.place_order(order)
        assert status.order_id == 12346
        assert status.action == "SELL"

    @pytest.mark.asyncio
    async def test_modify_order(self, backend):
        _setup_request(backend, [
            {"symbol": "AAPL", "side": "BUY", "quantity": 15, "order_status": "Modified"}
        ])
        status = await backend.modify_order(12345, quantity=15)
        assert status.order_id == 12345
        assert status.status == "Modified"

    @pytest.mark.asyncio
    async def test_cancel_order(self, backend):
        _setup_request(backend, {"order_id": 12345, "msg": "Order cancelled"})
        result = await backend.cancel_order(12345)
        assert result["order_id"] == 12345

    @pytest.mark.asyncio
    async def test_get_open_orders(self, backend):
        _setup_request(backend, {
            "orders": [
                {
                    "orderId": 12345,
                    "ticker": "AAPL",
                    "side": "BUY",
                    "totalSize": 10,
                    "filledQuantity": 5,
                    "remainingQuantity": 5,
                    "avgPrice": 150.5,
                    "status": "PartiallyFilled",
                },
            ]
        })
        orders = await backend.get_open_orders()
        assert len(orders) == 1
        assert orders[0].order_id == 12345
        assert orders[0].filled == 5
        assert orders[0].remaining == 5
        assert orders[0].avg_fill_price == Decimal("150.5")
        assert orders[0].status == "PartiallyFilled"

    @pytest.mark.asyncio
    async def test_get_open_orders_empty(self, backend):
        _setup_request(backend, {"orders": []})
        orders = await backend.get_open_orders()
        assert orders == []


# ── Account & Portfolio Tests ────────────────────────────────────


class TestAccountPortfolio:
    @pytest.mark.asyncio
    async def test_get_account_summary(self, backend):
        _setup_request(backend, {
            "netliquidation": {"amount": 100000.50},
            "totalcashvalue": {"amount": 50000.25},
            "buyingpower": {"amount": 200000.00},
            "grosspositionvalue": {"amount": 50000.25},
            "unrealizedpnl": {"amount": 1500.75},
            "realizedpnl": {"amount": 500.00},
        })
        summary = await backend.get_account_summary()
        assert summary.account_id == "U1234567"
        assert summary.net_liquidation == Decimal("100000.50")
        assert summary.total_cash == Decimal("50000.25")
        assert summary.buying_power == Decimal("200000.00")
        assert summary.unrealized_pnl == Decimal("1500.75")

    @pytest.mark.asyncio
    async def test_get_positions(self, backend):
        _setup_request(backend, [
            {
                "ticker": "AAPL",
                "position": 100,
                "avgCost": 145.50,
                "mktValue": 15025.00,
                "unrealizedPnl": 475.00,
                "realizedPnl": 0,
            },
            {
                "ticker": "MSFT",
                "position": -50,
                "avgCost": 380.00,
                "mktValue": 18500.00,
                "unrealizedPnl": -500.00,
                "realizedPnl": 200.00,
            },
        ])
        positions = await backend.get_positions()
        assert len(positions) == 2
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == 100
        assert positions[0].avg_cost == Decimal("145.50")
        assert positions[0].market_value == Decimal("15025.00")
        assert positions[1].symbol == "MSFT"
        assert positions[1].quantity == -50

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, backend):
        _setup_request(backend, [])
        positions = await backend.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_get_pnl(self, backend):
        _setup_request(backend, {
            "U1234567": {"dpl": 1500.75, "nl": 100000.50}
        })
        pnl = await backend.get_pnl()
        assert pnl["dpl"] == 1500.75

    @pytest.mark.asyncio
    async def test_get_trades(self, backend):
        _setup_request(backend, [
            {"execution_id": "001", "symbol": "AAPL", "side": "BOT", "shares": 100},
        ])
        trades = await backend.get_trades(days=1)
        assert len(trades) == 1
        assert trades[0]["symbol"] == "AAPL"


# ── Info Tests ───────────────────────────────────────────────────


class TestInfo:
    @pytest.mark.asyncio
    async def test_get_news(self, backend):
        _setup_request(backend, [
            {"title": "Apple earnings beat", "source": "Reuters"},
            {"title": "Tech rally continues", "source": "Bloomberg"},
        ])
        news = await backend.get_news(symbol="AAPL", num_articles=2)
        assert len(news) == 2
        assert news[0]["title"] == "Apple earnings beat"

    @pytest.mark.asyncio
    async def test_get_news_empty(self, backend):
        _setup_request(backend, [])
        news = await backend.get_news()
        assert news == []

    @pytest.mark.asyncio
    async def test_get_fundamentals(self, backend):
        _setup_resolve_conid(backend, 265598)
        _setup_request(backend, {
            "symbol": "AAPL", "pe_ratio": 28.5, "market_cap": "2.8T"
        })
        data = await backend.get_fundamentals("AAPL")
        assert data["symbol"] == "AAPL"
        assert data["pe_ratio"] == 28.5


# ── Authentication & Session Tests ───────────────────────────────


class TestAuthentication:
    @pytest.mark.asyncio
    async def test_authenticate_already_authenticated(self, portal_config):
        backend = PortalBackend(config=portal_config)
        auth_resp = _mock_response({"authenticated": True})
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=_mock_cm(auth_resp))
        backend._session = mock_session

        await backend._authenticate()
        assert backend._authenticated is True

    @pytest.mark.asyncio
    async def test_authenticate_triggers_sso(self, portal_config):
        backend = PortalBackend(config=portal_config)
        status_resp = _mock_response({"authenticated": False})
        sso_resp = _mock_response({"authenticated": True})

        call_count = 0

        def mock_post(path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_cm(status_resp)
            return _mock_cm(sso_resp)

        mock_session = MagicMock()
        mock_session.post = mock_post
        backend._session = mock_session

        await backend._authenticate()
        assert backend._authenticated is True

    @pytest.mark.asyncio
    async def test_request_raises_without_session(self, portal_config):
        backend = PortalBackend(config=portal_config)
        with pytest.raises(RuntimeError, match="Session not initialized"):
            await backend._request("GET", "/test")


# ── Account ID Resolution Tests ──────────────────────────────────


class TestAccountIdResolution:
    @pytest.mark.asyncio
    async def test_get_account_id_cached(self, backend):
        result = await backend._get_account_id()
        assert result == "U1234567"
        # _request should not have been called since it's cached
        backend._request = AsyncMock()
        result = await backend._get_account_id()
        backend._request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_account_id_fetches(self, portal_config):
        backend = PortalBackend(config=portal_config)
        backend._session = MagicMock()
        backend._request = AsyncMock(
            return_value=[{"accountId": "U9999999"}]
        )
        result = await backend._get_account_id()
        assert result == "U9999999"


# ── Contract Resolution Tests ────────────────────────────────────


class TestConidResolution:
    @pytest.mark.asyncio
    async def test_resolve_conid_success(self, backend):
        _setup_request(backend, [{"conid": 265598, "symbol": "AAPL"}])
        conid = await backend._resolve_conid(ContractSpec(symbol="AAPL"))
        assert conid == 265598

    @pytest.mark.asyncio
    async def test_resolve_conid_not_found(self, backend):
        _setup_request(backend, [])
        with pytest.raises(ValueError, match="Could not resolve conid"):
            await backend._resolve_conid(ContractSpec(symbol="UNKNOWN"))


# ── Request Retry on 401 ────────────────────────────────────────


class TestRequestRetry:
    @pytest.mark.asyncio
    async def test_request_retries_on_401(self, portal_config):
        backend = PortalBackend(config=portal_config)

        # First call returns 401, retry returns 200
        first_resp = _mock_response({}, status=401)
        retry_resp = _mock_response({"result": "ok"}, status=200)

        call_count = 0

        def mock_request(method, path, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_cm(first_resp)
            return _mock_cm(retry_resp)

        mock_session = MagicMock()
        mock_session.request = mock_request
        mock_session.post = MagicMock(
            return_value=_mock_cm(_mock_response({"authenticated": True}))
        )
        backend._session = mock_session

        result = await backend._request("GET", "/test")
        assert result == {"result": "ok"}
