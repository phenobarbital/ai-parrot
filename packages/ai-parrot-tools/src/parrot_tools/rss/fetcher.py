"""
Article and feed fetching for the RSS Feed Reader Toolkit.

Strategy: fast aiohttp GET first; fall back to a shared headless Selenium
driver (reusing ``parrot_tools.scraping.driver.SeleniumSetup``, available via
the ``scraping`` extra) when the response fails or looks like a JS-rendered
shell. Feed XML parsing (feedparser) and all Selenium calls are blocking and
run off the event loop via ``asyncio.to_thread`` / ``run_in_executor``.
"""
from __future__ import annotations

import asyncio
import logging
import re
from functools import partial
from typing import Any, Optional

import aiohttp
from bs4 import BeautifulSoup

from .models import FetchedPage

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    feedparser = None  # type: ignore[assignment]
    HAS_FEEDPARSER = False

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    trafilatura = None  # type: ignore[assignment]
    HAS_TRAFILATURA = False

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

#: Empty SPA mount points — a strong signal the page is JS-rendered.
_JS_SHELL_RE = re.compile(r'<div\s+id="(?:root|app|__next)"\s*>\s*</div>', re.IGNORECASE)

#: Lowercase markers that, combined with thin content, suggest a JS or
#: bot-challenge wall that a real browser can pass.
_JS_MARKERS = (
    "enable javascript",
    "javascript is required",
    "cf-browser-verification",
    "checking your browser",
    "just a moment...",
)


def extract_text(html: str) -> str:
    """Extract the main readable text from an HTML page.

    Uses trafilatura when installed; otherwise falls back to a BeautifulSoup
    text dump with script/style/noscript removed.

    Args:
        html: Raw page HTML.

    Returns:
        Extracted text, or '' when nothing could be extracted.
    """
    if not html:
        return ""
    if HAS_TRAFILATURA:
        try:
            extracted = trafilatura.extract(
                html, include_comments=False, include_tables=True
            )
            if extracted:
                return extracted
        except Exception as exc:  # noqa: BLE001 — extraction must never break a fetch
            logger.debug("trafilatura extraction failed: %s", exc)
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("BeautifulSoup extraction failed: %s", exc)
        return ""


