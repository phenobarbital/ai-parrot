"""
RSS Feed Reader Toolkit.

Reads a configurable list of RSS/Atom feeds, fetches the COMPLETE page
content of every linked article (aiohttp first, Selenium fallback for
JS-heavy pages — the fallback needs the ``scraping`` extra), and archives
raw HTML + extracted text on disk. The LLM only receives per-item metadata
dictionaries carrying the paths of the archived files, never the page
content itself; ``rss_get_content`` reads archived content on demand.

Feed parsing requires the ``rss`` extra: ``pip install ai-parrot-tools[rss]``.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import aiohttp

from parrot.conf import OUTPUT_DIR
from parrot.tools.decorators import tool_schema
from parrot.tools.toolkit import AbstractToolkit

from .fetcher import HAS_FEEDPARSER, ArticleFetcher, extract_text
from .models import FeedItemMetadata, FeedSite, GetContentInput, SUMMARY_MAX_CHARS, make_item_id
from .storage import RSSStorage

FeedConfig = Union[str, Dict[str, Any], FeedSite]


class RSSFeedReaderToolkit(AbstractToolkit):
    """Toolkit that archives RSS feed articles to disk for later retrieval.

    Args:
        feeds: Feed list — plain URLs, dicts of :class:`FeedSite` fields
            (``url``, ``name``, ``max_items``, ``use_browser``), or
            ``FeedSite`` instances.
        storage_dir: Archive root. Defaults to ``OUTPUT_DIR/rss_feeds``.
        max_items_per_feed: Default cap on items processed per feed.
        concurrency: Max concurrent aiohttp requests across all feeds.
        browser_concurrency: Max concurrent Selenium fallback slots.
        min_text_length: Extracted-text length under which a page is
            considered JS-rendered and retried in the browser.
        request_timeout: Per-request timeout in seconds.
        use_browser_fallback: Disable to never launch a browser.
        browser: Selenium browser type for the fallback.
        headless: Run the fallback browser headless.
    """

    tool_prefix = "rss"

    def __init__(
        self,
        feeds: Optional[Sequence[FeedConfig]] = None,
        storage_dir: Optional[Union[str, Path]] = None,
        max_items_per_feed: int = 10,
        concurrency: int = 10,
        browser_concurrency: int = 2,
        min_text_length: int = 500,
        request_timeout: int = 30,
        use_browser_fallback: bool = True,
        browser: str = "chrome",
        headless: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.feeds: List[FeedSite] = [
            FeedSite.from_config(item) for item in (feeds or [])
        ]
        self.storage = RSSStorage(storage_dir or Path(OUTPUT_DIR) / "rss_feeds")
        self.max_items_per_feed = max_items_per_feed
        self.concurrency = concurrency
        self.browser_concurrency = browser_concurrency
        self.min_text_length = min_text_length
        self.request_timeout = request_timeout
        self.use_browser_fallback = use_browser_fallback
        self.selenium_config = {"browser": browser, "headless": headless}
        self._session: Optional[aiohttp.ClientSession] = None
        self._fetcher: Optional[ArticleFetcher] = None

    async def start(self) -> None:
        """Create the HTTP session, semaphores, and article fetcher."""
        if self._fetcher is not None:
            return
        if not HAS_FEEDPARSER:
            raise RuntimeError(
                "feedparser is not installed — install ai-parrot-tools[rss]"
            )
        self._session = aiohttp.ClientSession()
        self._fetcher = ArticleFetcher(
            session=self._session,
            http_semaphore=asyncio.Semaphore(self.concurrency),
            browser_semaphore=asyncio.Semaphore(self.browser_concurrency),
            min_text_length=self.min_text_length,
            request_timeout=self.request_timeout,
            selenium_config=self.selenium_config,
            use_browser_fallback=self.use_browser_fallback,
        )

    async def stop(self) -> None:
        """Close the fetcher (Selenium driver) and the HTTP session."""
        if self._fetcher is not None:
            await self._fetcher.close()
            self._fetcher = None
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _ensure_started(self) -> ArticleFetcher:
        """Lazily start the toolkit — agents don't always call ``start()``."""
        if self._fetcher is None:
            await self.start()
        return self._fetcher  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    async def read_feeds(
        self,
        feed_urls: Optional[List[str]] = None,
        max_items: Optional[int] = None,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fetch RSS feeds and archive the full content of every linked article.

        Reads the configured feeds (plus any ad-hoc feed_urls) concurrently,
        downloads the complete page of each item, and saves raw HTML and
        extracted text to disk. Returns one metadata dictionary per item
        (title, link, published, summary, item_id, html_path, text_path,
        fetch_status) — never the article content itself. Use rss_get_content
        with an item_id to read an article's content.

        Args:
            feed_urls: Optional additional feed URLs to read alongside the
                configured feeds.
            max_items: Cap on items processed per feed for this call.
            force_refresh: Re-download items that are already archived.

        Returns:
            A list of item metadata dictionaries.
        """
        fetcher = await self._ensure_started()
        sites = self.feeds + [FeedSite(url=u) for u in (feed_urls or [])]
        if not sites:
            return [{"error": "No feeds configured and no feed_urls provided."}]
        results = await asyncio.gather(
            *(
                self._process_feed(fetcher, site, max_items, force_refresh)
                for site in sites
            )
        )
        return [meta.to_llm_dict() for feed_metas in results for meta in feed_metas]

    @tool_schema(GetContentInput)
    async def get_content(
        self, item: str, format: str = "text", max_chars: int = 20000
    ) -> Dict[str, Any]:
        """Retrieve the archived content of a previously fetched article.

        Args:
            item: The 16-char item_id returned by rss_read_feeds, or a saved
                html_path/text_path.
            format: 'text' for the extracted article text, 'html' for the
                raw page HTML.
            max_chars: Maximum number of characters to return.

        Returns:
            A dict with keys item, format, content, and truncated — or an
            error dict when the item is unknown or the path is invalid.
        """
        try:
            content = await self.storage.read_content(item, format)
        except ValueError as exc:
            return {"error": str(exc)}
        truncated = len(content) > max_chars
        return {
            "item": item,
            "format": format,
            "content": content[:max_chars],
            "truncated": truncated,
        }

    async def list_feeds(self) -> List[Dict[str, Any]]:
        """List the RSS feeds this toolkit is configured to read.

        Returns:
            One dict per configured feed with url, name, slug, max_items,
            and use_browser.
        """
        return [
            {**site.model_dump(exclude_none=True), "slug": site.slug}
            for site in self.feeds
        ]

    async def list_saved(
        self, feed: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List previously archived feed items, newest first.

        Args:
            feed: Optional feed slug to filter by (see rss_list_feeds).
            limit: Maximum number of items to return.

        Returns:
            A list of archived item metadata dictionaries.
        """
        return await asyncio.to_thread(self.storage.list_saved, feed, limit)

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    async def _process_feed(
        self,
        fetcher: ArticleFetcher,
        site: FeedSite,
        max_items: Optional[int],
        force_refresh: bool,
    ) -> List[FeedItemMetadata]:
        """Fetch, parse, and archive one feed; errors stay local to the feed."""
        try:
            xml = await fetcher.fetch_feed_xml(site.url)
            parsed = await fetcher.parse_feed(xml)
        except Exception as exc:  # noqa: BLE001 — one bad feed must not kill the batch
            self.logger.warning("Failed to read feed %s: %s", site.url, exc)
            return [
                FeedItemMetadata(
                    item_id=make_item_id(site.url),
                    feed=site.slug,
                    feed_url=site.url,
                    fetch_status="failed",
                    error=f"Feed fetch failed: {exc}",
                )
            ]
        limit = site.max_items or max_items or self.max_items_per_feed
        entries = parsed.entries[:limit]
        if not entries:
            return []
        return list(
            await asyncio.gather(
                *(
                    self._process_entry(fetcher, site, entry, force_refresh)
                    for entry in entries
                )
            )
        )

    async def _process_entry(
        self,
        fetcher: ArticleFetcher,
        site: FeedSite,
        entry: Any,
        force_refresh: bool,
    ) -> FeedItemMetadata:
        """Archive one feed entry's article page and return its metadata."""
        link = entry.get("link", "") or ""
        item_id = make_item_id(link or entry.get("id", site.url))

        if link and not force_refresh and self.storage.has_item(site.slug, item_id):
            cached = self.storage.load_metadata(site.slug, item_id)
            if cached is not None:
                cached.fetch_status = "cached"
                return cached

        meta = FeedItemMetadata(
            item_id=item_id,
            feed=site.slug,
            feed_url=site.url,
            title=entry.get("title", "") or "",
            link=link,
            published=self._published_iso(entry),
            summary=self._entry_summary(entry),
            author=entry.get("author") or None,
        )
        if not link:
            meta.error = "Feed entry has no link"
            return meta

        page = await fetcher.fetch_page(link, use_browser=site.use_browser)
        meta.fetch_method = page.method
        if page.html:
            meta.fetch_status = "fetched"
            meta.error = page.error
            meta = await self.storage.save_item(meta, page.html, page.text)
        else:
            meta.fetch_status = "failed"
            meta.error = page.error or "Empty response"
        return meta

    @staticmethod
    def _published_iso(entry: Any) -> Optional[str]:
        """Best-effort ISO-8601 publication timestamp from a feed entry."""
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            try:
                return time.strftime("%Y-%m-%dT%H:%M:%SZ", parsed)
            except (TypeError, ValueError):
                pass
        return entry.get("published") or entry.get("updated") or None

    @staticmethod
    def _entry_summary(entry: Any) -> Optional[str]:
        """Feed-provided summary, truncated for token economy."""
        summary = entry.get("summary") or entry.get("description") or ""
        if not summary:
            return None
        # Summaries often carry HTML markup.
        clean = extract_text(summary) or summary
        return clean[:SUMMARY_MAX_CHARS]
