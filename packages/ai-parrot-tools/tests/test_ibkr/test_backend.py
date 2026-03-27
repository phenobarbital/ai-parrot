"""Tests for IBKR Backend ABC — written BEFORE implementation (TDD RED phase)."""
import pytest
from parrot.tools.ibkr.models import IBKRConfig, ContractSpec, OrderRequest
from decimal import Decimal


class TestIBKRBackendABC:
    def test_cannot_instantiate(self):
        """IBKRBackend is abstract and cannot be instantiated."""
        from parrot.tools.ibkr.backend import IBKRBackend
        with pytest.raises(TypeError):
            IBKRBackend(config=IBKRConfig())

    def test_subclass_missing_connect_only(self):
        """Subclass implementing only connect raises TypeError."""
        from parrot.tools.ibkr.backend import IBKRBackend

        class PartialBackend(IBKRBackend):
            async def connect(self):
                pass

        with pytest.raises(TypeError):
            PartialBackend(config=IBKRConfig())

    def test_subclass_missing_one_method(self):
        """Subclass missing just get_fundamentals raises TypeError."""
        from parrot.tools.ibkr.backend import IBKRBackend

        class AlmostComplete(IBKRBackend):
            async def connect(self): pass
            async def disconnect(self): pass
            async def is_connected(self): return False
            async def get_quote(self, contract): pass
            async def get_historical_bars(self, contract, duration, bar_size): pass
            async def get_options_chain(self, symbol, expiry=None): pass
            async def search_contracts(self, pattern, sec_type="STK"): pass
            async def run_scanner(self, scan_code, num_results=25): pass
            async def place_order(self, order): pass
            async def modify_order(self, order_id, **changes): pass
            async def cancel_order(self, order_id): pass
            async def get_open_orders(self): pass
            async def get_account_summary(self): pass
            async def get_positions(self): pass
            async def get_pnl(self): pass
            async def get_trades(self, days=1): pass
            async def get_news(self, symbol=None, num_articles=5): pass
            # Missing: get_fundamentals

        with pytest.raises(TypeError):
            AlmostComplete(config=IBKRConfig())

    def test_complete_subclass_instantiates(self):
        """A complete subclass can be instantiated."""
        from parrot.tools.ibkr.backend import IBKRBackend

        class StubBackend(IBKRBackend):
            async def connect(self): pass
            async def disconnect(self): pass
            async def is_connected(self): return False
            async def get_quote(self, contract): pass
            async def get_historical_bars(self, contract, duration, bar_size): pass
            async def get_options_chain(self, symbol, expiry=None): pass
            async def search_contracts(self, pattern, sec_type="STK"): pass
            async def run_scanner(self, scan_code, num_results=25): pass
            async def place_order(self, order): pass
            async def modify_order(self, order_id, **changes): pass
            async def cancel_order(self, order_id): pass
            async def get_open_orders(self): pass
            async def get_account_summary(self): pass
            async def get_positions(self): pass
            async def get_pnl(self): pass
            async def get_trades(self, days=1): pass
            async def get_news(self, symbol=None, num_articles=5): pass
            async def get_fundamentals(self, symbol): pass

        backend = StubBackend(config=IBKRConfig())
        assert backend.config.backend == "tws"

    def test_config_stored(self):
        """Backend stores config as attribute."""
        from parrot.tools.ibkr.backend import IBKRBackend

        class StubBackend(IBKRBackend):
            async def connect(self): pass
            async def disconnect(self): pass
            async def is_connected(self): return False
            async def get_quote(self, contract): pass
            async def get_historical_bars(self, contract, duration, bar_size): pass
            async def get_options_chain(self, symbol, expiry=None): pass
            async def search_contracts(self, pattern, sec_type="STK"): pass
            async def run_scanner(self, scan_code, num_results=25): pass
            async def place_order(self, order): pass
            async def modify_order(self, order_id, **changes): pass
            async def cancel_order(self, order_id): pass
            async def get_open_orders(self): pass
            async def get_account_summary(self): pass
            async def get_positions(self): pass
            async def get_pnl(self): pass
            async def get_trades(self, days=1): pass
            async def get_news(self, symbol=None, num_articles=5): pass
            async def get_fundamentals(self, symbol): pass

        config = IBKRConfig(port=7496, client_id=5)
        backend = StubBackend(config=config)
        assert backend.config.port == 7496
        assert backend.config.client_id == 5

    def test_has_logger(self):
        """Backend initializes a logger."""
        from parrot.tools.ibkr.backend import IBKRBackend

        class StubBackend(IBKRBackend):
            async def connect(self): pass
            async def disconnect(self): pass
            async def is_connected(self): return False
            async def get_quote(self, contract): pass
            async def get_historical_bars(self, contract, duration, bar_size): pass
            async def get_options_chain(self, symbol, expiry=None): pass
            async def search_contracts(self, pattern, sec_type="STK"): pass
            async def run_scanner(self, scan_code, num_results=25): pass
            async def place_order(self, order): pass
            async def modify_order(self, order_id, **changes): pass
            async def cancel_order(self, order_id): pass
            async def get_open_orders(self): pass
            async def get_account_summary(self): pass
            async def get_positions(self): pass
            async def get_pnl(self): pass
            async def get_trades(self, days=1): pass
            async def get_news(self, symbol=None, num_articles=5): pass
            async def get_fundamentals(self, symbol): pass

        backend = StubBackend(config=IBKRConfig())
        assert backend.logger is not None
        assert backend.logger.name == "StubBackend"

    @pytest.mark.asyncio
    async def test_stub_methods_callable(self):
        """All abstract methods are callable on a complete subclass."""
        from parrot.tools.ibkr.backend import IBKRBackend

        class StubBackend(IBKRBackend):
            async def connect(self): pass
            async def disconnect(self): pass
            async def is_connected(self): return False
            async def get_quote(self, contract): return None
            async def get_historical_bars(self, contract, duration, bar_size): return []
            async def get_options_chain(self, symbol, expiry=None): return []
            async def search_contracts(self, pattern, sec_type="STK"): return []
            async def run_scanner(self, scan_code, num_results=25): return []
            async def place_order(self, order): return None
            async def modify_order(self, order_id, **changes): return None
            async def cancel_order(self, order_id): return {}
            async def get_open_orders(self): return []
            async def get_account_summary(self): return None
            async def get_positions(self): return []
            async def get_pnl(self): return {}
            async def get_trades(self, days=1): return []
            async def get_news(self, symbol=None, num_articles=5): return []
            async def get_fundamentals(self, symbol): return {}

        backend = StubBackend(config=IBKRConfig())
        contract = ContractSpec(symbol="AAPL")
        order = OrderRequest(symbol="AAPL", action="BUY", quantity=10)

        # Connection methods
        await backend.connect()
        assert await backend.is_connected() is False
        await backend.disconnect()

        # Market data methods
        assert await backend.get_quote(contract) is None
        assert await backend.get_historical_bars(contract, "1 D", "1 hour") == []
        assert await backend.get_options_chain("AAPL") == []
        assert await backend.search_contracts("AAPL") == []
        assert await backend.run_scanner("TOP_PERC_GAIN") == []

        # Order methods
        assert await backend.place_order(order) is None
        assert await backend.modify_order(123, quantity=5) is None
        assert await backend.cancel_order(123) == {}
        assert await backend.get_open_orders() == []

        # Account methods
        assert await backend.get_account_summary() is None
        assert await backend.get_positions() == []
        assert await backend.get_pnl() == {}
        assert await backend.get_trades() == []

        # Info methods
        assert await backend.get_news() == []
        assert await backend.get_fundamentals("AAPL") == {}

    def test_abstract_method_count(self):
        """IBKRBackend has exactly 18 abstract methods."""
        from parrot.tools.ibkr.backend import IBKRBackend
        abstract_methods = IBKRBackend.__abstractmethods__
        assert len(abstract_methods) == 18