class ArticleFetcher:
    """Fetches feed XML and article pages with bounded concurrency.

    Args:
        session: Shared aiohttp client session.
        http_semaphore: Bounds concurrent aiohttp requests (feeds + pages).
        browser_semaphore: Bounds concurrent Selenium fetch slots.
        min_text_length: Extracted-text length below which a page is
            considered "thin" (fallback candidate).
        request_timeout: Per-request timeout in seconds.
        selenium_config: Extra kwargs forwarded to ``SeleniumSetup``
            (e.g. ``{"browser": "chrome", "headless": True}``).
        use_browser_fallback: Master switch for the Selenium fallback.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        http_semaphore: asyncio.Semaphore,
        browser_semaphore: asyncio.Semaphore,
        min_text_length: int = 500,
        request_timeout: int = 30,
        selenium_config: Optional[dict] = None,
        use_browser_fallback: bool = True,
    ):
        self.session = session
        self.http_semaphore = http_semaphore
        self.browser_semaphore = browser_semaphore
        self.min_text_length = min_text_length
        self.timeout = aiohttp.ClientTimeout(total=request_timeout)
        self.selenium_config = selenium_config or {}
        self.use_browser_fallback = use_browser_fallback
        self.logger = logging.getLogger(__name__)
        self._headers = {"User-Agent": DEFAULT_USER_AGENT}
        self._driver: Any = None
        self._driver_lock = asyncio.Lock()
        self._selenium_unavailable = False

    async def fetch_feed_xml(self, url: str) -> str:
        """Download a feed's raw XML.

        Args:
            url: Feed URL.

        Returns:
            The response body.

        Raises:
            RuntimeError: On non-200 responses.
            aiohttp.ClientError / asyncio.TimeoutError: On transport errors.
        """
        async with self.http_semaphore:
            async with self.session.get(
                url, headers=self._headers, timeout=self.timeout
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"HTTP {resp.status} fetching feed {url}")
                return await resp.text()

    async def parse_feed(self, xml: str) -> Any:
        """Parse feed XML with feedparser off the event loop.

        Args:
            xml: Raw feed XML.

        Returns:
            The ``feedparser.FeedParserDict``.

        Raises:
            RuntimeError: When feedparser is not installed.
        """
        if not HAS_FEEDPARSER:
            raise RuntimeError(
                "feedparser is not installed — install ai-parrot-tools[rss]"
            )
        return await asyncio.to_thread(feedparser.parse, xml)

    async def fetch_page(self, url: str, use_browser: bool = False) -> FetchedPage:
        """Fetch the complete content of an article page.

        Args:
            url: Article URL.
            use_browser: Skip aiohttp and go straight to Selenium.

        Returns:
            A :class:`FetchedPage`; on total failure ``html`` is '' and
            ``error`` explains why.
        """
        if use_browser:
            return await self._fetch_with_selenium(url)

        page = await self._fetch_with_aiohttp(url)
        if self.use_browser_fallback and self._needs_fallback(page):
            self.logger.debug(
                "Falling back to browser for %s (error=%s thin=%s)",
                url, page.error, page.thin,
            )
            browser_page = await self._fetch_with_selenium(url)
            if browser_page.html:
                return browser_page
            # Selenium also failed — keep the best-effort aiohttp result
            # but record why the fallback did not help.
            page.error = (
                f"{page.error or 'thin content'}; browser fallback failed: "
                f"{browser_page.error}"
            )
        return page

    async def _fetch_with_aiohttp(self, url: str) -> FetchedPage:
        """GET a page with aiohttp and extract its text."""
        try:
            async with self.http_semaphore:
                async with self.session.get(
                    url, headers=self._headers, timeout=self.timeout
                ) as resp:
                    if resp.status != 200:
                        return FetchedPage(
                            method="aiohttp",
                            status_code=resp.status,
                            error=f"HTTP {resp.status}",
                        )
                    content_type = resp.headers.get("Content-Type", "")
                    if content_type and "html" not in content_type.lower():
                        return FetchedPage(
                            method="aiohttp",
                            status_code=resp.status,
                            error=f"Non-HTML content-type: {content_type}",
                        )
                    html = await resp.text(errors="replace")
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            return FetchedPage(method="aiohttp", error=f"{type(exc).__name__}: {exc}")

        text = extract_text(html)
        return FetchedPage(
            html=html,
            text=text,
            method="aiohttp",
            status_code=200,
            thin=len(text) < self.min_text_length,
        )

    def _needs_fallback(self, page: FetchedPage) -> bool:
        """Decide whether an aiohttp result warrants a browser retry."""
        if page.error:
            return True
        if _JS_SHELL_RE.search(page.html):
            return True
        if page.thin:
            # Thin extraction usually means a JS-rendered or challenge page;
            # markers make it certain, but thin alone still warrants a retry.
            return True
        lowered = page.html.lower()
        return any(marker in lowered for marker in _JS_MARKERS)

    async def _get_selenium_driver(self) -> Any:
        """Lazily create the shared Selenium WebDriver.

        Returns:
            The WebDriver, or None when the scraping extra is not installed
            or driver creation failed (logged once).
        """
        if self._driver is not None or self._selenium_unavailable:
            return self._driver
        try:
            from parrot_tools.scraping.driver import SeleniumSetup
        except ImportError:
            self._selenium_unavailable = True
            self.logger.warning(
                "Selenium fallback disabled: install ai-parrot-tools[scraping]"
            )
            return None
        config = {"browser": "chrome", "headless": True, **self.selenium_config}
        try:
            setup = SeleniumSetup(**config)
            self._driver = await setup.get_driver()
        except Exception as exc:  # noqa: BLE001 — driver setup failures must not crash reads
            self._selenium_unavailable = True
            self.logger.warning("Selenium driver creation failed: %s", exc)
            return None
        return self._driver

    async def _fetch_with_selenium(self, url: str) -> FetchedPage:
        """Render a page in the shared headless browser and return its HTML."""
        async with self.browser_semaphore:
            driver = await self._get_selenium_driver()
            if driver is None:
                return FetchedPage(method="selenium", error="selenium unavailable")

            def _blocking_fetch() -> str:
                driver.get(url)
                return driver.page_source

            loop = asyncio.get_running_loop()
            # A single shared driver holds one page at a time — serialize.
            async with self._driver_lock:
                try:
                    html = await loop.run_in_executor(None, _blocking_fetch)
                except Exception as exc:  # noqa: BLE001 — selenium raises many types
                    return FetchedPage(
                        method="selenium", error=f"{type(exc).__name__}: {exc}"
                    )

        text = extract_text(html)
        return FetchedPage(
            html=html,
            text=text,
            method="selenium",
            thin=len(text) < self.min_text_length,
        )

    async def close(self) -> None:
        """Quit the shared Selenium driver, ignoring shutdown errors."""
        if self._driver is None:
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, partial(self._driver.quit))
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Error quitting selenium driver: %s", exc)
        finally:
            self._driver = None
