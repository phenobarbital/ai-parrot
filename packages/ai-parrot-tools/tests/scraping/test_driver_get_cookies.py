"""FEAT-602 TASK-3736 — context-level cookie export."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot_tools.scraping.drivers.abstract import AbstractDriver
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver


async def test_playwright_get_cookies_returns_httponly():
    """PlaywrightDriver.get_cookies() returns context cookies, HttpOnly included."""
    drv = PlaywrightDriver.__new__(PlaywrightDriver)
    cookies = [{"name": "sid", "value": "x", "httpOnly": True}]
    drv._context = MagicMock(cookies=AsyncMock(return_value=cookies))

    result = await drv.get_cookies()

    assert result == cookies
    drv._context.cookies.assert_awaited_once_with(None)


async def test_playwright_get_cookies_forwards_urls():
    """A urls= argument is forwarded to BrowserContext.cookies() as a list."""
    drv = PlaywrightDriver.__new__(PlaywrightDriver)
    drv._context = MagicMock(cookies=AsyncMock(return_value=[]))

    await drv.get_cookies(urls=["https://hooba.example.com"])

    drv._context.cookies.assert_awaited_once_with(["https://hooba.example.com"])


async def test_playwright_get_cookies_before_start_raises():
    """Calling get_cookies() before start() (no context yet) raises RuntimeError."""
    drv = PlaywrightDriver.__new__(PlaywrightDriver)
    drv._context = None

    with pytest.raises(RuntimeError, match="before start"):
        await drv.get_cookies()


async def test_abstract_driver_get_cookies_default_raises():
    """AbstractDriver.get_cookies() fails closed with NotImplementedError."""

    class _MinimalDriver(AbstractDriver):
        async def start(self):
            ...

        async def quit(self):
            ...

        async def navigate(self, url, timeout=30):
            ...

        async def go_back(self):
            ...

        async def go_forward(self):
            ...

        async def reload(self):
            ...

        async def click(self, selector, timeout=10):
            ...

        async def fill(self, selector, value, timeout=10):
            ...

        async def select_option(self, selector, value, *, by="value", timeout=10):
            ...

        async def hover(self, selector, timeout=10):
            ...

        async def press_key(self, key):
            ...

        async def get_page_source(self):
            ...

        async def get_text(self, selector, timeout=10):
            ...

        async def get_attribute(self, selector, attribute, timeout=10):
            ...

        async def get_all_texts(self, selector, timeout=10):
            ...

        async def screenshot(self, path, full_page=False):
            ...

        async def wait_for_selector(self, selector, timeout=10, state="visible"):
            ...

        async def wait_for_navigation(self, timeout=30):
            ...

        async def wait_for_load_state(self, state="load", timeout=30):
            ...

        async def execute_script(self, script, *args):
            ...

        async def evaluate(self, expression):
            ...

        @property
        def current_url(self):
            return ""

    drv = _MinimalDriver.__new__(_MinimalDriver)

    with pytest.raises(NotImplementedError, match="get_cookies"):
        await drv.get_cookies()
