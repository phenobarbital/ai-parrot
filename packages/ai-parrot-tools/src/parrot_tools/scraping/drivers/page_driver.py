"""PageDriver — a lightweight AbstractDriver over a single Playwright Page.

``FlowExecutor`` creates one Playwright ``Page`` per node (from a
session-scoped ``BrowserContext``) and wraps it in a :class:`PageDriver` so it
can be handed to ``execute_plan_steps`` (which only speaks ``AbstractDriver``).

Unlike :class:`PlaywrightDriver`, this adapter owns neither the browser nor the
context — ``start()`` is a no-op and ``quit()`` closes only the wrapped page
(FEAT-222, Module 6).
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from .abstract import AbstractDriver


class PageDriver(AbstractDriver):
    """Adapt a live Playwright ``Page`` to the :class:`AbstractDriver` interface.

    Args:
        page: A live Playwright ``Page`` (already created within a
            ``BrowserContext``).
    """

    def __init__(self, page: Any) -> None:
        self._page = page
        self.logger = logging.getLogger(__name__)

    # ── Internal helper ──────────────────────────────────────────────

    @staticmethod
    def _resolve_selector(selector: str) -> str:
        """Prefix XPath selectors for Playwright.

        Selectors starting with ``/`` or ``./`` are treated as XPath and
        prefixed with ``xpath=``; all others are used as CSS selectors
        (same logic as :class:`PlaywrightDriver`).
        """
        if selector.startswith(("/", "./")):
            return f"xpath={selector}"
        return selector

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        """No-op: the page is already alive when handed to this adapter."""
        return None

    async def quit(self) -> None:
        """Close the wrapped page (not the context or browser)."""
        await self._page.close()

    # ── Navigation ───────────────────────────────────────────────────

    async def navigate(self, url: str, timeout: int = 30) -> None:
        """Navigate to *url*."""
        await self._page.goto(url, timeout=timeout * 1000)

    async def go_back(self) -> None:
        """Navigate back in history."""
        await self._page.go_back()

    async def go_forward(self) -> None:
        """Navigate forward in history."""
        await self._page.go_forward()

    async def reload(self) -> None:
        """Reload the current page."""
        await self._page.reload()

    # ── DOM Interaction ──────────────────────────────────────────────

    async def click(self, selector: str, timeout: int = 10) -> None:
        """Click the element matching *selector*."""
        await self._page.click(self._resolve_selector(selector), timeout=timeout * 1000)

    async def fill(self, selector: str, value: str, timeout: int = 10) -> None:
        """Fill the input matching *selector* with *value*."""
        await self._page.fill(
            self._resolve_selector(selector), value, timeout=timeout * 1000
        )

    async def select_option(
        self,
        selector: str,
        value: str,
        *,
        by: str = "value",
        timeout: int = 10,
    ) -> None:
        """Select an option in a ``<select>`` element."""
        sel = self._resolve_selector(selector)
        if by == "value":
            await self._page.select_option(sel, value=value, timeout=timeout * 1000)
        elif by == "text":
            await self._page.select_option(sel, label=value, timeout=timeout * 1000)
        elif by == "index":
            await self._page.select_option(
                sel, index=int(value), timeout=timeout * 1000
            )
        else:
            raise ValueError(f"Unsupported select 'by' mode: {by!r}")

    async def hover(self, selector: str, timeout: int = 10) -> None:
        """Hover over the element matching *selector*."""
        await self._page.hover(self._resolve_selector(selector), timeout=timeout * 1000)

    async def press_key(self, key: str) -> None:
        """Press a keyboard key."""
        await self._page.keyboard.press(key)

    # ── Content Extraction ───────────────────────────────────────────

    async def get_page_source(self) -> str:
        """Return the full HTML of the current page."""
        return await self._page.content()

    async def get_text(self, selector: str, timeout: int = 10) -> str:
        """Return the inner text of the first matching element."""
        return await self._page.inner_text(
            self._resolve_selector(selector), timeout=timeout * 1000
        )

    async def get_attribute(
        self, selector: str, attribute: str, timeout: int = 10
    ) -> Optional[str]:
        """Return the value of *attribute* on the matching element."""
        return await self._page.get_attribute(
            self._resolve_selector(selector), attribute, timeout=timeout * 1000
        )

    async def get_all_texts(self, selector: str, timeout: int = 10) -> List[str]:
        """Return the inner text of every matching element."""
        return await self._page.eval_on_selector_all(
            self._resolve_selector(selector),
            "els => els.map(e => e.innerText)",
        )

    async def screenshot(self, path: str, full_page: bool = False) -> bytes:
        """Take a screenshot and save it to *path*."""
        return await self._page.screenshot(path=path, full_page=full_page)

    # ── Waiting ──────────────────────────────────────────────────────

    async def wait_for_selector(
        self, selector: str, timeout: int = 10, state: str = "visible"
    ) -> None:
        """Wait until *selector* reaches *state*."""
        await self._page.wait_for_selector(
            self._resolve_selector(selector), timeout=timeout * 1000, state=state
        )

    async def wait_for_navigation(self, timeout: int = 30) -> None:
        """Wait for navigation/network to settle."""
        await self._page.wait_for_load_state("networkidle", timeout=timeout * 1000)

    async def wait_for_load_state(
        self, state: str = "load", timeout: int = 30
    ) -> None:
        """Wait until the page reaches the given load *state*."""
        await self._page.wait_for_load_state(state, timeout=timeout * 1000)

    # ── Media / Scripts ──────────────────────────────────────────────

    async def execute_script(self, script: str, *args: Any) -> Any:
        """Execute JavaScript with arguments in the page context."""
        return await self._page.evaluate(script, *args)

    async def evaluate(self, expression: str) -> Any:
        """Evaluate a JavaScript expression and return the result."""
        return await self._page.evaluate(expression)

    # ── Property ─────────────────────────────────────────────────────

    @property
    def current_url(self) -> str:
        """The URL of the wrapped page."""
        return self._page.url
