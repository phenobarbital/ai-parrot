"""
AsyncComputerBackend — async Playwright wrapper for computer-use actions.

Translates coordinate-based computer-use model actions into Playwright API
calls. Every action returns an EnvState with a screenshot and current URL.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from parrot_tools.computer.models import EnvState

logger = logging.getLogger(__name__)

# Key mapping from model-friendly names to Playwright key names.
_KEY_MAP: dict[str, str] = {
    "ctrl": "ControlOrMeta",
    "control": "ControlOrMeta",
    "cmd": "ControlOrMeta",
    "meta": "Meta",
    "shift": "Shift",
    "alt": "Alt",
    "option": "Alt",
    "enter": "Enter",
    "return": "Enter",
    "backspace": "Backspace",
    "delete": "Delete",
    "escape": "Escape",
    "esc": "Escape",
    "tab": "Tab",
    "space": "Space",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "arrowup": "ArrowUp",
    "arrowdown": "ArrowDown",
    "arrowleft": "ArrowLeft",
    "arrowright": "ArrowRight",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "f1": "F1",
    "f2": "F2",
    "f3": "F3",
    "f4": "F4",
    "f5": "F5",
    "f6": "F6",
    "f7": "F7",
    "f8": "F8",
    "f9": "F9",
    "f10": "F10",
    "f11": "F11",
    "f12": "F12",
}


def _normalize_key(key: str) -> str:
    """Normalize a key name to the Playwright format.

    Args:
        key: Key name as provided (e.g. "control", "Enter").

    Returns:
        Playwright-compatible key name.
    """
    return _KEY_MAP.get(key.lower(), key)


class AsyncComputerBackend:
    """Async Playwright wrapper implementing the computer-use action interface.

    Manages browser lifecycle (start/stop), translates pixel-coordinate
    actions into Playwright mouse/keyboard calls, and returns EnvState
    (screenshot + URL) after each action.

    Coordinate parameters accepted by action methods are ALREADY in pixel
    units — the toolkit layer is responsible for denormalization.

    Args:
        viewport: Browser viewport as ``(width, height)`` in pixels.
        headless: Whether to run the browser in headless mode.
        browser_type: Playwright browser engine — ``"chromium"``, ``"firefox"``
            or ``"webkit"``.
        initial_url: URL to navigate to when the browser first opens.
        search_engine_url: URL used by the ``search()`` action.
    """

    def __init__(
        self,
        viewport: tuple[int, int] = (1280, 720),
        headless: bool = True,
        browser_type: str = "chromium",
        initial_url: str = "https://www.google.com",
        search_engine_url: str = "https://www.google.com",
    ) -> None:
        self._viewport = viewport
        self._headless = headless
        self._browser_type = browser_type
        self._initial_url = initial_url
        self._search_engine_url = search_engine_url

        # Playwright state — populated by start()
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch the browser and navigate to the initial URL.

        Creates a new Playwright context with the configured viewport and
        hooks new-tab events to redirect them to the current page (single-tab
        model).

        Raises:
            RuntimeError: If the browser is already running.
        """
        from playwright.async_api import async_playwright

        if self._playwright is not None:
            logger.warning("AsyncComputerBackend.start() called but browser is already running.")
            return

        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, self._browser_type)
        self._browser = await launcher.launch(headless=self._headless)
        self._context = await self._browser.new_context(
            viewport={"width": self._viewport[0], "height": self._viewport[1]},
        )

        # Intercept new tabs and redirect them to the current page (single-tab model).
        self._context.on("page", self._handle_new_page)

        self._page = await self._context.new_page()
        await self._page.goto(self._initial_url)
        logger.info(
            "AsyncComputerBackend started: browser=%s headless=%s viewport=%s initial_url=%s",
            self._browser_type,
            self._headless,
            self._viewport,
            self._initial_url,
        )

    async def stop(self) -> None:
        """Close the browser and release all Playwright resources."""
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
        logger.info("AsyncComputerBackend stopped.")

    def _handle_new_page(self, page: Any) -> None:
        """Redirect newly opened pages to the current page (single-tab model).

        Args:
            page: The newly opened Playwright page.
        """
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(self._redirect_new_page(page))
        except RuntimeError:
            logger.debug("_handle_new_page: no running event loop, ignoring new tab")

    async def _redirect_new_page(self, new_page: Any) -> None:
        """Close new tabs and navigate current page to their URL.

        Args:
            new_page: The newly opened page to redirect.
        """
        try:
            url = new_page.url
            await new_page.close()
            if url and url not in ("about:blank", "chrome://newtab/"):
                await self._page.goto(url)
        except Exception as exc:
            logger.warning("_redirect_new_page: %s", exc)

    # ── Guards ────────────────────────────────────────────────────────────────

    def _ensure_started(self) -> None:
        """Raise RuntimeError if the browser has not been started.

        Raises:
            RuntimeError: If start() has not been called yet.
        """
        if self._page is None:
            raise RuntimeError(
                "Browser not started. Call start() or use the toolkit which calls "
                "_pre_execute() automatically."
            )

    @property
    def current_url(self) -> str:
        """Return the current page URL, or empty string if browser not started.

        Returns:
            Current URL string, or ``""`` if the browser has not been started.
        """
        return self._page.url if self._page else ""

    # ── State helpers ──────────────────────────────────────────────────────────

    def screen_size(self) -> tuple[int, int]:
        """Return the current viewport dimensions.

        Returns:
            ``(width, height)`` tuple in pixels.
        """
        return self._viewport

    async def current_state(self) -> EnvState:
        """Capture the current page state (screenshot + URL).

        Waits for the page to finish loading before capturing.

        Returns:
            EnvState with PNG bytes and the current URL.

        Raises:
            RuntimeError: If the browser has not been started.
        """
        self._ensure_started()
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass  # Some navigations time out — capture anyway
        await asyncio.sleep(0.5)  # Let the page fully render
        screenshot_bytes = await self._page.screenshot(full_page=False)
        return EnvState(screenshot=screenshot_bytes, url=self._page.url)

    async def screenshot(self, full_page: bool = False) -> bytes:
        """Capture a standalone screenshot without triggering state updates.

        Args:
            full_page: If True, captures the entire scrollable page.

        Returns:
            PNG-encoded screenshot bytes.
        """
        return await self._page.screenshot(full_page=full_page)

    # ── 13 predefined computer-use actions ────────────────────────────────────

    async def click_at(self, x: int, y: int) -> EnvState:
        """Click at pixel coordinates (x, y).

        Args:
            x: Horizontal pixel coordinate.
            y: Vertical pixel coordinate.

        Returns:
            EnvState after the click.
        """
        await self._page.mouse.click(x, y)
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass
        return await self.current_state()

    async def hover_at(self, x: int, y: int) -> EnvState:
        """Hover the mouse at pixel coordinates (x, y).

        Args:
            x: Horizontal pixel coordinate.
            y: Vertical pixel coordinate.

        Returns:
            EnvState after the hover.
        """
        await self._page.mouse.move(x, y)
        return await self.current_state()

    async def type_text_at(
        self,
        x: int,
        y: int,
        text: str,
        press_enter: bool = False,
        clear_before_typing: bool = True,
    ) -> EnvState:
        """Click at (x, y) and type text into the element.

        Args:
            x: Horizontal pixel coordinate.
            y: Vertical pixel coordinate.
            text: Text to type.
            press_enter: If True, presses Enter after typing.
            clear_before_typing: If True, selects all existing content and
                replaces it with the new text.

        Returns:
            EnvState after typing.
        """
        await self._page.mouse.click(x, y)
        if clear_before_typing:
            await self._page.keyboard.press("ControlOrMeta+a")
        await self._page.keyboard.type(text)
        if press_enter:
            await self._page.keyboard.press("Enter")
            try:
                await self._page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
        return await self.current_state()

    async def scroll_document(self, direction: str) -> EnvState:
        """Scroll the entire document up or down.

        Args:
            direction: ``"up"`` or ``"down"``.

        Returns:
            EnvState after scrolling.
        """
        delta = -800 if direction.lower() == "up" else 800
        await self._page.evaluate(f"window.scrollBy(0, {delta})")
        return await self.current_state()

    async def scroll_at(
        self,
        x: int,
        y: int,
        direction: str,
        magnitude: int = 800,
    ) -> EnvState:
        """Scroll at a specific pixel position.

        Args:
            x: Horizontal pixel coordinate.
            y: Vertical pixel coordinate.
            direction: ``"up"`` or ``"down"``.
            magnitude: Scroll distance in pixels.

        Returns:
            EnvState after scrolling.
        """
        delta = -magnitude if direction.lower() == "up" else magnitude
        await self._page.mouse.move(x, y)
        await self._page.mouse.wheel(0, delta)
        return await self.current_state()

    MAX_WAIT_SECONDS: int = 60

    async def wait_seconds(self, seconds: int = 5) -> EnvState:
        """Wait for the specified number of seconds (capped at 60).

        Args:
            seconds: Number of seconds to wait (clamped to 0–60).

        Returns:
            EnvState after waiting.
        """
        seconds = min(max(0, seconds), self.MAX_WAIT_SECONDS)
        await asyncio.sleep(seconds)
        return await self.current_state()

    async def go_back(self) -> EnvState:
        """Navigate to the previous page in history.

        Returns:
            EnvState after going back.
        """
        await self._page.go_back()
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass
        return await self.current_state()

    async def go_forward(self) -> EnvState:
        """Navigate to the next page in history.

        Returns:
            EnvState after going forward.
        """
        await self._page.go_forward()
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except Exception:
            pass
        return await self.current_state()

    async def search(self) -> EnvState:
        """Navigate to the configured search engine URL.

        Returns:
            EnvState after navigating to the search engine.
        """
        await self._page.goto(self._search_engine_url)
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        return await self.current_state()

    async def navigate(self, url: str) -> EnvState:
        """Navigate to an absolute URL.

        Args:
            url: Fully qualified URL to navigate to.

        Returns:
            EnvState after navigation.
        """
        await self._page.goto(url)
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        return await self.current_state()

    async def key_combination(self, keys: list[str]) -> EnvState:
        """Press a key combination (e.g. Ctrl+C).

        Args:
            keys: List of key names to press simultaneously, in order
                (e.g. ``["control", "c"]``). Keys are normalized via
                the internal key map.

        Returns:
            EnvState after the key combination.
        """
        normalized = [_normalize_key(k) for k in keys]
        combo = "+".join(normalized)
        await self._page.keyboard.press(combo)
        return await self.current_state()

    async def drag_and_drop(
        self,
        x: int,
        y: int,
        dest_x: int,
        dest_y: int,
    ) -> EnvState:
        """Drag from (x, y) to (dest_x, dest_y).

        Args:
            x: Source horizontal pixel coordinate.
            y: Source vertical pixel coordinate.
            dest_x: Destination horizontal pixel coordinate.
            dest_y: Destination vertical pixel coordinate.

        Returns:
            EnvState after the drag.
        """
        await self._page.mouse.move(x, y)
        await self._page.mouse.down()
        await self._page.mouse.move(dest_x, dest_y, steps=20)
        await self._page.mouse.up()
        return await self.current_state()

    async def open_web_browser(self) -> EnvState:
        """Open (or navigate to) the initial URL.

        Returns:
            EnvState after navigating to the initial URL.
        """
        await self._page.goto(self._initial_url)
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        return await self.current_state()

    # ── Screenshot / recording helpers ────────────────────────────────────────

    async def screenshot_element(self, selector: str) -> bytes:
        """Capture a screenshot of a specific element.

        Args:
            selector: CSS selector identifying the element.

        Returns:
            PNG-encoded screenshot bytes.
        """
        element = await self._page.query_selector(selector)
        if element is None:
            raise ValueError(f"Element not found: {selector!r}")
        return await element.screenshot()

    async def start_recording(self, output_dir: str = "./recordings") -> None:
        """Start video recording.

        Restarts the browser context with video recording enabled.

        Args:
            output_dir: Directory where the recorded video will be saved.
        """
        import os
        os.makedirs(output_dir, exist_ok=True)
        # Close existing context and reopen with recording
        current_url = self._page.url if self._page else self._initial_url
        if self._context:
            await self._context.close()
        self._context = await self._browser.new_context(
            viewport={"width": self._viewport[0], "height": self._viewport[1]},
            record_video_dir=output_dir,
        )
        self._context.on("page", self._handle_new_page)
        self._page = await self._context.new_page()
        await self._page.goto(current_url)
        logger.info("Recording started: output_dir=%s", output_dir)

    async def stop_recording(self) -> Optional[str]:
        """Stop video recording and return the video file path.

        Returns:
            Path to the recorded video file, or None if no video was recorded.
        """
        video = None
        if self._page:
            video_obj = self._page.video
            if video_obj:
                path = await video_obj.path()
                video = str(path)
        # Reopen a new context without recording
        current_url = self._page.url if self._page else self._initial_url
        if self._context:
            await self._context.close()
        self._context = await self._browser.new_context(
            viewport={"width": self._viewport[0], "height": self._viewport[1]},
        )
        self._context.on("page", self._handle_new_page)
        self._page = await self._context.new_page()
        await self._page.goto(current_url)
        logger.info("Recording stopped: video_path=%s", video)
        return video

    async def start_tracing(
        self,
        screenshots: bool = True,
        snapshots: bool = True,
    ) -> None:
        """Start Playwright tracing.

        Args:
            screenshots: Include screenshots in the trace.
            snapshots: Include DOM snapshots in the trace.
        """
        await self._context.tracing.start(
            screenshots=screenshots,
            snapshots=snapshots,
        )
        logger.info("Tracing started.")

    async def stop_tracing(self, output_path: str) -> None:
        """Stop tracing and save the trace to the given path.

        Args:
            output_path: File path where the trace archive (.zip) is saved.
        """
        await self._context.tracing.stop(path=output_path)
        logger.info("Tracing stopped: output_path=%s", output_path)

    async def record_har(self, output_path: str) -> None:
        """Start recording network traffic to a HAR file.

        Recreates the browser context with HAR recording enabled via
        ``record_har_path``. The previous context is closed and a new one is
        opened, then the browser navigates back to the current URL.

        Args:
            output_path: Path where the HAR file will be written.
        """
        current_url = self._page.url if self._page else self._initial_url
        if self._context:
            await self._context.close()
        self._context = await self._browser.new_context(
            viewport={"width": self._viewport[0], "height": self._viewport[1]},
            record_har_path=output_path,
        )
        self._context.on("page", self._handle_new_page)
        self._page = await self._context.new_page()
        if current_url:
            await self._page.goto(current_url)
        logger.info("HAR recording started: output_path=%s", output_path)

    async def save_pdf(self, output_path: str) -> bytes:
        """Export the current page as a PDF.

        Args:
            output_path: File path where the PDF will be saved.

        Returns:
            PDF bytes.
        """
        pdf_bytes = await self._page.pdf(path=output_path)
        logger.info("PDF saved: output_path=%s", output_path)
        return pdf_bytes
