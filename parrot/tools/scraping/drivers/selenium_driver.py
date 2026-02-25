"""Selenium-based browser automation driver.

Wraps the existing :class:`SeleniumSetup` class to implement the
:class:`AbstractDriver` interface.  All blocking Selenium WebDriver calls
are dispatched via :func:`asyncio.get_event_loop().run_in_executor` so the
async event loop is never blocked.

The ``selenium`` package is imported lazily inside :meth:`start` so the
module can be loaded even when Selenium is not installed.
"""

import asyncio
import logging
from functools import partial
from typing import Any, Dict, List, Optional

from .abstract import AbstractDriver


class SeleniumDriver(AbstractDriver):
    """Selenium-based browser automation driver.

    Wraps the existing ``SeleniumSetup`` class to implement the full
    ``AbstractDriver`` interface.  All blocking Selenium calls are run
    via ``run_in_executor`` to avoid blocking the async event loop.

    Extended capability methods (HAR, tracing, PDF, interception) are
    **not** overridden — the base-class defaults raise
    ``NotImplementedError``.

    Args:
        browser: Browser name (``"chrome"``, ``"firefox"``, ``"edge"``,
            ``"safari"``, ``"undetected"``).
        headless: Whether to run in headless mode.
        auto_install: Whether to auto-install the browser driver.
        mobile: Whether to emulate a mobile viewport.
        options: Additional keyword arguments forwarded to
            ``SeleniumSetup``.
    """

    def __init__(
        self,
        browser: str = "chrome",
        headless: bool = True,
        auto_install: bool = True,
        mobile: bool = False,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._browser_name = browser
        self._headless = headless
        self._auto_install = auto_install
        self._mobile = mobile
        self._options = options or {}
        self._setup: Any = None  # SeleniumSetup instance
        self._driver: Any = None  # WebDriver instance
        self.logger = logging.getLogger(__name__)

    # ── Internal helper ───────────────────────────────────────────

    async def _run(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking function in the default executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, partial(func, *args, **kwargs)
        )

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch browser via ``SeleniumSetup`` and store the WebDriver."""
        from parrot.tools.scraping.driver import SeleniumSetup

        self._setup = SeleniumSetup(
            browser=self._browser_name,
            headless=self._headless,
            auto_install=self._auto_install,
            mobile=self._mobile,
            **self._options,
        )
        # get_driver() is already async (uses run_in_executor internally)
        self._driver = await self._setup.get_driver()
        self.logger.info(
            "SeleniumDriver started: browser=%s headless=%s",
            self._browser_name,
            self._headless,
        )

    async def quit(self) -> None:
        """Close browser and release resources."""
        if self._driver:
            await self._run(self._driver.quit)
            self._driver = None
            self._setup = None
        self.logger.info("SeleniumDriver closed.")

    # ── Navigation ───────────────────────────────────────────────

    async def navigate(self, url: str, timeout: int = 30) -> None:
        """Navigate to *url*."""
        self._driver.set_page_load_timeout(timeout)
        await self._run(self._driver.get, url)

    async def go_back(self) -> None:
        """Navigate back."""
        await self._run(self._driver.back)

    async def go_forward(self) -> None:
        """Navigate forward."""
        await self._run(self._driver.forward)

    async def reload(self) -> None:
        """Reload the current page."""
        await self._run(self._driver.refresh)

    # ── DOM Interaction ──────────────────────────────────────────

    def _find_element(self, selector: str) -> Any:
        """Find a single element by CSS selector or XPath (blocking)."""
        from selenium.webdriver.common.by import By

        if selector.startswith(("/", "./")):
            return self._driver.find_element(By.XPATH, selector)
        return self._driver.find_element(By.CSS_SELECTOR, selector)

    def _find_elements(self, selector: str) -> List[Any]:
        """Find all matching elements by CSS selector or XPath (blocking)."""
        from selenium.webdriver.common.by import By

        if selector.startswith(("/", "./")):
            return self._driver.find_elements(By.XPATH, selector)
        return self._driver.find_elements(By.CSS_SELECTOR, selector)

    async def click(self, selector: str, timeout: int = 10) -> None:
        """Click element matching *selector*."""
        await self._wait_for_element(selector, timeout)
        element = await self._run(self._find_element, selector)
        await self._run(element.click)

    async def fill(
        self, selector: str, value: str, timeout: int = 10
    ) -> None:
        """Fill input matching *selector* with *value*."""
        await self._wait_for_element(selector, timeout)
        element = await self._run(self._find_element, selector)
        await self._run(element.clear)
        await self._run(element.send_keys, value)

    async def select_option(
        self, selector: str, value: str, timeout: int = 10
    ) -> None:
        """Select an option in a ``<select>`` element."""
        await self._wait_for_element(selector, timeout)
        element = await self._run(self._find_element, selector)
        await self._run(self._select_by_value, element, value)

    def _select_by_value(self, element: Any, value: str) -> None:
        """Blocking: select option by value using Selenium Select."""
        from selenium.webdriver.support.ui import Select

        Select(element).select_by_value(value)

    async def hover(self, selector: str, timeout: int = 10) -> None:
        """Hover over element matching *selector*."""
        await self._wait_for_element(selector, timeout)
        element = await self._run(self._find_element, selector)
        await self._run(self._hover_element, element)

    def _hover_element(self, element: Any) -> None:
        """Blocking: hover over an element using ActionChains."""
        from selenium.webdriver.common.action_chains import ActionChains

        ActionChains(self._driver).move_to_element(element).perform()

    async def press_key(self, key: str) -> None:
        """Press a keyboard key."""
        await self._run(self._press_key_sync, key)

    def _press_key_sync(self, key: str) -> None:
        """Blocking: press a keyboard key using ActionChains."""
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.keys import Keys

        key_map = {
            "Enter": Keys.ENTER,
            "Tab": Keys.TAB,
            "Escape": Keys.ESCAPE,
            "Backspace": Keys.BACKSPACE,
            "Delete": Keys.DELETE,
            "ArrowUp": Keys.ARROW_UP,
            "ArrowDown": Keys.ARROW_DOWN,
            "ArrowLeft": Keys.ARROW_LEFT,
            "ArrowRight": Keys.ARROW_RIGHT,
            "Space": Keys.SPACE,
        }
        selenium_key = key_map.get(key, key)
        ActionChains(self._driver).send_keys(selenium_key).perform()

    # ── Content Extraction ───────────────────────────────────────

    async def get_page_source(self) -> str:
        """Return the full HTML of the current page."""
        return await self._run(lambda: self._driver.page_source)

    async def get_text(self, selector: str, timeout: int = 10) -> str:
        """Return the inner text of the first matching element."""
        await self._wait_for_element(selector, timeout)
        element = await self._run(self._find_element, selector)
        return await self._run(lambda: element.text)

    async def get_attribute(
        self, selector: str, attribute: str, timeout: int = 10
    ) -> Optional[str]:
        """Return the value of *attribute* on the matching element."""
        await self._wait_for_element(selector, timeout)
        element = await self._run(self._find_element, selector)
        return await self._run(element.get_attribute, attribute)

    async def get_all_texts(
        self, selector: str, timeout: int = 10
    ) -> List[str]:
        """Return inner text of every matching element."""
        await self._wait_for_element(selector, timeout)
        elements = await self._run(self._find_elements, selector)
        return [await self._run(lambda el=el: el.text) for el in elements]

    async def screenshot(
        self, path: str, full_page: bool = False
    ) -> bytes:
        """Take a screenshot and save to *path*."""
        png_bytes = await self._run(self._driver.get_screenshot_as_png)
        await self._run(self._driver.save_screenshot, path)
        return png_bytes

    # ── Waiting ──────────────────────────────────────────────────

    async def _wait_for_element(
        self, selector: str, timeout: int = 10
    ) -> None:
        """Internal: wait for element to be present in the DOM."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if selector.startswith(("/", "./")):
            locator = (By.XPATH, selector)
        else:
            locator = (By.CSS_SELECTOR, selector)

        await self._run(
            WebDriverWait(self._driver, timeout).until,
            EC.presence_of_element_located(locator),
        )

    async def wait_for_selector(
        self, selector: str, timeout: int = 10, state: str = "visible"
    ) -> None:
        """Wait for *selector* to reach *state*."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        if selector.startswith(("/", "./")):
            locator = (By.XPATH, selector)
        else:
            locator = (By.CSS_SELECTOR, selector)

        condition_map = {
            "visible": EC.visibility_of_element_located,
            "hidden": EC.invisibility_of_element_located,
            "attached": EC.presence_of_element_located,
            "detached": EC.staleness_of,
        }
        condition_factory = condition_map.get(
            state, EC.visibility_of_element_located
        )
        condition = condition_factory(locator)
        await self._run(
            WebDriverWait(self._driver, timeout).until, condition
        )

    async def wait_for_navigation(self, timeout: int = 30) -> None:
        """Wait for a navigation event to complete."""
        from selenium.webdriver.support.ui import WebDriverWait

        def _ready(driver: Any) -> bool:
            return driver.execute_script("return document.readyState") == "complete"

        await self._run(
            WebDriverWait(self._driver, timeout).until, _ready
        )

    async def wait_for_load_state(
        self, state: str = "load", timeout: int = 30
    ) -> None:
        """Wait until the page reaches the given load *state*."""
        from selenium.webdriver.support.ui import WebDriverWait

        state_map = {
            "load": "complete",
            "domcontentloaded": "interactive",
            "networkidle": "complete",
        }
        target = state_map.get(state, "complete")

        def _check(driver: Any) -> bool:
            ready = driver.execute_script("return document.readyState")
            if target == "interactive":
                return ready in ("interactive", "complete")
            return ready == target

        await self._run(
            WebDriverWait(self._driver, timeout).until, _check
        )

    # ── Media / Scripts ──────────────────────────────────────────

    async def execute_script(self, script: str, *args: Any) -> Any:
        """Execute JavaScript with arguments in the page context."""
        return await self._run(self._driver.execute_script, script, *args)

    async def evaluate(self, expression: str) -> Any:
        """Evaluate a JavaScript expression and return the result."""
        return await self._run(
            self._driver.execute_script, f"return {expression}"
        )

    # ── Property ─────────────────────────────────────────────────

    @property
    def current_url(self) -> str:
        """The URL of the current page."""
        if self._driver:
            return self._driver.current_url
        return ""
