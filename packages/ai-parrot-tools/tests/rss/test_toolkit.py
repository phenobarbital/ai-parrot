"""Tests for parrot_tools.rss.toolkit.RSSFeedReaderToolkit."""
import asyncio

import pytest
from aiohttp import web

from parrot_tools import TOOL_REGISTRY
from parrot_tools.rss.models import FeedSite

EXPECTED_TOOLS = {"rss_read_feeds", "rss_get_content", "rss_list_feeds", "rss_list_saved"}

ARTICLE_HTML = (
    "<html><body><article>" + ("Interesting article content. " * 60) + "</article></body></html>"
)


def _rss_xml(base_url: str, n_items: int = 2) -> str:
    items = "".join(
        f"""<item>
            <title>Article {i}</title>
            <link>{base_url}/articles/{i}</link>
            <description>Summary of article {i}</description>
            <pubDate>Mon, 13 Jul 2026 10:0{i}:00 GMT</pubDate>
        </item>"""
        for i in range(n_items)
    )
    return f"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Test Feed</title>{items}</channel></rss>"""


def test_registered_in_tool_registry():
    assert TOOL_REGISTRY["rss_feed_reader"] == "parrot_tools.rss.toolkit.RSSFeedReaderToolkit"


def test_module_imports_without_optional_deps():
    # The module must import even when feedparser/trafilatura/selenium are
    # absent (guarded imports) — this mirrors test_imports_integrity.py.
    from parrot_tools.rss import toolkit as _  # noqa: F401


# Everything below exercises feed parsing and needs feedparser.
feedparser = pytest.importorskip("feedparser")

from parrot_tools.rss.toolkit import RSSFeedReaderToolkit  # noqa: E402


@pytest.fixture
async def feed_server(aiohttp_server):
    """Local server exposing /feed.xml plus two article pages, with hit counts."""
    hits = {"feed": 0, "articles": 0}

    async def feed_handler(request):
        hits["feed"] += 1
        base = f"http://{request.host}"
        return web.Response(text=_rss_xml(base), content_type="application/rss+xml")

    async def article_handler(request):
        hits["articles"] += 1
        return web.Response(text=ARTICLE_HTML, content_type="text/html")

    app = web.Application()
    app.router.add_get("/feed.xml", feed_handler)
    app.router.add_get("/articles/{i}", article_handler)
    server = await aiohttp_server(app)
    server.hits = hits
    return server


def _toolkit(tmp_path, server=None, **kwargs) -> RSSFeedReaderToolkit:
    feeds = kwargs.pop(
        "feeds",
        [str(server.make_url("/feed.xml"))] if server else [],
    )
    defaults = dict(
        feeds=feeds,
        storage_dir=tmp_path / "rss",
        use_browser_fallback=False,
        min_text_length=50,
    )
    defaults.update(kwargs)
    return RSSFeedReaderToolkit(**defaults)


def test_tool_surface(tmp_path):
    tk = _toolkit(tmp_path)
    names = {t.name for t in tk.get_tools()}
    assert EXPECTED_TOOLS <= names


def test_feed_normalization(tmp_path):
    tk = _toolkit(
        tmp_path,
        feeds=[
            "https://example.com/a.xml",
            {"url": "https://example.com/b.xml", "name": "My Feed", "use_browser": True},
            FeedSite(url="https://example.com/c.xml", max_items=3),
        ],
    )
    assert all(isinstance(site, FeedSite) for site in tk.feeds)
    assert tk.feeds[1].use_browser is True
    assert tk.feeds[1].slug == "my-feed"
    assert tk.feeds[2].max_items == 3


def test_default_storage_dir(tmp_path):
    tk = RSSFeedReaderToolkit(feeds=[])
    assert str(tk.storage.base_dir).endswith("outputs/rss_feeds")


async def test_read_feeds_end_to_end(tmp_path, feed_server):
    tk = _toolkit(tmp_path, feed_server)
    try:
        items = await tk.read_feeds()
    finally:
        await tk.stop()

    assert len(items) == 2
    for item in items:
        assert item["fetch_status"] == "fetched"
        assert item["fetch_method"] == "aiohttp"
        assert item["title"].startswith("Article")
        assert item["summary"].startswith("Summary")
        assert item["published"].startswith("2026-07-13")
        assert len(item["item_id"]) == 16
        # Paths returned, content NOT returned
        assert "content" not in item
        assert "html" not in item
        html_path = tmp_path / "rss"
        assert item["html_path"].startswith(str(html_path))
        assert item["text_path"].startswith(str(html_path))

    # Files really on disk
    from pathlib import Path

    assert "Interesting article content" in Path(items[0]["text_path"]).read_text()
    assert Path(items[0]["html_path"]).read_text() == ARTICLE_HTML


