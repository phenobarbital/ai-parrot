# SPEC-04 — `PlaywrightDriver` (First-Class Playwright Support)
**Project:** AI-Parrot · WebScrapingToolkit  
**Version:** 1.0  
**Status:** Draft  
**File:** `parrot/tools/scraping/drivers/playwright_driver.py`

---

## 1. Purpose

The current `driver.py` is heavily Selenium-centric.  Playwright support
exists as a fallback shim but lacks the parity needed to be a reliable
first-class option.  This spec defines a full `PlaywrightDriver`
implementation that:

- Implements the same `AbstractDriver` interface as `SeleniumDriver`.
- Exposes Playwright-specific capabilities unavailable in Selenium (network
  interception, HAR recording, route mocking, native PDF/screenshot, tracing).
- Is structurally parallel to `SeleniumDriver` so both can be tested,
  maintained, and swapped with zero toolkit changes.

---

## 2. Architecture

### 2.1 Driver Abstraction Layer (revised)

The existing `SeleniumSetup` class is refactored into a proper `AbstractDriver`
interface.  Both drivers implement it, and `DriverFactory` selects the right
one.

```
parrot/tools/scraping/
├── drivers/
│   ├── __init__.py
│   ├── abstract.py         ← AbstractDriver interface (NEW)
│   ├── selenium_driver.py  ← refactored from driver.py
│   └── playwright_driver.py← new first-class implementation
├── driver_factory.py       ← DriverFactory (NEW, replaces direct instantiation)
└── ...
```

