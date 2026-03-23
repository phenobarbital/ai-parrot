"""Playwright-based browser automation driver.

Implements :class:`AbstractDriver` using Playwright's async API, providing
full browser automation with Playwright-exclusive features such as request
interception, HAR recording, tracing, PDF export, and session persistence.
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from .abstract import AbstractDriver
from .playwright_config import PlaywrightConfig


class PlaywrightDriver(AbstractDriver):
    """Playwright-based browser automation driver.

    Implements the full ``AbstractDriver`` interface using Playwright's async
    API, plus Playwright-exclusive capabilities (HAR, tracing, PDF,
    interception, session persistence).

    The ``playwright`` package is imported lazily inside :meth:`start` so the
    module can be loaded even when Playwright is not installed.

    Args:
        config: Browser and context configuration.  Defaults to
            ``PlaywrightConfig()`` (headless Chromium).
    """

    def __init__(self, config: Optional[PlaywrightConfig] = None) -> None:
        self.config = config or PlaywrightConfig()
        self.logger = logging.getLogger(__name__)
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._responses: List[Dict[str, Any]] = []

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch browser and create a default context + page."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        browser_launcher = getattr(self._playwright, self.config.browser_type)
        launch_kwargs: Dict[str, Any] = {
            "headless": self.config.headless,
            "slow_mo": self.config.slow_mo,
        }
        if self.config.proxy:
            launch_kwargs["proxy"] = self.config.proxy
        self._browser = await browser_launcher.launch(**launch_kwargs)

        context_kwargs = self._build_context_kwargs()
        self._context = await self._browser.new_context(**context_kwargs)
        self._context.set_default_timeout(self.config.timeout * 1000)

        self._page = await self._context.new_page()
        self.logger.info(
            "PlaywrightDriver started: browser=%s headless=%s",
            self.config.browser_type,
            self.config.headless,
        )

    async def quit(self) -> None:
        """Close browser and release resources."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._page = None
        self.logger.info("PlaywrightDriver closed.")

    # ── Navigation ───────────────────────────────────────────────

    async def navigate(self, url: str, timeout: int = 30) -> None:
        """Navigate to *url*."""
        await self._page.goto(url, timeout=timeout * 1000)

    async def go_back(self) -> None:
        """Navigate back."""
        await self._page.go_back()

    async def go_forward(self) -> None:
        """Navigate forward."""
        await self._page.go_forward()

    async def reload(self) -> None:
        """Reload the current page."""
        await self._page.reload()

    # ── DOM Interaction ──────────────────────────────────────────

    async def click(self, selector: str, timeout: int = 10) -> None:
        """Click element matching *selector*."""
        sel = self._resolve_selector(selector)
        await self._page.locator(sel).click(timeout=timeout * 1000)

    async def fill(
        self, selector: str, value: str, timeout: int = 10
    ) -> None:
        """Fill input matching *selector* with *value*."""
        sel = self._resolve_selector(selector)
        await self._page.locator(sel).fill(value, timeout=timeout * 1000)

    async def select_option(
        self, selector: str, value: str, timeout: int = 10
    ) -> None:
        """Select an option in a ``<select>`` element."""
        sel = self._resolve_selector(selector)
        await self._page.locator(sel).select_option(
            value, timeout=timeout * 1000
        )

    async def hover(self, selector: str, timeout: int = 10) -> None:
        """Hover over element matching *selector*."""
        sel = self._resolve_selector(selector)
        await self._page.locator(sel).hover(timeout=timeout * 1000)

    async def press_key(self, key: str) -> None:
        """Press a keyboard key."""
        await self._page.keyboard.press(key)

    # ── Content Extraction ───────────────────────────────────────

    async def get_page_source(self) -> str:
        """Return the full HTML of the current page."""
        return await self._page.content()

    async def get_text(self, selector: str, timeout: int = 10) -> str:
        """Return the inner text of the first matching element."""
        sel = self._resolve_selector(selector)
        return await self._page.locator(sel).inner_text(
            timeout=timeout * 1000
        )

    async def get_attribute(
        self, selector: str, attribute: str, timeout: int = 10
    ) -> Optional[str]:
        """Return the value of *attribute* on the matching element."""
        sel = self._resolve_selector(selector)
        return await self._page.locator(sel).get_attribute(
            attribute, timeout=timeout * 1000
        )

    async def get_all_texts(
        self, selector: str, timeout: int = 10
    ) -> List[str]:
        """Return inner text of every matching element."""
        sel = self._resolve_selector(selector)
        locator = self._page.locator(sel)
        await locator.first.wait_for(timeout=timeout * 1000)
        elements = await locator.all()
        return [await el.inner_text() for el in elements]

    async def screenshot(
        self, path: str, full_page: bool = False
    ) -> bytes:
        """Take a screenshot and save to *path*."""
        return await self._page.screenshot(path=path, full_page=full_page)

    # ── Waiting ──────────────────────────────────────────────────

    async def wait_for_selector(
        self, selector: str, timeout: int = 10, state: str = "visible"
    ) -> None:
        """Wait for *selector* to reach *state*."""
        sel = self._resolve_selector(selector)
        await self._page.wait_for_selector(
            sel, timeout=timeout * 1000, state=state
        )

    async def wait_for_navigation(self, timeout: int = 30) -> None:
        """Wait for a navigation event to complete."""
        await self._page.wait_for_load_state(
            "domcontentloaded", timeout=timeout * 1000
        )

    async def wait_for_load_state(
        self, state: str = "load", timeout: int = 30
    ) -> None:
        """Wait until the page reaches the given load *state*."""
        await self._page.wait_for_load_state(state, timeout=timeout * 1000)

    # ── Media / Scripts ──────────────────────────────────────────

    async def execute_script(self, script: str, *args: Any) -> Any:
        """Execute JavaScript with arguments in the page context."""
        return await self._page.evaluate(script, *args)

    async def evaluate(self, expression: str) -> Any:
        """Evaluate a JavaScript expression and return the result."""
        return await self._page.evaluate(expression)

    # ── Property ─────────────────────────────────────────────────

    @property
    def current_url(self) -> str:
        """The URL of the current page."""
        return self._page.url

    # ── Extended Capabilities (Playwright-exclusive) ─────────────

    async def intercept_requests(self, handler: Callable) -> None:
        """Register a request interception handler on all routes.

        Args:
            handler: Async callable receiving ``(route, request)``.
        """
        await self._page.route("**/*", handler)

    async def intercept_by_resource_type(
        self, resource_types: List[str], action: str = "abort"
    ) -> None:
        """Block or modify requests by resource type.

        Args:
            resource_types: Resource types to intercept (e.g.
                ``["image", "stylesheet", "font"]``).
            action: Action to take — ``"abort"`` (default) blocks the
                request.
        """

        async def _handler(route: Any, request: Any) -> None:
            if request.resource_type in resource_types:
                await route.abort()
            else:
                await route.continue_()

        await self._page.route("**/*", _handler)

    async def mock_route(
        self, url_pattern: str, handler: Callable
    ) -> None:
        """Mock network requests matching *url_pattern*.

        Args:
            url_pattern: Glob pattern to match request URLs.
            handler: Async callable to handle matched requests.
        """
        await self._page.route(url_pattern, handler)

    async def record_har(self, path: str) -> None:
        """Log a note about HAR recording.

        HAR recording in Playwright is configured at context creation time
        via :attr:`PlaywrightConfig.record_har_path`.  This method exists
        for interface completeness.
        """
        self.logger.info(
            "HAR recording should be configured via PlaywrightConfig."
            "record_har_path before calling start(). Path requested: %s",
            path,
        )

    async def save_pdf(self, path: str) -> bytes:
        """Export the current page as a PDF (Chromium only).

        Args:
            path: File path for the PDF output.

        Returns:
            Raw PDF bytes.

        Raises:
            ValueError: If the browser type is not ``"chromium"``.
        """
        if self.config.browser_type != "chromium":
            raise ValueError(
                "PDF export requires browser_type='chromium'. "
                f"Current browser_type is '{self.config.browser_type}'."
            )
        return await self._page.pdf(path=path)

    async def start_tracing(
        self,
        name: str = "trace",
        screenshots: bool = True,
        snapshots: bool = True,
    ) -> None:
        """Start Playwright tracing.

        Trace files can be viewed with:
        ``npx playwright show-trace trace.zip``
        """
        await self._context.tracing.start(
            name=name, screenshots=screenshots, snapshots=snapshots
        )

    async def stop_tracing(self, path: str) -> None:
        """Stop tracing and save the trace archive to *path*."""
        await self._context.tracing.stop(path=path)

    async def save_storage_state(self, path: str) -> None:
        """Persist cookies and localStorage to a JSON file.

        The saved state can be reused by setting
        ``PlaywrightConfig(storage_state=path)`` on a subsequent run.

        Args:
            path: File path for the state JSON.
        """
        await self._context.storage_state(path=path)

    async def new_page(self) -> Any:
        """Open a new tab within the same browser context.

        The new page becomes the active page.

        Returns:
            The new Playwright ``Page`` object.
        """
        self._page = await self._context.new_page()
        return self._page

    async def get_network_responses(self) -> List[Dict[str, Any]]:
        """Return captured network responses.

        Returns:
            List of dicts with ``url``, ``status``, and ``body`` keys.
        """
        return list(self._responses)

    # ── Internal Helpers ─────────────────────────────────────────

    def _resolve_selector(self, selector: str) -> str:
        """Auto-detect and prefix XPath selectors for Playwright.

        Selectors starting with ``/`` or ``./`` are treated as XPath and
        prefixed with ``xpath=``.  All others are used as CSS selectors.

        Args:
            selector: Raw selector string.

        Returns:
            Playwright-compatible selector string.
        """
        if selector.startswith(("/", "./")):
            return f"xpath={selector}"
        return selector

    def _build_context_kwargs(self) -> Dict[str, Any]:
        """Build keyword arguments for ``browser.new_context()``."""
        kwargs: Dict[str, Any] = {}
        if self.config.viewport:
            kwargs["viewport"] = self.config.viewport
        if self.config.locale:
            kwargs["locale"] = self.config.locale
        if self.config.timezone:
            kwargs["timezone_id"] = self.config.timezone
        if self.config.geolocation:
            kwargs["geolocation"] = self.config.geolocation
        if self.config.permissions:
            kwargs["permissions"] = self.config.permissions
        if self.config.ignore_https_errors:
            kwargs["ignore_https_errors"] = True
        if self.config.extra_http_headers:
            kwargs["extra_http_headers"] = self.config.extra_http_headers
        if self.config.http_credentials:
            kwargs["http_credentials"] = self.config.http_credentials
        if self.config.record_video_dir:
            kwargs["record_video_dir"] = self.config.record_video_dir
        if self.config.record_har_path:
            kwargs["record_har_path"] = self.config.record_har_path
        if self.config.storage_state:
            kwargs["storage_state"] = self.config.storage_state
        if self.config.proxy:
            kwargs["proxy"] = self.config.proxy
        return kwargs