async def test_read_feeds_dedup_and_force_refresh(tmp_path, feed_server):
    tk = _toolkit(tmp_path, feed_server)
    try:
        first = await tk.read_feeds()
        assert feed_server.hits["articles"] == 2

        second = await tk.read_feeds()
        assert all(item["fetch_status"] == "cached" for item in second)
        assert feed_server.hits["articles"] == 2  # no article re-fetch

        third = await tk.read_feeds(force_refresh=True)
        assert all(item["fetch_status"] == "fetched" for item in third)
        assert feed_server.hits["articles"] == 4
    finally:
        await tk.stop()
    assert {i["item_id"] for i in first} == {i["item_id"] for i in second}


async def test_read_feeds_adhoc_urls(tmp_path, feed_server):
    tk = _toolkit(tmp_path, feeds=[])
    try:
        items = await tk.read_feeds(feed_urls=[str(feed_server.make_url("/feed.xml"))])
    finally:
        await tk.stop()
    assert len(items) == 2
    assert all(item["fetch_status"] == "fetched" for item in items)


async def test_read_feeds_max_items(tmp_path, feed_server):
    tk = _toolkit(tmp_path, feed_server)
    try:
        items = await tk.read_feeds(max_items=1)
    finally:
        await tk.stop()
    assert len(items) == 1


async def test_read_feeds_empty_config(tmp_path):
    tk = _toolkit(tmp_path, feeds=[])
    try:
        result = await tk.read_feeds()
    finally:
        await tk.stop()
    assert result == [{"error": "No feeds configured and no feed_urls provided."}]


async def test_bad_feed_does_not_kill_batch(tmp_path, feed_server):
    good = str(feed_server.make_url("/feed.xml"))
    bad = str(feed_server.make_url("/nope.xml"))
    tk = _toolkit(tmp_path, feeds=[bad, good])
    try:
        items = await tk.read_feeds()
    finally:
        await tk.stop()
    failed = [i for i in items if i["fetch_status"] == "failed"]
    fetched = [i for i in items if i["fetch_status"] == "fetched"]
    assert len(failed) == 1
    assert "Feed fetch failed" in failed[0]["error"]
    assert len(fetched) == 2


async def test_get_content(tmp_path, feed_server):
    tk = _toolkit(tmp_path, feed_server)
    try:
        items = await tk.read_feeds()
        item_id = items[0]["item_id"]

        text = await tk.get_content(item_id)
        assert text["format"] == "text"
        assert "Interesting article content" in text["content"]
        assert text["truncated"] is False

        html = await tk.get_content(item_id, format="html")
        assert html["content"] == ARTICLE_HTML

        short = await tk.get_content(item_id, max_chars=100)
        assert len(short["content"]) == 100
        assert short["truncated"] is True

        missing = await tk.get_content("0" * 16)
        assert "error" in missing

        traversal = await tk.get_content("../../etc/passwd")
        assert "error" in traversal
    finally:
        await tk.stop()


async def test_list_feeds_and_list_saved(tmp_path, feed_server):
    tk = _toolkit(tmp_path, feed_server)
    try:
        feeds = await tk.list_feeds()
        assert len(feeds) == 1
        assert feeds[0]["url"] == str(feed_server.make_url("/feed.xml"))
        assert "slug" in feeds[0]

        assert await tk.list_saved() == []
        await tk.read_feeds()
        saved = await tk.list_saved()
        assert len(saved) == 2
        assert await tk.list_saved(limit=1) != []
        assert await tk.list_saved(feed="does-not-exist") == []
    finally:
        await tk.stop()


async def test_start_requires_feedparser(tmp_path, monkeypatch):
    import parrot_tools.rss.toolkit as toolkit_mod

    monkeypatch.setattr(toolkit_mod, "HAS_FEEDPARSER", False)
    tk = _toolkit(tmp_path)
    with pytest.raises(RuntimeError, match=r"ai-parrot-tools\[rss\]"):
        await tk.start()


async def test_stop_closes_session(tmp_path, feed_server):
    tk = _toolkit(tmp_path, feed_server)
    await tk.read_feeds()
    session = tk._session
    assert session is not None and not session.closed
    await tk.stop()
    assert session.closed
    assert tk._session is None and tk._fetcher is None