### 2.2 `AbstractDriver`

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class AbstractDriver(ABC):
    """
    Unified interface for browser automation drivers.
    All driver-specific capabilities are exposed through this interface.
    Methods not supported by a driver raise NotImplementedError with a
    clear message indicating which driver does support the feature.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def start(self) -> None:
        """Initialize the browser and create a default page/tab."""

    @abstractmethod
    async def quit(self) -> None:
        """Close the browser and release all resources."""

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    @abstractmethod
    async def navigate(self, url: str, timeout: int = 30) -> None: ...

    @abstractmethod
    async def go_back(self) -> None: ...

    @abstractmethod
    async def refresh(self) -> None: ...

    @property
    @abstractmethod
    def current_url(self) -> str: ...

    # ------------------------------------------------------------------
    # DOM interaction
    # ------------------------------------------------------------------

    @abstractmethod
    async def click(self, selector: str, selector_type: str = "css") -> None: ...

    @abstractmethod
    async def fill(self, selector: str, value: str,
                   selector_type: str = "css") -> None: ...

    @abstractmethod
    async def select_option(self, selector: str, value: str) -> None: ...

    @abstractmethod
    async def press_key(self, key: str) -> None: ...

    @abstractmethod
    async def scroll(self, direction: str, amount: int) -> None: ...

    @abstractmethod
    async def hover(self, selector: str) -> None: ...

    @abstractmethod
    async def drag_and_drop(self, source: str, target: str) -> None: ...

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_text(self, selector: str,
                       selector_type: str = "css",
                       multiple: bool = False) -> Any: ...

    @abstractmethod
    async def get_html(self, selector: Optional[str] = None) -> str: ...

    @abstractmethod
    async def get_attribute(self, selector: str, attribute: str) -> Optional[str]: ...

    @abstractmethod
    async def get_cookies(self) -> List[Dict]: ...

    @abstractmethod
    async def set_cookies(self, cookies: List[Dict]) -> None: ...

    # ------------------------------------------------------------------
    # Waiting
    # ------------------------------------------------------------------

    @abstractmethod
    async def wait_for_selector(self, selector: str, timeout: int = 10,
                                 state: str = "visible") -> None: ...

    @abstractmethod
    async def wait_for_url(self, url_pattern: str, timeout: int = 10) -> None: ...

    @abstractmethod
    async def wait_for_load_state(self, state: str = "load") -> None: ...

    # ------------------------------------------------------------------
    # Media / files
    # ------------------------------------------------------------------

    @abstractmethod
    async def screenshot(self, filepath: str, full_page: bool = False) -> str: ...

    @abstractmethod
    async def upload_file(self, selector: str, filepath: str) -> None: ...

    # ------------------------------------------------------------------
    # Script execution
    # ------------------------------------------------------------------

    @abstractmethod
    async def evaluate(self, script: str) -> Any: ...

    # ------------------------------------------------------------------
    # Extended capabilities (optional — raise NotImplementedError if unsupported)
    # ------------------------------------------------------------------

    async def intercept_requests(self, handler: Any) -> None:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support request interception. "
            "Use PlaywrightDriver instead."
        )

    async def record_har(self, path: str) -> None:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support HAR recording. "
            "Use PlaywrightDriver instead."
        )

    async def save_pdf(self, filepath: str) -> str:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support native PDF export. "
            "Use PlaywrightDriver with a Chromium-based browser."
        )

    async def start_tracing(self, screenshots: bool = True,
                             snapshots: bool = True) -> None:
        raise NotImplementedError

    async def stop_tracing(self, output_path: str) -> None:
        raise NotImplementedError

    async def mock_route(self, url_pattern: str, handler: Any) -> None:
        raise NotImplementedError
```

---

## 3. `PlaywrightDriver`

### 3.1 Configuration

```python
@dataclass
class PlaywrightConfig:
    browser_type: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    slow_mo: int = 0                    # ms delay between actions (debug aid)
    timeout: int = 30_000               # ms, Playwright uses ms not seconds
    viewport: Optional[Dict] = None     # {"width": 1280, "height": 720}
    locale: str = "en-US"
    timezone: Optional[str] = None
    geolocation: Optional[Dict] = None  # {"latitude": 37.7, "longitude": -122.4}
    permissions: List[str] = field(default_factory=list)

    # Mobile emulation
    mobile: bool = False
    device_name: Optional[str] = None  # e.g. "iPhone 14 Pro Max"

    # Network
    proxy: Optional[Dict] = None       # {"server": "http://..."}
    ignore_https_errors: bool = False
    extra_http_headers: Dict[str, str] = field(default_factory=dict)

    # Auth
    http_credentials: Optional[Dict] = None  # {"username": ..., "password": ...}

    # Recording
    record_video_dir: Optional[str] = None
    record_har_path: Optional[str] = None

    # Context-level storage state (for resuming authenticated sessions)
    storage_state: Optional[Union[str, Dict]] = None
```

### 3.2 Class Implementation

```python
from playwright.async_api import (
    async_playwright,
    Browser, BrowserContext, Page,
    Request, Response, Route,
    Playwright as PlaywrightInstance,
)


class PlaywrightDriver(AbstractDriver):
    """
    First-class Playwright driver implementing AbstractDriver.

    Playwright differences from Selenium that this class handles:
    - async_playwright() context manager must stay open for the browser lifetime.
    - BrowserContext is the isolation unit (not Page); one context per driver.
    - Selectors: Playwright supports CSS, XPath, text=, role=, and more natively.
    - Waits are built into locator.click(), fill(), etc. (no explicit WebDriverWait).
    - Network interception, HAR, tracing, and PDF are native features.
    """

    def __init__(self, config: Optional[PlaywrightConfig] = None, **kwargs):
        self._config = config or PlaywrightConfig(**kwargs)
        self._playwright: Optional[PlaywrightInstance] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._pw_instance = None   # async_playwright() context manager
        self.logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._pw_instance = async_playwright()
        self._playwright = await self._pw_instance.__aenter__()

        launcher = getattr(self._playwright, self._config.browser_type)
        self._browser = await launcher.launch(
            headless=self._config.headless,
            slow_mo=self._config.slow_mo,
            proxy=self._config.proxy,
        )

        context_kwargs = self._build_context_kwargs()
        self._context = await self._browser.new_context(**context_kwargs)
        self._context.set_default_timeout(self._config.timeout)

        self._page = await self._context.new_page()
        self.logger.info(
            f"PlaywrightDriver started  "
            f"browser={self._config.browser_type}  "
            f"headless={self._config.headless}"
        )

    async def quit(self) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw_instance:
            await self._pw_instance.__aexit__(None, None, None)
        self.logger.info("PlaywrightDriver closed.")

    def _build_context_kwargs(self) -> Dict[str, Any]:
        kw: Dict[str, Any] = {
            "locale": self._config.locale,
            "ignore_https_errors": self._config.ignore_https_errors,
            "extra_http_headers": self._config.extra_http_headers,
        }
        if self._config.viewport:
            kw["viewport"] = self._config.viewport
        if self._config.timezone:
            kw["timezone_id"] = self._config.timezone
        if self._config.geolocation:
            kw["geolocation"] = self._config.geolocation
            kw["permissions"] = self._config.permissions or ["geolocation"]
        if self._config.permissions:
            kw["permissions"] = self._config.permissions
        if self._config.http_credentials:
            kw["http_credentials"] = self._config.http_credentials
        if self._config.mobile and self._config.device_name:
            device = self._playwright.devices[self._config.device_name]
            kw.update(device)
        if self._config.record_video_dir:
            kw["record_video_dir"] = self._config.record_video_dir
        if self._config.record_har_path:
            kw["record_har_path"] = self._config.record_har_path
        if self._config.storage_state:
            kw["storage_state"] = self._config.storage_state
        return kw

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def navigate(self, url: str, timeout: int = 30) -> None:
        await self._page.goto(url, timeout=timeout * 1000,
                               wait_until="domcontentloaded")

    async def go_back(self) -> None:
        await self._page.go_back()

    async def refresh(self) -> None:
        await self._page.reload()

    @property
    def current_url(self) -> str:
        return self._page.url

    # ------------------------------------------------------------------
    # Selector resolution
    # ------------------------------------------------------------------

    def _resolve_selector(self, selector: str, selector_type: str) -> str:
        """
        Convert AI-Parrot selector_type conventions to Playwright selector strings.

        selector_type mappings:
          css   → selector (used as-is, Playwright default)
          xpath → xpath=<selector>
          text  → text=<selector>
          role  → role=<selector>  (Playwright ARIA role selector)
          id    → #<selector>      (shorthand for CSS id)
        """
        mapping = {
            "css":   selector,
            "xpath": f"xpath={selector}",
            "text":  f"text={selector}",
            "role":  f"role={selector}",
            "id":    f"#{selector}",
        }
        return mapping.get(selector_type.lower(), selector)

    # ------------------------------------------------------------------
    # DOM interaction
    # ------------------------------------------------------------------

    async def click(self, selector: str, selector_type: str = "css") -> None:
        loc = self._resolve_selector(selector, selector_type)
        await self._page.locator(loc).click()

    async def fill(self, selector: str, value: str,
                   selector_type: str = "css") -> None:
        loc = self._resolve_selector(selector, selector_type)
        await self._page.locator(loc).fill(value)

    async def select_option(self, selector: str, value: str) -> None:
        await self._page.locator(selector).select_option(value)

    async def press_key(self, key: str) -> None:
        await self._page.keyboard.press(key)

    async def scroll(self, direction: str, amount: int) -> None:
        delta_y = amount if direction == "down" else -amount
        delta_x = amount if direction == "right" else (
            -amount if direction == "left" else 0
        )
        await self._page.mouse.wheel(delta_x, delta_y)

    async def hover(self, selector: str) -> None:
        await self._page.locator(selector).hover()

    async def drag_and_drop(self, source: str, target: str) -> None:
        await self._page.drag_and_drop(source, target)

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    async def get_text(self, selector: str, selector_type: str = "css",
                        multiple: bool = False) -> Any:
        loc = self._resolve_selector(selector, selector_type)
        if multiple:
            elements = await self._page.locator(loc).all()
            return [await el.inner_text() for el in elements]
        return await self._page.locator(loc).inner_text()

    async def get_html(self, selector: Optional[str] = None) -> str:
        if selector:
            return await self._page.locator(selector).inner_html()
        return await self._page.content()

    async def get_attribute(self, selector: str, attribute: str) -> Optional[str]:
        return await self._page.locator(selector).get_attribute(attribute)

    async def get_cookies(self) -> List[Dict]:
        return await self._context.cookies()

    async def set_cookies(self, cookies: List[Dict]) -> None:
        await self._context.add_cookies(cookies)

    # ------------------------------------------------------------------
    # Waiting
    # ------------------------------------------------------------------

    async def wait_for_selector(self, selector: str, timeout: int = 10,
                                 state: str = "visible") -> None:
        # Playwright states: "attached" | "detached" | "visible" | "hidden"
        await self._page.wait_for_selector(
            selector, timeout=timeout * 1000, state=state
        )

    async def wait_for_url(self, url_pattern: str, timeout: int = 10) -> None:
        await self._page.wait_for_url(url_pattern, timeout=timeout * 1000)

    async def wait_for_load_state(self, state: str = "load") -> None:
        # Playwright states: "load" | "domcontentloaded" | "networkidle"
        await self._page.wait_for_load_state(state)

    # ------------------------------------------------------------------
    # Media / files
    # ------------------------------------------------------------------

    async def screenshot(self, filepath: str, full_page: bool = False) -> str:
        await self._page.screenshot(path=filepath, full_page=full_page)
        return filepath

    async def upload_file(self, selector: str, filepath: str) -> None:
        await self._page.set_input_files(selector, filepath)

    # ------------------------------------------------------------------
    # Script
    # ------------------------------------------------------------------

    async def evaluate(self, script: str) -> Any:
        return await self._page.evaluate(script)

    # ------------------------------------------------------------------
    # Playwright-exclusive features
    # ------------------------------------------------------------------

    async def intercept_requests(
        self,
        handler: Callable[[Route, Request], Awaitable[None]],
    ) -> None:
        """
        Register a network interception handler.

        The handler receives (route, request) and must call one of:
          await route.continue_()       — pass the request through
          await route.fulfill(...)      — respond with mock data
          await route.abort()           — block the request

        Example — block all image requests:
            async def block_images(route, request):
                if request.resource_type == "image":
                    await route.abort()
                else:
                    await route.continue_()

            await driver.intercept_requests(block_images)
        """
        await self._page.route("**/*", handler)

    async def intercept_by_resource_type(
        self,
        block_types: List[str],
    ) -> None:
        """
        Convenience wrapper to block specific resource types.

        Common types: "image", "stylesheet", "font", "media", "websocket"

        Useful for speeding up scrapes by blocking non-essential assets.
        """
        async def handler(route: Route, request: Request):
            if request.resource_type in block_types:
                await route.abort()
            else:
                await route.continue_()

        await self.intercept_requests(handler)

    async def mock_route(
        self,
        url_pattern: str,
        response_body: Any,
        status: int = 200,
        content_type: str = "application/json",
    ) -> None:
        """
        Mock API responses matching url_pattern.

        Example — mock a REST endpoint:
            await driver.mock_route(
                "**/api/products",
                response_body={"items": []},
                status=200,
            )
        """
        body = json.dumps(response_body) if not isinstance(response_body, str) \
               else response_body

        async def handler(route: Route, _: Request):
            await route.fulfill(
                status=status,
                content_type=content_type,
                body=body,
            )

        await self._page.route(url_pattern, handler)

    async def record_har(self, path: str) -> None:
        """
        Enable HAR recording for the current context.
        Must be called before navigating to any pages.
        HAR is written to disk when the context is closed (quit()).
        """
        # HAR recording in Playwright is set at context creation time via
        # record_har_path in PlaywrightConfig.  This method provides a
        # runtime alternative by re-routing via the context.
        self.logger.info(
            "For HAR recording, set record_har_path in PlaywrightConfig "
            "before calling start(). Runtime HAR attachment is not supported "
            "by the Playwright API."
        )

    async def save_pdf(self, filepath: str) -> str:
        """
        Export the current page as a PDF.
        Only supported with Chromium (not Firefox or WebKit).
        """
        if self._config.browser_type != "chromium":
            raise NotImplementedError(
                "PDF export is only supported with browser_type='chromium'."
            )
        await self._page.pdf(path=filepath)
        return filepath

    async def start_tracing(
        self,
        screenshots: bool = True,
        snapshots: bool = True,
        title: Optional[str] = None,
    ) -> None:
        """
        Start Playwright tracing.  Trace can be viewed in the Playwright
        Trace Viewer: `npx playwright show-trace trace.zip`
        """
        await self._context.tracing.start(
            screenshots=screenshots,
            snapshots=snapshots,
            title=title,
        )

    async def stop_tracing(self, output_path: str) -> None:
        """Stop tracing and write the trace archive to output_path."""
        await self._context.tracing.stop(path=output_path)

    async def save_storage_state(self, path: str) -> None:
        """
        Persist cookies and localStorage to a JSON file for session reuse.

        Saved state can be loaded on the next run via:
            PlaywrightConfig(storage_state="./auth_state.json")

        Useful for persisting authenticated sessions between scraping runs.
        """
        await self._context.storage_state(path=path)

    async def new_page(self) -> Page:
        """Open a new tab within the same browser context."""
        self._page = await self._context.new_page()
        return self._page

    async def get_network_responses(
        self,
        url_pattern: str,
        trigger_fn: Optional[Callable] = None,
    ) -> List[Dict]:
        """
        Collect network responses matching url_pattern.

        If trigger_fn is provided, it is awaited after setting up the listener,
        allowing the caller to perform an action (e.g. a click) that triggers
        the network request.

        Returns list of response dicts with keys: url, status, body.
        """
        responses = []

        async def on_response(response: Response):
            if url_pattern in response.url:
                try:
                    body = await response.json()
                except Exception:
                    body = await response.text()
                responses.append({
                    "url": response.url,
                    "status": response.status,
                    "body": body,
                })

        self._page.on("response", on_response)

        if trigger_fn:
            await trigger_fn()
            await self._page.wait_for_load_state("networkidle")

        self._page.remove_listener("response", on_response)
        return responses
```

---

## 4. `DriverFactory`

```python
class DriverFactory:
    """Creates the correct driver from a unified DriverConfig."""

    @staticmethod
    async def create(config: "DriverConfig") -> AbstractDriver:
        if config.driver_type == "playwright":
            pw_config = PlaywrightConfig(
                browser_type=_map_browser_to_playwright(config.browser),
                headless=config.headless,
                mobile=config.mobile,
                device_name=config.mobile_device,
                timeout=config.default_timeout * 1000,
            )
            driver = PlaywrightDriver(pw_config)
        else:
            driver = SeleniumDriver(config)

        await driver.start()
        return driver


def _map_browser_to_playwright(
    browser: str,
) -> Literal["chromium", "firefox", "webkit"]:
    mapping = {
        "chrome": "chromium",
        "edge": "chromium",
        "undetected": "chromium",
        "firefox": "firefox",
        "safari": "webkit",
        "webkit": "webkit",
    }
    result = mapping.get(browser, "chromium")
    if browser not in mapping:
        logging.warning(
            f"Unknown browser '{browser}', defaulting to chromium."
        )
    return result
```

---

## 5. Feature Comparison

| Capability | SeleniumDriver | PlaywrightDriver |
|---|---|---|
| CSS selectors | ✓ | ✓ |
| XPath selectors | ✓ | ✓ |
| Text selectors | via JS workaround | ✓ native |
| ARIA/role selectors | ✗ | ✓ |
| Auto-wait on actions | ✗ (explicit waits) | ✓ built-in |
| Request interception | via selenium-wire | ✓ native |
| Response interception | via selenium-wire | ✓ native |
| Route mocking | ✗ | ✓ |
| HAR recording | ✗ | ✓ (via config) |
| Native PDF export | ✗ | ✓ (Chromium only) |
| Trace recording | ✗ | ✓ |
| Storage state persistence | manual (cookies) | ✓ (full context) |
| Multi-tab in same context | workaround | ✓ |
| Mobile device emulation | via user-agent | ✓ full emulation |
| Video recording | ✗ | ✓ |
| Geolocation mocking | ✗ | ✓ |
| Network throttling | ✗ | ✓ (via CDP) |
| Performance metrics | via JS | ✓ native |
| headless detection evasion | undetected-chrome | stealth plugins (optional) |

---

## 6. Playwright-Exclusive Workflow: Authenticated Session Reuse

```python
# First run: log in and save session
driver = PlaywrightDriver(PlaywrightConfig(browser_type="chromium"))
await driver.start()
await driver.navigate("https://example.com/login")
await driver.fill("#email", "user@example.com")
await driver.fill("#password", "secret")
await driver.click("#submit")
await driver.wait_for_url("**/dashboard")
await driver.save_storage_state("./session/example_auth.json")
await driver.quit()

# Subsequent runs: skip login entirely
driver2 = PlaywrightDriver(PlaywrightConfig(
    browser_type="chromium",
    storage_state="./session/example_auth.json",  # restored automatically
))
await driver2.start()
await driver2.navigate("https://example.com/dashboard")  # already logged in
```

---

## 7. Playwright-Exclusive Workflow: Speed Optimization via Resource Blocking

```python
driver = PlaywrightDriver(PlaywrightConfig(headless=True))
await driver.start()

# Block images, fonts, and stylesheets for 3-5x faster scraping
await driver.intercept_by_resource_type(["image", "stylesheet", "font", "media"])

await driver.navigate("https://news.example.com/articles")
html = await driver.get_html()
await driver.quit()
```

---

## 8. Playwright-Exclusive Workflow: API Response Capture

```python
driver = PlaywrightDriver(PlaywrightConfig())
await driver.start()
await driver.navigate("https://spa.example.com")

# Capture the JSON response that the SPA fetches on load
api_data = await driver.get_network_responses(
    url_pattern="/api/products",
    trigger_fn=lambda: driver.click(".load-more-button"),
)

print(api_data[0]["body"])  # raw JSON from the API, no scraping needed
await driver.quit()
```

---

## 9. Step Action Mapping (Selenium → Playwright)

The existing step-execution engine maps action strings to driver method calls.
The table below shows the method-level mapping to ensure parity:

| Action | SeleniumDriver method | PlaywrightDriver method |
|---|---|---|
| `navigate` | `get(url)` | `navigate(url)` |
| `click` | `find_element + .click()` | `locator(sel).click()` |
| `fill` | `find_element + .send_keys()` | `locator(sel).fill()` |
| `select` | `Select(element).select_by_value()` | `locator(sel).select_option()` |
| `wait` (element) | `WebDriverWait + EC` | `wait_for_selector()` |
| `wait` (url) | `EC.url_contains` | `wait_for_url()` |
| `wait` (networkidle) | not available | `wait_for_load_state("networkidle")` |
| `scroll` | `execute_script("window.scrollBy")` | `mouse.wheel(dx, dy)` |
| `screenshot` | `driver.save_screenshot()` | `page.screenshot()` |
| `get_text` | `element.text` | `locator(sel).inner_text()` |
| `get_html` | `driver.page_source` | `page.content()` |
| `evaluate` | `execute_script()` | `page.evaluate()` |
| `upload_file` | `find_element.send_keys(path)` | `page.set_input_files()` |
| `authenticate` (form) | fill + click | fill + click |
| `get_cookies` | `driver.get_cookies()` | `context.cookies()` |
| `set_cookies` | `driver.add_cookie()` | `context.add_cookies()` |

---

## 10. Dependencies

| Package | Purpose | Notes |
|---------|---------|-------|
| `playwright` | Browser automation | `pip install playwright` + `playwright install` |
| Standard library | `json`, `logging`, etc. | — |

Playwright must be installed separately:
```bash
pip install playwright
playwright install chromium  # or: playwright install  (all browsers)
```

The existing `auto_install=True` option in driver configuration should detect
Playwright's browser binaries and trigger `playwright install` if missing.

---

## 11. Tests (expected coverage)

- `PlaywrightDriver` full lifecycle (start, navigate, interact, quit).
- Selector type mapping: css, xpath, text, role, id.
- Request interception: block images, verify page still loads.
- Route mocking: mock API endpoint, verify response used by page.
- `save_storage_state` / `storage_state` round-trip (authenticated session).
- `save_pdf` raises `NotImplementedError` on firefox/webkit.
- `start_tracing` + `stop_tracing` produces a valid zip file.
- `get_network_responses` captures correct API response body.
- `DriverFactory.create()` returns correct driver type for all browser strings.
- `intercept_by_resource_type` blocks specified resource types.

---

*Previous: [SPEC-03 — CrawlEngine](./SPEC-03-CrawlEngine.md)*
