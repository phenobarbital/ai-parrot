"""Tests for IBKR data models — written BEFORE implementation (TDD RED phase)."""
import pytest
from decimal import Decimal
from datetime import datetime
from pydantic import ValidationError


# =============================================================================
# IBKRConfig
# =============================================================================

class TestIBKRConfig:
    def test_defaults(self):
        """IBKRConfig has sensible defaults for paper trading."""
        from parrot.tools.ibkr.models import IBKRConfig
        config = IBKRConfig()
        assert config.backend == "tws"
        assert config.host == "127.0.0.1"
        assert config.port == 7497
        assert config.client_id == 1
        assert config.portal_url is None
        assert config.readonly is False

    def test_portal_config(self):
        """IBKRConfig accepts portal backend with URL."""
        from parrot.tools.ibkr.models import IBKRConfig
        config = IBKRConfig(
            backend="portal",
            portal_url="https://localhost:5000/v1/api",
        )
        assert config.backend == "portal"
        assert config.portal_url == "https://localhost:5000/v1/api"

    def test_invalid_backend_rejected(self):
        """IBKRConfig rejects unknown backend types."""
        from parrot.tools.ibkr.models import IBKRConfig
        with pytest.raises(ValidationError):
            IBKRConfig(backend="invalid")

    def test_readonly_mode(self):
        """IBKRConfig supports readonly mode."""
        from parrot.tools.ibkr.models import IBKRConfig
        config = IBKRConfig(readonly=True)
        assert config.readonly is True

    def test_live_port(self):
        """IBKRConfig can be set to live trading port."""
        from parrot.tools.ibkr.models import IBKRConfig
        config = IBKRConfig(port=7496)
        assert config.port == 7496


# =============================================================================
# RiskConfig
# =============================================================================

class TestRiskConfig:
    def test_defaults(self):
        """RiskConfig has safe defaults."""
        from parrot.tools.ibkr.models import RiskConfig
        config = RiskConfig()
        assert config.max_order_qty == 100
        assert config.max_order_value == Decimal("50000")
        assert config.max_position_value == Decimal("200000")
        assert config.daily_loss_limit == Decimal("5000")
        assert config.require_confirmation is True

    def test_custom_limits(self):
        """RiskConfig accepts custom limits."""
        from parrot.tools.ibkr.models import RiskConfig
        config = RiskConfig(
            max_order_qty=10,
            max_order_value=Decimal("1000"),
            daily_loss_limit=Decimal("500"),
            require_confirmation=False,
        )
        assert config.max_order_qty == 10
        assert config.max_order_value == Decimal("1000")
        assert config.require_confirmation is False


# =============================================================================
# ContractSpec
# =============================================================================

class TestContractSpec:
    def test_defaults(self):
        """ContractSpec has sensible defaults for US stocks."""
        from parrot.tools.ibkr.models import ContractSpec
        contract = ContractSpec(symbol="AAPL")
        assert contract.symbol == "AAPL"
        assert contract.sec_type == "STK"
        assert contract.exchange == "SMART"
        assert contract.currency == "USD"

    def test_options_contract(self):
        """ContractSpec supports options."""
        from parrot.tools.ibkr.models import ContractSpec
        contract = ContractSpec(symbol="AAPL", sec_type="OPT", exchange="CBOE")
        assert contract.sec_type == "OPT"
        assert contract.exchange == "CBOE"

    def test_futures_contract(self):
        """ContractSpec supports futures."""
        from parrot.tools.ibkr.models import ContractSpec
        contract = ContractSpec(symbol="ES", sec_type="FUT", exchange="GLOBEX")
        assert contract.sec_type == "FUT"

    def test_crypto_contract(self):
        """ContractSpec supports crypto."""
        from parrot.tools.ibkr.models import ContractSpec
        contract = ContractSpec(symbol="BTC", sec_type="CRYPTO", currency="USD")
        assert contract.sec_type == "CRYPTO"

    def test_symbol_required(self):
        """ContractSpec requires symbol."""
        from parrot.tools.ibkr.models import ContractSpec
        with pytest.raises(ValidationError):
            ContractSpec()


# =============================================================================
# Quote
# =============================================================================

