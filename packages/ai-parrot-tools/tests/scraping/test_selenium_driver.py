"""Unit tests for SeleniumDriver (TASK-059).

All Selenium WebDriver calls are mocked — no real browser is required.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.tools.scraping.drivers.selenium_driver import SeleniumDriver
from parrot.tools.scraping.drivers.abstract import AbstractDriver


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def driver():
    """SeleniumDriver with default settings (not started)."""
    return SeleniumDriver()


@pytest.fixture
def mock_webdriver():
    """A mock Selenium WebDriver with common methods."""
    wd = MagicMock()
    wd.current_url = "https://example.com"
    wd.page_source = "<html><body>Hello</body></html>"
    wd.get_screenshot_as_png.return_value = b"\x89PNG"
    return wd


@pytest.fixture
def mock_element():
    """A mock Selenium WebElement."""
    el = MagicMock()
    el.text = "Hello World"
    el.get_attribute.return_value = "https://link.com"
    return el


@pytest.fixture
def started_driver(driver, mock_webdriver):
    """SeleniumDriver with mocked internals (simulates started state)."""
    driver._driver = mock_webdriver
    driver._setup = MagicMock()
    return driver


# ── Identity Tests ───────────────────────────────────────────────


class TestSeleniumDriverIsAbstractDriver:
    def test_isinstance(self, driver):
        assert isinstance(driver, AbstractDriver)

    def test_default_browser(self, driver):
        assert driver._browser_name == "chrome"

    def test_default_headless(self, driver):
        assert driver._headless is True

    def test_custom_browser(self):
        d = SeleniumDriver(browser="firefox", headless=False)
        assert d._browser_name == "firefox"
        assert d._headless is False

    def test_custom_options(self):
        d = SeleniumDriver(options={"disable_images": True})
        assert d._options == {"disable_images": True}


# ── Lifecycle ───────────────────────────────────────────────────


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_driver(self):
        mock_setup_cls = MagicMock()
        mock_instance = MagicMock()
        mock_wd = MagicMock()
        mock_instance.get_driver = AsyncMock(return_value=mock_wd)
        mock_setup_cls.return_value = mock_instance

        d = SeleniumDriver()
        # Patch the source module since SeleniumSetup is imported lazily
        with patch(
            "parrot.tools.scraping.driver.SeleniumSetup",
            mock_setup_cls,
        ):
            await d.start()

        assert d._driver is mock_wd
        assert d._setup is mock_instance
        mock_setup_cls.assert_called_once_with(
            browser="chrome",
            headless=True,
            auto_install=True,
            mobile=False,
        )

    @pytest.mark.asyncio
    async def test_quit_clears_state(self, started_driver, mock_webdriver):
        await started_driver.quit()
        mock_webdriver.quit.assert_called_once()
        assert started_driver._driver is None
        assert started_driver._setup is None

    @pytest.mark.asyncio
    async def test_quit_when_not_started(self, driver):
        """Quit gracefully when no resources were initialized."""
        await driver.quit()  # Should not raise


# ── Navigation ───────────────────────────────────────────────────


class TestNavigation:
    @pytest.mark.asyncio
    async def test_navigate(self, started_driver, mock_webdriver):
        await started_driver.navigate("https://example.com", timeout=15)
        mock_webdriver.set_page_load_timeout.assert_called_with(15)
        mock_webdriver.get.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_go_back(self, started_driver, mock_webdriver):
        await started_driver.go_back()
        mock_webdriver.back.assert_called_once()

    @pytest.mark.asyncio
    async def test_go_forward(self, started_driver, mock_webdriver):
        await started_driver.go_forward()
        mock_webdriver.forward.assert_called_once()

    @pytest.mark.asyncio
    async def test_reload(self, started_driver, mock_webdriver):
        await started_driver.reload()
        mock_webdriver.refresh.assert_called_once()


# ── DOM Interaction ──────────────────────────────────────────────


class TestDOMInteraction:
    @pytest.mark.asyncio
    async def test_click(self, started_driver, mock_webdriver, mock_element):
        mock_webdriver.find_element.return_value = mock_element
        # Patch the wait helper to avoid needing full Selenium imports
        with patch.object(started_driver, "_wait_for_element", new_callable=AsyncMock):
            await started_driver.click(".btn", timeout=5)
        mock_element.click.assert_called_once()

    @pytest.mark.asyncio
    async def test_fill(self, started_driver, mock_webdriver, mock_element):
        mock_webdriver.find_element.return_value = mock_element
        with patch.object(started_driver, "_wait_for_element", new_callable=AsyncMock):
            await started_driver.fill("#email", "test@example.com")
        mock_element.clear.assert_called_once()
        mock_element.send_keys.assert_called_once_with("test@example.com")

    @pytest.mark.asyncio
    async def test_select_option(self, started_driver, mock_webdriver, mock_element):
        mock_webdriver.find_element.return_value = mock_element
        with patch.object(started_driver, "_wait_for_element", new_callable=AsyncMock):
            with patch.object(started_driver, "_select_by_value") as mock_sel:
                await started_driver.select_option("select#size", "large")
        mock_sel.assert_called_once_with(mock_element, "large")

    @pytest.mark.asyncio
    async def test_hover(self, started_driver, mock_webdriver, mock_element):
        mock_webdriver.find_element.return_value = mock_element
        with patch.object(started_driver, "_wait_for_element", new_callable=AsyncMock):
            with patch.object(started_driver, "_hover_element") as mock_hov:
                await started_driver.hover(".menu-item")
        mock_hov.assert_called_once_with(mock_element)

    @pytest.mark.asyncio
    async def test_press_key(self, started_driver, mock_webdriver):
        with patch.object(started_driver, "_press_key_sync") as mock_pk:
            await started_driver.press_key("Enter")
        mock_pk.assert_called_once_with("Enter")


# ── Content Extraction ───────────────────────────────────────────


class TestContentExtraction:
    @pytest.mark.asyncio
    async def test_get_page_source(self, started_driver):
        result = await started_driver.get_page_source()
        assert result == "<html><body>Hello</body></html>"

    @pytest.mark.asyncio
    async def test_get_text(self, started_driver, mock_webdriver, mock_element):
        mock_webdriver.find_element.return_value = mock_element
        with patch.object(started_driver, "_wait_for_element", new_callable=AsyncMock):
            result = await started_driver.get_text("h1")
        assert result == "Hello World"

    @pytest.mark.asyncio
    async def test_get_attribute(self, started_driver, mock_webdriver, mock_element):
        mock_webdriver.find_element.return_value = mock_element
        with patch.object(started_driver, "_wait_for_element", new_callable=AsyncMock):
            result = await started_driver.get_attribute("a", "href")
        assert result == "https://link.com"
        mock_element.get_attribute.assert_called_once_with("href")

    @pytest.mark.asyncio
    async def test_get_all_texts(self, started_driver, mock_webdriver):
        el1 = MagicMock()
        el1.text = "one"
        el2 = MagicMock()
        el2.text = "two"
        mock_webdriver.find_elements.return_value = [el1, el2]
        with patch.object(started_driver, "_wait_for_element", new_callable=AsyncMock):
            result = await started_driver.get_all_texts("li")
        assert result == ["one", "two"]

    @pytest.mark.asyncio
    async def test_screenshot(self, started_driver, mock_webdriver):
        result = await started_driver.screenshot("/tmp/shot.png")
        assert result == b"\x89PNG"
        mock_webdriver.get_screenshot_as_png.assert_called_once()
        mock_webdriver.save_screenshot.assert_called_once_with("/tmp/shot.png")


# ── Scripts ──────────────────────────────────────────────────────


class TestScripts:
    @pytest.mark.asyncio
    async def test_execute_script(self, started_driver, mock_webdriver):
        mock_webdriver.execute_script.return_value = 42
        result = await started_driver.execute_script("return 1 + 1")
        assert result == 42
        mock_webdriver.execute_script.assert_called_once_with("return 1 + 1")

    @pytest.mark.asyncio
    async def test_evaluate(self, started_driver, mock_webdriver):
        mock_webdriver.execute_script.return_value = "Test Page"
        result = await started_driver.evaluate("document.title")
        assert result == "Test Page"
        mock_webdriver.execute_script.assert_called_once_with(
            "return document.title"
        )


# ── Property ─────────────────────────────────────────────────────


class TestCurrentUrl:
    def test_returns_driver_url(self, started_driver):
        assert started_driver.current_url == "https://example.com"

    def test_empty_when_no_driver(self, driver):
        assert driver.current_url == ""


# ── Extended Capabilities (inherited NotImplementedError) ────────


class TestExtendedCapabilities:
    @pytest.mark.asyncio
    async def test_intercept_requests_raises(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.intercept_requests(lambda r: r)

    @pytest.mark.asyncio
    async def test_record_har_raises(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.record_har("/tmp/test.har")

    @pytest.mark.asyncio
    async def test_save_pdf_raises(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.save_pdf("/tmp/test.pdf")

    @pytest.mark.asyncio
    async def test_start_tracing_raises(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.start_tracing()

    @pytest.mark.asyncio
    async def test_stop_tracing_raises(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.stop_tracing("/tmp/trace.zip")

    @pytest.mark.asyncio
    async def test_mock_route_raises(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.mock_route("**/*", lambda r: r)


# ── Lazy Import ──────────────────────────────────────────────────


class TestLazyImport:
    def test_module_loads_without_selenium(self):
        """Module can be imported without selenium installed."""
        from parrot.tools.scraping.drivers.selenium_driver import (
            SeleniumDriver as SD,
        )

        assert SD is not None
