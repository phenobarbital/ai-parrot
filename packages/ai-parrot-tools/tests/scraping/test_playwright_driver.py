"""Unit tests for PlaywrightDriver (TASK-058).

All Playwright API calls are mocked — no real browser is required.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock

from parrot.tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot.tools.scraping.drivers.playwright_config import PlaywrightConfig
from parrot.tools.scraping.drivers.abstract import AbstractDriver


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def driver():
    """PlaywrightDriver with default config (not started)."""
    return PlaywrightDriver()


@pytest.fixture
def mock_locator():
    """A mock Playwright Locator with async action methods."""
    locator = AsyncMock()
    locator.first = AsyncMock()
    locator.all = AsyncMock(return_value=[])
    return locator


@pytest.fixture
def mock_page(mock_locator):
    """A mock Playwright Page with common methods."""
    page = AsyncMock()
    page.url = "https://example.com"

    # locator() is synchronous in Playwright — returns a Locator object
    page.locator = MagicMock(return_value=mock_locator)

    # keyboard
    page.keyboard = AsyncMock()

    return page


@pytest.fixture
def mock_context():
    """A mock Playwright BrowserContext."""
    ctx = AsyncMock()
    ctx.tracing = AsyncMock()
    return ctx


@pytest.fixture
def started_driver(driver, mock_page, mock_context):
    """PlaywrightDriver with mocked internals (simulates started state)."""
    driver._page = mock_page
    driver._context = mock_context
    driver._browser = AsyncMock()
    driver._playwright = AsyncMock()
    return driver


# ── Identity Tests ───────────────────────────────────────────────


class TestPlaywrightDriverIsAbstractDriver:
    def test_isinstance(self, driver):
        assert isinstance(driver, AbstractDriver)

    def test_default_config(self, driver):
        assert driver.config.browser_type == "chromium"
        assert driver.config.headless is True

    def test_custom_config(self):
        config = PlaywrightConfig(browser_type="firefox", headless=False)
        d = PlaywrightDriver(config)
        assert d.config.browser_type == "firefox"
        assert d.config.headless is False


# ── Selector Resolution ─────────────────────────────────────────


class TestResolveSelector:
    def test_css_selector(self, driver):
        assert driver._resolve_selector("div.class") == "div.class"

    def test_css_id_selector(self, driver):
        assert driver._resolve_selector("#main") == "#main"

    def test_xpath_double_slash(self, driver):
        assert (
            driver._resolve_selector("//div[@id='main']")
            == "xpath=//div[@id='main']"
        )

    def test_xpath_dot_slash(self, driver):
        assert driver._resolve_selector("./div") == "xpath=./div"

    def test_plain_tag(self, driver):
        assert driver._resolve_selector("button") == "button"


# ── Context kwargs builder ───────────────────────────────────────


class TestBuildContextKwargs:
    def test_empty_config(self, driver):
        kwargs = driver._build_context_kwargs()
        assert kwargs == {}

    def test_viewport(self):
        config = PlaywrightConfig(viewport={"width": 1280, "height": 720})
        d = PlaywrightDriver(config)
        kwargs = d._build_context_kwargs()
        assert kwargs["viewport"] == {"width": 1280, "height": 720}

    def test_locale_and_timezone(self):
        config = PlaywrightConfig(locale="en-US", timezone="America/New_York")
        d = PlaywrightDriver(config)
        kwargs = d._build_context_kwargs()
        assert kwargs["locale"] == "en-US"
        assert kwargs["timezone_id"] == "America/New_York"

    def test_geolocation_and_permissions(self):
        config = PlaywrightConfig(
            geolocation={"latitude": 40.7, "longitude": -74.0},
            permissions=["geolocation"],
        )
        d = PlaywrightDriver(config)
        kwargs = d._build_context_kwargs()
        assert kwargs["geolocation"]["latitude"] == 40.7
        assert kwargs["permissions"] == ["geolocation"]

    def test_ignore_https_errors(self):
        config = PlaywrightConfig(ignore_https_errors=True)
        d = PlaywrightDriver(config)
        kwargs = d._build_context_kwargs()
        assert kwargs["ignore_https_errors"] is True

    def test_extra_http_headers(self):
        config = PlaywrightConfig(
            extra_http_headers={"X-Custom": "value"}
        )
        d = PlaywrightDriver(config)
        kwargs = d._build_context_kwargs()
        assert kwargs["extra_http_headers"]["X-Custom"] == "value"

    def test_http_credentials(self):
        config = PlaywrightConfig(
            http_credentials={"username": "u", "password": "p"}
        )
        d = PlaywrightDriver(config)
        kwargs = d._build_context_kwargs()
        assert kwargs["http_credentials"]["username"] == "u"

    def test_recording_paths(self):
        config = PlaywrightConfig(
            record_video_dir="/tmp/videos",
            record_har_path="/tmp/trace.har",
        )
        d = PlaywrightDriver(config)
        kwargs = d._build_context_kwargs()
        assert kwargs["record_video_dir"] == "/tmp/videos"
        assert kwargs["record_har_path"] == "/tmp/trace.har"

    def test_storage_state(self):
        config = PlaywrightConfig(storage_state="/tmp/state.json")
        d = PlaywrightDriver(config)
        kwargs = d._build_context_kwargs()
        assert kwargs["storage_state"] == "/tmp/state.json"

    def test_proxy(self):
        config = PlaywrightConfig(proxy={"server": "http://proxy:8080"})
        d = PlaywrightDriver(config)
        kwargs = d._build_context_kwargs()
        assert kwargs["proxy"]["server"] == "http://proxy:8080"

    def test_false_ignore_https_not_included(self, driver):
        """ignore_https_errors=False (default) is not included in kwargs."""
        kwargs = driver._build_context_kwargs()
        assert "ignore_https_errors" not in kwargs


# ── Navigation ───────────────────────────────────────────────────


class TestNavigation:
    @pytest.mark.asyncio
    async def test_navigate_timeout_conversion(self, started_driver):
        await started_driver.navigate("https://example.com", timeout=5)
        started_driver._page.goto.assert_called_once_with(
            "https://example.com", timeout=5000
        )

    @pytest.mark.asyncio
    async def test_navigate_default_timeout(self, started_driver):
        await started_driver.navigate("https://example.com")
        started_driver._page.goto.assert_called_once_with(
            "https://example.com", timeout=30000
        )

    @pytest.mark.asyncio
    async def test_go_back(self, started_driver):
        await started_driver.go_back()
        started_driver._page.go_back.assert_called_once()

    @pytest.mark.asyncio
    async def test_go_forward(self, started_driver):
        await started_driver.go_forward()
        started_driver._page.go_forward.assert_called_once()

    @pytest.mark.asyncio
    async def test_reload(self, started_driver):
        await started_driver.reload()
        started_driver._page.reload.assert_called_once()


# ── DOM Interaction ──────────────────────────────────────────────


class TestDOMInteraction:
    @pytest.mark.asyncio
    async def test_click(self, started_driver, mock_locator):
        await started_driver.click(".btn", timeout=5)
        started_driver._page.locator.assert_called_with(".btn")
        mock_locator.click.assert_called_once_with(timeout=5000)

    @pytest.mark.asyncio
    async def test_click_xpath(self, started_driver):
        await started_driver.click("//button[@id='go']")
        started_driver._page.locator.assert_called_with(
            "xpath=//button[@id='go']"
        )

    @pytest.mark.asyncio
    async def test_fill(self, started_driver, mock_locator):
        await started_driver.fill("#email", "test@example.com", timeout=3)
        started_driver._page.locator.assert_called_with("#email")
        mock_locator.fill.assert_called_once_with(
            "test@example.com", timeout=3000
        )

    @pytest.mark.asyncio
    async def test_select_option(self, started_driver, mock_locator):
        await started_driver.select_option("select#size", "large")
        started_driver._page.locator.assert_called_with("select#size")
        mock_locator.select_option.assert_called_once()

    @pytest.mark.asyncio
    async def test_hover(self, started_driver, mock_locator):
        await started_driver.hover(".menu-item")
        started_driver._page.locator.assert_called_with(".menu-item")
        mock_locator.hover.assert_called_once()

    @pytest.mark.asyncio
    async def test_press_key(self, started_driver):
        await started_driver.press_key("Enter")
        started_driver._page.keyboard.press.assert_called_once_with("Enter")


# ── Content Extraction ───────────────────────────────────────────


class TestContentExtraction:
    @pytest.mark.asyncio
    async def test_get_page_source(self, started_driver):
        started_driver._page.content.return_value = "<html></html>"
        result = await started_driver.get_page_source()
        assert result == "<html></html>"

    @pytest.mark.asyncio
    async def test_get_text(self, started_driver, mock_locator):
        mock_locator.inner_text.return_value = "Hello"
        result = await started_driver.get_text("h1")
        started_driver._page.locator.assert_called_with("h1")
        mock_locator.inner_text.assert_called_once_with(timeout=10000)
        assert result == "Hello"

    @pytest.mark.asyncio
    async def test_get_attribute(self, started_driver, mock_locator):
        mock_locator.get_attribute.return_value = "https://link.com"
        result = await started_driver.get_attribute("a", "href")
        started_driver._page.locator.assert_called_with("a")
        mock_locator.get_attribute.assert_called_once_with(
            "href", timeout=10000
        )
        assert result == "https://link.com"

    @pytest.mark.asyncio
    async def test_screenshot(self, started_driver):
        started_driver._page.screenshot.return_value = b"\x89PNG"
        result = await started_driver.screenshot("/tmp/shot.png", full_page=True)
        assert result == b"\x89PNG"
        started_driver._page.screenshot.assert_called_once_with(
            path="/tmp/shot.png", full_page=True
        )


# ── Waiting ──────────────────────────────────────────────────────


class TestWaiting:
    @pytest.mark.asyncio
    async def test_wait_for_selector(self, started_driver):
        await started_driver.wait_for_selector(".loaded", timeout=5)
        started_driver._page.wait_for_selector.assert_called_once_with(
            ".loaded", timeout=5000, state="visible"
        )

    @pytest.mark.asyncio
    async def test_wait_for_selector_hidden(self, started_driver):
        await started_driver.wait_for_selector(
            ".spinner", timeout=10, state="hidden"
        )
        started_driver._page.wait_for_selector.assert_called_once_with(
            ".spinner", timeout=10000, state="hidden"
        )

    @pytest.mark.asyncio
    async def test_wait_for_navigation(self, started_driver):
        await started_driver.wait_for_navigation(timeout=15)
        started_driver._page.wait_for_load_state.assert_called_once_with(
            "domcontentloaded", timeout=15000
        )

    @pytest.mark.asyncio
    async def test_wait_for_load_state(self, started_driver):
        await started_driver.wait_for_load_state("networkidle", timeout=20)
        started_driver._page.wait_for_load_state.assert_called_once_with(
            "networkidle", timeout=20000
        )


# ── Scripts ──────────────────────────────────────────────────────


class TestScripts:
    @pytest.mark.asyncio
    async def test_execute_script(self, started_driver):
        started_driver._page.evaluate.return_value = 42
        result = await started_driver.execute_script("1 + 1")
        assert result == 42

    @pytest.mark.asyncio
    async def test_evaluate(self, started_driver):
        started_driver._page.evaluate.return_value = "hello"
        result = await started_driver.evaluate("document.title")
        assert result == "hello"


# ── Property ─────────────────────────────────────────────────────


class TestCurrentUrl:
    def test_returns_page_url(self, started_driver):
        started_driver._page.url = "https://example.com/page"
        assert started_driver.current_url == "https://example.com/page"


# ── Extended Capabilities (Playwright-exclusive) ─────────────────


class TestInterceptRequests:
    @pytest.mark.asyncio
    async def test_registers_handler(self, started_driver):
        handler = AsyncMock()
        await started_driver.intercept_requests(handler)
        started_driver._page.route.assert_called_once_with("**/*", handler)


class TestInterceptByResourceType:
    @pytest.mark.asyncio
    async def test_registers_route(self, started_driver):
        await started_driver.intercept_by_resource_type(
            ["image", "stylesheet"]
        )
        started_driver._page.route.assert_called_once()
        args = started_driver._page.route.call_args
        assert args[0][0] == "**/*"


class TestMockRoute:
    @pytest.mark.asyncio
    async def test_registers_pattern_handler(self, started_driver):
        handler = AsyncMock()
        await started_driver.mock_route("**/api/data", handler)
        started_driver._page.route.assert_called_once_with(
            "**/api/data", handler
        )


class TestSavePdf:
    @pytest.mark.asyncio
    async def test_chromium_succeeds(self, started_driver):
        started_driver._page.pdf.return_value = b"%PDF-1.4"
        result = await started_driver.save_pdf("/tmp/out.pdf")
        assert result == b"%PDF-1.4"
        started_driver._page.pdf.assert_called_once_with(path="/tmp/out.pdf")

    @pytest.mark.asyncio
    async def test_firefox_raises(self):
        config = PlaywrightConfig(browser_type="firefox")
        d = PlaywrightDriver(config)
        d._page = AsyncMock()
        with pytest.raises(ValueError, match="chromium"):
            await d.save_pdf("/tmp/out.pdf")

    @pytest.mark.asyncio
    async def test_webkit_raises(self):
        config = PlaywrightConfig(browser_type="webkit")
        d = PlaywrightDriver(config)
        d._page = AsyncMock()
        with pytest.raises(ValueError, match="chromium"):
            await d.save_pdf("/tmp/out.pdf")


class TestTracing:
    @pytest.mark.asyncio
    async def test_start_tracing(self, started_driver):
        await started_driver.start_tracing(
            name="test", screenshots=True, snapshots=False
        )
        started_driver._context.tracing.start.assert_called_once_with(
            name="test", screenshots=True, snapshots=False
        )

    @pytest.mark.asyncio
    async def test_stop_tracing(self, started_driver):
        await started_driver.stop_tracing("/tmp/trace.zip")
        started_driver._context.tracing.stop.assert_called_once_with(
            path="/tmp/trace.zip"
        )


class TestSaveStorageState:
    @pytest.mark.asyncio
    async def test_calls_context(self, started_driver):
        await started_driver.save_storage_state("/tmp/state.json")
        started_driver._context.storage_state.assert_called_once_with(
            path="/tmp/state.json"
        )


class TestNewPage:
    @pytest.mark.asyncio
    async def test_creates_new_page(self, started_driver):
        new_page = AsyncMock()
        started_driver._context.new_page.return_value = new_page
        result = await started_driver.new_page()
        assert result is new_page
        assert started_driver._page is new_page


class TestGetNetworkResponses:
    @pytest.mark.asyncio
    async def test_returns_captured_responses(self, started_driver):
        started_driver._responses = [
            {"url": "https://api.com/data", "status": 200, "body": "ok"}
        ]
        result = await started_driver.get_network_responses()
        assert len(result) == 1
        assert result[0]["url"] == "https://api.com/data"

    @pytest.mark.asyncio
    async def test_returns_copy(self, started_driver):
        started_driver._responses = [{"url": "a"}]
        result = await started_driver.get_network_responses()
        result.append({"url": "b"})
        assert len(started_driver._responses) == 1


# ── Quit / Cleanup ───────────────────────────────────────────────


class TestQuit:
    @pytest.mark.asyncio
    async def test_closes_all_resources(self, started_driver):
        # Capture references before quit() sets them to None
        context = started_driver._context
        browser = started_driver._browser
        playwright = started_driver._playwright
        await started_driver.quit()
        context.close.assert_called_once()
        browser.close.assert_called_once()
        playwright.stop.assert_called_once()
        assert started_driver._page is None
        assert started_driver._context is None
        assert started_driver._browser is None
        assert started_driver._playwright is None

    @pytest.mark.asyncio
    async def test_quit_when_not_started(self, driver):
        """Quit gracefully when no resources were initialized."""
        await driver.quit()  # Should not raise


# ── Lazy Import ──────────────────────────────────────────────────


class TestLazyImport:
    def test_module_loads_without_playwright(self):
        """Module can be imported without playwright installed."""
        from parrot.tools.scraping.drivers.playwright_driver import (
            PlaywrightDriver as PD,
        )

        assert PD is not None