class TestQuote:
    def test_minimal_quote(self):
        """Quote works with just symbol."""
        from parrot.tools.ibkr.models import Quote
        q = Quote(symbol="AAPL")
        assert q.symbol == "AAPL"
        assert q.last is None
        assert q.bid is None
        assert q.ask is None
        assert q.volume is None
        assert q.timestamp is None

    def test_full_quote(self):
        """Quote accepts all fields."""
        from parrot.tools.ibkr.models import Quote
        ts = datetime(2026, 2, 19, 10, 30, 0)
        q = Quote(
            symbol="AAPL",
            last=Decimal("150.25"),
            bid=Decimal("150.20"),
            ask=Decimal("150.30"),
            volume=1000000,
            timestamp=ts,
        )
        assert q.last == Decimal("150.25")
        assert q.bid < q.ask
        assert q.volume == 1000000
        assert q.timestamp == ts


# =============================================================================
# BarData
# =============================================================================

class TestBarData:
    def test_valid_bar(self):
        """BarData accepts valid OHLCV data."""
        from parrot.tools.ibkr.models import BarData
        bar = BarData(
            timestamp=datetime(2026, 2, 19, 10, 0, 0),
            open=Decimal("150.00"),
            high=Decimal("152.00"),
            low=Decimal("149.50"),
            close=Decimal("151.25"),
            volume=500000,
        )
        assert bar.high > bar.low
        assert bar.volume == 500000

    def test_all_fields_required(self):
        """BarData requires all OHLCV fields."""
        from parrot.tools.ibkr.models import BarData
        with pytest.raises(ValidationError):
            BarData(timestamp=datetime.now())  # missing OHLCV


# =============================================================================
# OrderRequest
# =============================================================================

class TestOrderRequest:
    def test_valid_limit_order(self):
        """OrderRequest accepts a valid limit order."""
        from parrot.tools.ibkr.models import OrderRequest
        order = OrderRequest(
            symbol="AAPL",
            action="BUY",
            quantity=10,
            order_type="LMT",
            limit_price=Decimal("150.50"),
        )
        assert order.symbol == "AAPL"
        assert order.action == "BUY"
        assert order.quantity == 10
        assert order.order_type == "LMT"
        assert order.tif == "DAY"  # default

    def test_valid_market_order(self):
        """OrderRequest accepts a market order without limit price."""
        from parrot.tools.ibkr.models import OrderRequest
        order = OrderRequest(
            symbol="AAPL",
            action="SELL",
            quantity=5,
            order_type="MKT",
        )
        assert order.order_type == "MKT"
        assert order.limit_price is None

    def test_valid_stop_order(self):
        """OrderRequest accepts a stop order."""
        from parrot.tools.ibkr.models import OrderRequest
        order = OrderRequest(
            symbol="AAPL",
            action="SELL",
            quantity=10,
            order_type="STP",
            stop_price=Decimal("140.00"),
        )
        assert order.order_type == "STP"
        assert order.stop_price == Decimal("140.00")

    def test_zero_quantity_rejected(self):
        """OrderRequest rejects zero quantity."""
        from parrot.tools.ibkr.models import OrderRequest
        with pytest.raises(ValidationError):
            OrderRequest(symbol="AAPL", action="BUY", quantity=0)

    def test_negative_quantity_rejected(self):
        """OrderRequest rejects negative quantity."""
        from parrot.tools.ibkr.models import OrderRequest
        with pytest.raises(ValidationError):
            OrderRequest(symbol="AAPL", action="BUY", quantity=-5)

    def test_invalid_action_rejected(self):
        """OrderRequest rejects invalid action."""
        from parrot.tools.ibkr.models import OrderRequest
        with pytest.raises(ValidationError):
            OrderRequest(symbol="AAPL", action="HOLD", quantity=10)

    def test_invalid_order_type_rejected(self):
        """OrderRequest rejects invalid order type."""
        from parrot.tools.ibkr.models import OrderRequest
        with pytest.raises(ValidationError):
            OrderRequest(symbol="AAPL", action="BUY", quantity=10, order_type="INVALID")

    def test_invalid_tif_rejected(self):
        """OrderRequest rejects invalid time-in-force."""
        from parrot.tools.ibkr.models import OrderRequest
        with pytest.raises(ValidationError):
            OrderRequest(symbol="AAPL", action="BUY", quantity=10, tif="INVALID")

    def test_gtc_tif(self):
        """OrderRequest accepts GTC time-in-force."""
        from parrot.tools.ibkr.models import OrderRequest
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=10, tif="GTC")
        assert order.tif == "GTC"


