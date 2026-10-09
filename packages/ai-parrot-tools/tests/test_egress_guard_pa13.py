"""PA-13 through the real tools: with the host guard on, their own fetches never reach a private address."""

from __future__ import annotations

import pytest
from aiohttp import web

import parrot.tools.egress as egress

pytestmark = pytest.mark.asyncio

AllowedOutside = {"127.0.0.1"}  # the test's stand-in for a public host; 127.0.0.2 is the "internal" one


@pytest.fixture(autouse=True)
def _guard(monkeypatch):
    real = egress.is_public_address
    monkeypatch.setattr(egress, "is_public_address", lambda a: a in AllowedOutside or real(a))
    egress.configure(True)
    yield
    egress.configure(False)


async def _serve(handler, host: str):
    app = web.Application()
    app.router.add_get("/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, 0)
    await site.start()
    return runner, site._server.sockets[0].getsockname()[1]


async def test_rss_item_links_into_the_internal_network_are_never_fetched(tmp_path):
    pytest.importorskip("feedparser")
    from parrot_tools.rss.toolkit import RSSFeedReaderToolkit

    internal_hits: list[str] = []

    async def internal(request):
        internal_hits.append(request.path)
        return web.Response(text="secret", content_type="text/html")

    internal_runner, internal_port = await _serve(internal, "127.0.0.2")
    feed = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><item><title>a</title>'
        f"<link>http://127.0.0.2:{internal_port}/admin</link><description>d</description></item></channel></rss>"
    )

    async def feed_handler(request):
        return web.Response(text=feed, content_type="application/rss+xml")

    feed_runner, feed_port = await _serve(feed_handler, "127.0.0.1")
    toolkit = RSSFeedReaderToolkit(
        feeds=[f"http://127.0.0.1:{feed_port}/feed.xml"], storage_dir=tmp_path / "rss",
        use_browser_fallback=False, min_text_length=50,
    )
    try:
        rows = await toolkit.read_feeds()
    finally:
        await toolkit.stop()
        await feed_runner.cleanup()
        await internal_runner.cleanup()
    assert internal_hits == []
    assert rows and rows[0]["fetch_status"] != "ok"


async def test_word_to_markdown_download_of_a_private_url_is_refused():
    from parrot_tools.msword import WordToMarkdownTool

    hits: list[str] = []

    async def handler(request):
        hits.append(request.path)
        return web.Response(body=b"x")

    runner, port = await _serve(handler, "127.0.0.2")
    tool = WordToMarkdownTool()
    try:
        with pytest.raises(egress.EgressBlocked):
            await tool._download_file(f"http://127.0.0.2:{port}/a.docx")
    finally:
        await runner.cleanup()
    assert hits == []


async def test_wiki_url_source_fetch_is_guarded(tmp_path):
    from parrot.knowledge.wiki.documents import DocumentAcquisitionError
    from parrot.knowledge.wiki import documents

    hits: list[str] = []

    async def handler(request):
        hits.append(request.path)
        return web.Response(text="# secret")

    runner, port = await _serve(handler, "127.0.0.2")
    acquirer = documents.DocumentAcquirer.__new__(documents.DocumentAcquirer)
    acquirer.fetch_timeout, acquirer.max_bytes, acquirer.cache_dir = 5, 1024, tmp_path
    try:
        with pytest.raises(DocumentAcquisitionError):
            await acquirer._download(f"http://127.0.0.2:{port}/s.md")
    finally:
        await runner.cleanup()
    assert hits == []
