"""Tests for parrot_tools.rss.fetcher."""
import asyncio
from unittest.mock import AsyncMock

import aiohttp
import pytest
from aiohttp import web

from parrot_tools.rss import fetcher as fetcher_mod
from parrot_tools.rss.fetcher import ArticleFetcher, extract_text
from parrot_tools.rss.models import FetchedPage

RICH_HTML = "<html><body><article>" + ("Lots of real content. " * 100) + "</article></body></html>"
JS_SHELL_HTML = '<html><body><div id="root"></div></body></html>'


def _make_fetcher(session, **kwargs) -> ArticleFetcher:
    defaults = dict(
        session=session,
        http_semaphore=asyncio.Semaphore(5),
        browser_semaphore=asyncio.Semaphore(1),
        min_text_length=100,
    )
    defaults.update(kwargs)
    return ArticleFetcher(**defaults)


def test_extract_text_bs4_fallback(monkeypatch):
    monkeypatch.setattr(fetcher_mod, "HAS_TRAFILATURA", False)
    html = "<html><head><style>x{}</style><script>bad()</script></head><body><p>Hello world</p></body></html>"
    text = extract_text(html)
    assert "Hello world" in text
    assert "bad()" not in text
    assert "x{}" not in text
    assert extract_text("") == ""


def test_needs_fallback_truth_table():
    f = ArticleFetcher(
        session=None,  # type: ignore[arg-type]
        http_semaphore=asyncio.Semaphore(1),
        browser_semaphore=asyncio.Semaphore(1),
        min_text_length=100,
    )
    assert f._needs_fallback(FetchedPage(error="HTTP 403"))
    assert f._needs_fallback(FetchedPage(html=JS_SHELL_HTML, text="", thin=True))
    assert f._needs_fallback(FetchedPage(html="<html></html>", text="short", thin=True))
    assert f._needs_fallback(
        FetchedPage(html="<html>Please enable JavaScript to continue" + "x" * 500, text="y" * 200)
    )
    assert not f._needs_fallback(
        FetchedPage(html=RICH_HTML, text="y" * 200, thin=False)
    )


async def test_fetch_page_aiohttp_happy_path(aiohttp_server):
    async def handler(request):
        return web.Response(text=RICH_HTML, content_type="text/html")

    app = web.Application()
    app.router.add_get("/article", handler)
    server = await aiohttp_server(app)

    async with aiohttp.ClientSession() as session:
        f = _make_fetcher(session)
        f._fetch_with_selenium = AsyncMock()
        page = await f.fetch_page(str(server.make_url("/article")))

    assert page.method == "aiohttp"
    assert page.status_code == 200
    assert "Lots of real content" in page.text
    assert not page.thin
    f._fetch_with_selenium.assert_not_awaited()


async def test_fetch_page_js_shell_triggers_selenium(aiohttp_server):
    async def handler(request):
        return web.Response(text=JS_SHELL_HTML, content_type="text/html")

    app = web.Application()
    app.router.add_get("/spa", handler)
    server = await aiohttp_server(app)

    selenium_result = FetchedPage(
        html=RICH_HTML, text="rendered " * 50, method="selenium"
    )
    async with aiohttp.ClientSession() as session:
        f = _make_fetcher(session)
        f._fetch_with_selenium = AsyncMock(return_value=selenium_result)
        page = await f.fetch_page(str(server.make_url("/spa")))

    f._fetch_with_selenium.assert_awaited_once()
    assert page.method == "selenium"
    assert page.html == RICH_HTML


async def test_fetch_page_no_fallback_when_disabled(aiohttp_server):
    async def handler(request):
        return web.Response(text=JS_SHELL_HTML, content_type="text/html")

    app = web.Application()
    app.router.add_get("/spa", handler)
    server = await aiohttp_server(app)

    async with aiohttp.ClientSession() as session:
        f = _make_fetcher(session, use_browser_fallback=False)
        f._fetch_with_selenium = AsyncMock()
        page = await f.fetch_page(str(server.make_url("/spa")))

    f._fetch_with_selenium.assert_not_awaited()
    assert page.method == "aiohttp"
    assert page.thin


async def test_fetch_page_keeps_aiohttp_result_when_selenium_fails(aiohttp_server):
    async def handler(request):
        return web.Response(text=JS_SHELL_HTML, content_type="text/html")

    app = web.Application()
    app.router.add_get("/spa", handler)
    server = await aiohttp_server(app)

    async with aiohttp.ClientSession() as session:
        f = _make_fetcher(session)
        f._fetch_with_selenium = AsyncMock(
            return_value=FetchedPage(method="selenium", error="selenium unavailable")
        )
        page = await f.fetch_page(str(server.make_url("/spa")))

    assert page.method == "aiohttp"
    assert page.html == JS_SHELL_HTML
    assert "browser fallback failed" in page.error


async def test_fetch_page_use_browser_goes_straight_to_selenium():
    selenium_result = FetchedPage(html=RICH_HTML, text="rendered", method="selenium")
    f = _make_fetcher(None)  # session unused on the selenium path
    f._fetch_with_selenium = AsyncMock(return_value=selenium_result)
    page = await f.fetch_page("https://example.com/x", use_browser=True)
    f._fetch_with_selenium.assert_awaited_once()
    assert page is selenium_result


async def test_fetch_with_aiohttp_error_statuses(aiohttp_server):
    async def not_found(request):
        return web.Response(status=404)

    async def json_endpoint(request):
        return web.json_response({"a": 1})

    app = web.Application()
    app.router.add_get("/missing", not_found)
    app.router.add_get("/api", json_endpoint)
    server = await aiohttp_server(app)

    async with aiohttp.ClientSession() as session:
        f = _make_fetcher(session, use_browser_fallback=False)
        missing = await f.fetch_page(str(server.make_url("/missing")))
        api = await f.fetch_page(str(server.make_url("/api")))

    assert missing.error == "HTTP 404"
    assert missing.status_code == 404
    assert "Non-HTML" in api.error


async def test_parse_feed_requires_feedparser(monkeypatch):
    f = _make_fetcher(None)
    monkeypatch.setattr(fetcher_mod, "HAS_FEEDPARSER", False)
    with pytest.raises(RuntimeError, match=r"ai-parrot-tools\[rss\]"):
        await f.parse_feed("<rss/>")


async def test_parse_feed_with_feedparser():
    pytest.importorskip("feedparser")
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>T</title>
    <item><title>Item 1</title><link>https://example.com/1</link></item>
    </channel></rss>"""
    f = _make_fetcher(None)
    parsed = await f.parse_feed(xml)
    assert len(parsed.entries) == 1
    assert parsed.entries[0]["link"] == "https://example.com/1"


async def test_selenium_unavailable_returns_error(monkeypatch):
    f = _make_fetcher(None)
    f._selenium_unavailable = True
    page = await f._fetch_with_selenium("https://example.com/x")
    assert page.method == "selenium"
    assert page.error == "selenium unavailable"


async def test_close_without_driver_is_noop():
    f = _make_fetcher(None)
    await f.close()  # must not raise
