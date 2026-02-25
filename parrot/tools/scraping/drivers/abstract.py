"""Abstract driver interface for browser automation.

Defines the unified ``AbstractDriver`` ABC that all browser automation
drivers (Selenium, Playwright, etc.) must implement.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, List, Optional


class AbstractDriver(ABC):
    """Unified interface for browser automation drivers.

    All driver-specific capabilities are exposed through this interface.
    Concrete drivers implement the abstract methods for their backend.
    Methods not supported by a driver raise ``NotImplementedError`` with
    a clear message indicating which driver does support the feature.

    Method groups:
        - **Lifecycle**: start / quit
        - **Navigation**: navigate, go_back, go_forward, reload
        - **DOM interaction**: click, fill, select_option, hover, press_key
        - **Content extraction**: get_page_source, get_text, get_attribute,
          get_all_texts, screenshot
        - **Waiting**: wait_for_selector, wait_for_navigation,
          wait_for_load_state
        - **Media / Scripts**: execute_script, evaluate
        - **Property**: current_url
        - **Extended** (non-abstract, Playwright-only by default):
          intercept_requests, record_har, save_pdf, start_tracing,
          stop_tracing, mock_route
    """

    # ── Lifecycle ────────────────────────────────────────────────

    @abstractmethod
    async def start(self) -> None:
        """Initialize the browser and create a default page/tab."""

    @abstractmethod
    async def quit(self) -> None:
        """Close the browser and release all resources."""

    # ── Navigation ───────────────────────────────────────────────

    @abstractmethod
    async def navigate(self, url: str, timeout: int = 30) -> None:
        """Navigate to *url*.

        Args:
            url: The URL to navigate to.
            timeout: Maximum wait time in seconds.
        """

    @abstractmethod
    async def go_back(self) -> None:
        """Navigate back in history."""

    @abstractmethod
    async def go_forward(self) -> None:
        """Navigate forward in history."""

    @abstractmethod
    async def reload(self) -> None:
        """Reload the current page."""

    # ── DOM Interaction ──────────────────────────────────────────

    @abstractmethod
    async def click(self, selector: str, timeout: int = 10) -> None:
        """Click the element matching *selector*.

        Args:
            selector: CSS selector (or driver-specific selector).
            timeout: Maximum wait time in seconds.
        """

    @abstractmethod
    async def fill(
        self, selector: str, value: str, timeout: int = 10
    ) -> None:
        """Clear and fill the input matching *selector* with *value*.

        Args:
            selector: CSS selector for the input element.
            value: Text to type into the input.
            timeout: Maximum wait time in seconds.
        """

    @abstractmethod
    async def select_option(
        self, selector: str, value: str, timeout: int = 10
    ) -> None:
        """Select an option by value in a ``<select>`` element.

        Args:
            selector: CSS selector for the select element.
            value: The option value to select.
            timeout: Maximum wait time in seconds.
        """

    @abstractmethod
    async def hover(self, selector: str, timeout: int = 10) -> None:
        """Hover over the element matching *selector*.

        Args:
            selector: CSS selector.
            timeout: Maximum wait time in seconds.
        """

    @abstractmethod
    async def press_key(self, key: str) -> None:
        """Press a keyboard key.

        Args:
            key: Key name (e.g. ``"Enter"``, ``"Tab"``, ``"Escape"``).
        """

    # ── Content Extraction ───────────────────────────────────────

    @abstractmethod
    async def get_page_source(self) -> str:
        """Return the full HTML source of the current page."""

    @abstractmethod
    async def get_text(self, selector: str, timeout: int = 10) -> str:
        """Return the inner text of the element matching *selector*.

        Args:
            selector: CSS selector.
            timeout: Maximum wait time in seconds.
        """

    @abstractmethod
    async def get_attribute(
        self, selector: str, attribute: str, timeout: int = 10
    ) -> Optional[str]:
        """Return the value of *attribute* on the element matching *selector*.

        Args:
            selector: CSS selector.
            attribute: Attribute name (e.g. ``"href"``, ``"src"``).
            timeout: Maximum wait time in seconds.

        Returns:
            Attribute value, or ``None`` if not present.
        """

    @abstractmethod
    async def get_all_texts(
        self, selector: str, timeout: int = 10
    ) -> List[str]:
        """Return the inner text of every element matching *selector*.

        Args:
            selector: CSS selector matching one or more elements.
            timeout: Maximum wait time in seconds.
        """

    @abstractmethod
    async def screenshot(
        self, path: str, full_page: bool = False
    ) -> bytes:
        """Take a screenshot of the current page.

        Args:
            path: File path to save the screenshot.
            full_page: If ``True``, capture the full scrollable page.

        Returns:
            Raw screenshot bytes.
        """

    # ── Waiting ──────────────────────────────────────────────────

    @abstractmethod
    async def wait_for_selector(
        self, selector: str, timeout: int = 10, state: str = "visible"
    ) -> None:
        """Wait until an element matching *selector* reaches *state*.

        Args:
            selector: CSS selector.
            timeout: Maximum wait time in seconds.
            state: Target state — ``"visible"``, ``"hidden"``,
                ``"attached"``, or ``"detached"``.
        """

    @abstractmethod
    async def wait_for_navigation(self, timeout: int = 30) -> None:
        """Wait for a navigation event to complete.

        Args:
            timeout: Maximum wait time in seconds.
        """

    @abstractmethod
    async def wait_for_load_state(
        self, state: str = "load", timeout: int = 30
    ) -> None:
        """Wait until the page reaches the given load *state*.

        Args:
            state: ``"load"``, ``"domcontentloaded"``, or
                ``"networkidle"``.
            timeout: Maximum wait time in seconds.
        """

    # ── Media / Scripts ──────────────────────────────────────────

    @abstractmethod
    async def execute_script(self, script: str, *args: Any) -> Any:
        """Execute JavaScript in the page context.

        Args:
            script: JavaScript source code.
            *args: Arguments passed to the script.

        Returns:
            The return value of the script.
        """

    @abstractmethod
    async def evaluate(self, expression: str) -> Any:
        """Evaluate a JavaScript expression and return the result.

        Args:
            expression: JavaScript expression to evaluate.

        Returns:
            The expression result.
        """

    # ── Property ─────────────────────────────────────────────────

    @property
    @abstractmethod
    def current_url(self) -> str:
        """The URL of the current page."""

    # ── Extended Capabilities (non-abstract) ─────────────────────
    # These methods have concrete default implementations that raise
    # NotImplementedError.  Drivers that support the feature override
    # them (e.g. PlaywrightDriver).

    async def intercept_requests(self, handler: Callable) -> None:
        """Set up a request interception handler.

        Args:
            handler: Async callable receiving ``(route, request)``.

        Raises:
            NotImplementedError: If the driver does not support
                request interception.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support intercept_requests. "
            "Use PlaywrightDriver for this feature."
        )

    async def record_har(self, path: str) -> None:
        """Start recording a HAR file.

        Args:
            path: File path for the HAR output.

        Raises:
            NotImplementedError: If the driver does not support HAR
                recording.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support record_har. "
            "Use PlaywrightDriver for this feature."
        )

    async def save_pdf(self, path: str) -> bytes:
        """Save the current page as a PDF.

        Args:
            path: File path for the PDF output.

        Returns:
            Raw PDF bytes.

        Raises:
            NotImplementedError: If the driver does not support native
                PDF export.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support save_pdf. "
            "Use PlaywrightDriver with a Chromium-based browser."
        )

    async def start_tracing(
        self,
        name: str = "trace",
        screenshots: bool = True,
        snapshots: bool = True,
    ) -> None:
        """Start tracing browser activity.

        Args:
            name: Trace name / title.
            screenshots: Capture screenshots in the trace.
            snapshots: Capture DOM snapshots in the trace.

        Raises:
            NotImplementedError: If the driver does not support tracing.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support start_tracing. "
            "Use PlaywrightDriver for this feature."
        )

    async def stop_tracing(self, path: str) -> None:
        """Stop tracing and save to *path*.

        Args:
            path: File path for the trace archive.

        Raises:
            NotImplementedError: If the driver does not support tracing.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support stop_tracing. "
            "Use PlaywrightDriver for this feature."
        )

    async def mock_route(self, url_pattern: str, handler: Callable) -> None:
        """Mock network requests matching *url_pattern*.

        Args:
            url_pattern: Glob or regex pattern to match request URLs.
            handler: Async callable to handle matched requests.

        Raises:
            NotImplementedError: If the driver does not support route
                mocking.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support mock_route. "
            "Use PlaywrightDriver for this feature."
        )
