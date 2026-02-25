"""Unit tests for AbstractDriver ABC (TASK-056)."""

import pytest

from parrot.tools.scraping.drivers.abstract import AbstractDriver


# ── Minimal concrete stub implementing all abstract methods ──────


class ConcreteStub(AbstractDriver):
    """Minimal concrete implementation for testing."""

    async def start(self) -> None:
        pass

    async def quit(self) -> None:
        pass

    async def navigate(self, url, timeout=30):
        pass

    async def go_back(self):
        pass

    async def go_forward(self):
        pass

    async def reload(self):
        pass

    async def click(self, selector, timeout=10):
        pass

    async def fill(self, selector, value, timeout=10):
        pass

    async def select_option(self, selector, value, timeout=10):
        pass

    async def hover(self, selector, timeout=10):
        pass

    async def press_key(self, key):
        pass

    async def get_page_source(self):
        return "<html></html>"

    async def get_text(self, selector, timeout=10):
        return "text"

    async def get_attribute(self, selector, attribute, timeout=10):
        return None

    async def get_all_texts(self, selector, timeout=10):
        return []

    async def screenshot(self, path, full_page=False):
        return b""

    async def wait_for_selector(self, selector, timeout=10, state="visible"):
        pass

    async def wait_for_navigation(self, timeout=30):
        pass

    async def wait_for_load_state(self, state="load", timeout=30):
        pass

    async def execute_script(self, script, *args):
        return None

    async def evaluate(self, expression):
        return None

    @property
    def current_url(self):
        return "about:blank"


# ── Tests ────────────────────────────────────────────────────────


class TestAbstractDriverCannotInstantiate:
    def test_direct_instantiation_raises(self):
        """ABC prevents direct instantiation."""
        with pytest.raises(TypeError):
            AbstractDriver()


class TestAbstractMethods:
    def test_has_required_abstract_methods(self):
        """All required methods are declared as abstract."""
        abstract_methods = AbstractDriver.__abstractmethods__
        required = {
            "start",
            "quit",
            "navigate",
            "go_back",
            "go_forward",
            "reload",
            "click",
            "fill",
            "select_option",
            "hover",
            "press_key",
            "get_page_source",
            "get_text",
            "get_attribute",
            "get_all_texts",
            "screenshot",
            "wait_for_selector",
            "wait_for_navigation",
            "wait_for_load_state",
            "execute_script",
            "evaluate",
            "current_url",
        }
        for method in required:
            assert method in abstract_methods, f"{method} is not abstract"

    def test_extended_methods_are_not_abstract(self):
        """Extended capability methods are concrete (not in __abstractmethods__)."""
        abstract_methods = AbstractDriver.__abstractmethods__
        extended = {
            "intercept_requests",
            "record_har",
            "save_pdf",
            "start_tracing",
            "stop_tracing",
            "mock_route",
        }
        for method in extended:
            assert method not in abstract_methods, (
                f"{method} should NOT be abstract"
            )


class TestConcreteSubclass:
    def test_can_instantiate(self):
        """A complete concrete subclass can be instantiated."""
        driver = ConcreteStub()
        assert isinstance(driver, AbstractDriver)

    def test_current_url_is_property(self):
        """current_url is accessible as a property."""
        driver = ConcreteStub()
        assert driver.current_url == "about:blank"


class TestExtendedCapabilitiesRaiseNotImplemented:
    @pytest.fixture
    def driver(self):
        return ConcreteStub()

    @pytest.mark.asyncio
    async def test_intercept_requests(self, driver):
        """intercept_requests raises NotImplementedError by default."""
        with pytest.raises(NotImplementedError, match="intercept_requests"):
            await driver.intercept_requests(lambda r: r)

    @pytest.mark.asyncio
    async def test_record_har(self, driver):
        """record_har raises NotImplementedError by default."""
        with pytest.raises(NotImplementedError, match="record_har"):
            await driver.record_har("/tmp/test.har")

    @pytest.mark.asyncio
    async def test_save_pdf(self, driver):
        """save_pdf raises NotImplementedError by default."""
        with pytest.raises(NotImplementedError, match="save_pdf"):
            await driver.save_pdf("/tmp/test.pdf")

    @pytest.mark.asyncio
    async def test_start_tracing(self, driver):
        """start_tracing raises NotImplementedError by default."""
        with pytest.raises(NotImplementedError, match="start_tracing"):
            await driver.start_tracing()

    @pytest.mark.asyncio
    async def test_stop_tracing(self, driver):
        """stop_tracing raises NotImplementedError by default."""
        with pytest.raises(NotImplementedError, match="stop_tracing"):
            await driver.stop_tracing("/tmp/trace.zip")

    @pytest.mark.asyncio
    async def test_mock_route(self, driver):
        """mock_route raises NotImplementedError by default."""
        with pytest.raises(NotImplementedError, match="mock_route"):
            await driver.mock_route("**/api/*", lambda r: r)

    @pytest.mark.asyncio
    async def test_error_message_includes_class_name(self, driver):
        """NotImplementedError message includes the concrete class name."""
        with pytest.raises(NotImplementedError, match="ConcreteStub"):
            await driver.intercept_requests(lambda r: r)


class TestImports:
    def test_import_from_package(self):
        """Import AbstractDriver from the drivers package."""
        from parrot.tools.scraping.drivers import AbstractDriver as AD

        assert AD is not None

    def test_import_from_module(self):
        """Import AbstractDriver from the abstract module directly."""
        from parrot.tools.scraping.drivers.abstract import (
            AbstractDriver as AD,
        )

        assert AD is not None