# =============================================================================
# OrderStatus
# =============================================================================

class TestOrderStatus:
    def test_submitted_order(self):
        """OrderStatus represents a submitted order."""
        from parrot.tools.ibkr.models import OrderStatus
        status = OrderStatus(
            order_id=12345,
            symbol="AAPL",
            action="BUY",
            quantity=10,
            status="Submitted",
        )
        assert status.order_id == 12345
        assert status.filled == 0
        assert status.remaining == 0
        assert status.avg_fill_price is None

    def test_filled_order(self):
        """OrderStatus represents a filled order."""
        from parrot.tools.ibkr.models import OrderStatus
        status = OrderStatus(
            order_id=12345,
            symbol="AAPL",
            action="BUY",
            quantity=10,
            filled=10,
            remaining=0,
            avg_fill_price=Decimal("150.25"),
            status="Filled",
        )
        assert status.filled == 10
        assert status.remaining == 0
        assert status.avg_fill_price == Decimal("150.25")

    def test_partial_fill(self):
        """OrderStatus represents a partially filled order."""
        from parrot.tools.ibkr.models import OrderStatus
        status = OrderStatus(
            order_id=12345,
            symbol="AAPL",
            action="BUY",
            quantity=10,
            filled=3,
            remaining=7,
            avg_fill_price=Decimal("150.10"),
            status="PartiallyFilled",
        )
        assert status.filled + status.remaining == status.quantity


# =============================================================================
# Position
# =============================================================================

class TestPosition:
    def test_basic_position(self):
        """Position with required fields only."""
        from parrot.tools.ibkr.models import Position
        p = Position(symbol="AAPL", quantity=100, avg_cost=Decimal("145.00"))
        assert p.symbol == "AAPL"
        assert p.quantity == 100
        assert p.market_value is None
        assert p.unrealized_pnl is None

    def test_position_with_pnl(self):
        """Position with P&L data."""
        from parrot.tools.ibkr.models import Position
        p = Position(
            symbol="AAPL",
            quantity=100,
            avg_cost=Decimal("145.00"),
            market_value=Decimal("15025.00"),
            unrealized_pnl=Decimal("525.00"),
            realized_pnl=Decimal("0"),
        )
        assert p.unrealized_pnl == Decimal("525.00")

    def test_short_position(self):
        """Position supports negative quantity for short positions."""
        from parrot.tools.ibkr.models import Position
        p = Position(symbol="TSLA", quantity=-50, avg_cost=Decimal("200.00"))
        assert p.quantity == -50


# =============================================================================
# AccountSummary
# =============================================================================

class TestAccountSummary:
    def test_full_summary(self):
        """AccountSummary with all required fields."""
        from parrot.tools.ibkr.models import AccountSummary
        s = AccountSummary(
            account_id="DU12345",
            net_liquidation=Decimal("100000"),
            total_cash=Decimal("50000"),
            buying_power=Decimal("200000"),
            gross_position_value=Decimal("50000"),
            unrealized_pnl=Decimal("1500"),
            realized_pnl=Decimal("300"),
        )
        assert s.account_id == "DU12345"
        assert s.net_liquidation == Decimal("100000")
        assert s.buying_power == Decimal("200000")

    def test_missing_required_field_rejected(self):
        """AccountSummary rejects missing required fields."""
        from parrot.tools.ibkr.models import AccountSummary
        with pytest.raises(ValidationError):
            AccountSummary(account_id="DU12345")  # missing all monetary fields


# =============================================================================
# Serialization round-trip
# =============================================================================

class TestSerialization:
    def test_decimal_roundtrip(self):
        """Decimal fields survive JSON serialization round-trip."""
        from parrot.tools.ibkr.models import Quote
        q = Quote(symbol="AAPL", last=Decimal("150.25"))
        data = q.model_dump()
        q2 = Quote.model_validate(data)
        assert q2.last == Decimal("150.25")

    def test_order_request_json(self):
        """OrderRequest serializes to JSON-compatible dict."""
        from parrot.tools.ibkr.models import OrderRequest
        order = OrderRequest(
            symbol="AAPL", action="BUY", quantity=10,
            order_type="LMT", limit_price=Decimal("150.50"),
        )
        data = order.model_dump(mode="json")
        assert isinstance(data["symbol"], str)
        assert isinstance(data["quantity"], int)
