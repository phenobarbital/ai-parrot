"""Tests for parrot_tools.rss.storage — no optional dependencies required."""
import time

import pytest

from parrot_tools.rss.models import FeedItemMetadata, make_item_id
from parrot_tools.rss.storage import RSSStorage


def _meta(link: str = "https://example.com/article-1", feed: str = "example") -> FeedItemMetadata:
    return FeedItemMetadata(
        item_id=make_item_id(link),
        feed=feed,
        feed_url="https://example.com/feed.xml",
        title="An Article",
        link=link,
        fetch_method="aiohttp",
        fetch_status="fetched",
    )


async def test_save_and_load_roundtrip(tmp_path):
    storage = RSSStorage(tmp_path)
    meta = _meta()
    saved = await storage.save_item(meta, "<html><body>hi</body></html>", "hi")

    item_dir = tmp_path / "example" / meta.item_id
    assert (item_dir / "page.html").exists()
    assert (item_dir / "content.txt").exists()
    assert (item_dir / "item.json").exists()
    assert saved.html_path == str(item_dir / "page.html")
    assert saved.text_path == str(item_dir / "content.txt")

    loaded = storage.load_metadata("example", meta.item_id)
    assert loaded is not None
    assert loaded.title == "An Article"
    assert loaded.html_path == saved.html_path


async def test_has_item_dedup(tmp_path):
    storage = RSSStorage(tmp_path)
    meta = _meta()
    assert not storage.has_item("example", meta.item_id)
    await storage.save_item(meta, "<html></html>", "text")
    assert storage.has_item("example", meta.item_id)


async def test_find_item_across_feeds(tmp_path):
    storage = RSSStorage(tmp_path)
    meta = _meta(feed="other-feed")
    await storage.save_item(meta, "<html></html>", "text")
    found = storage.find_item(meta.item_id)
    assert found is not None
    assert found.name == meta.item_id
    assert found.parent.name == "other-feed"
    assert storage.find_item("0" * 16) is None


async def test_list_saved_filter_limit_order(tmp_path):
    storage = RSSStorage(tmp_path)
    links = [f"https://example.com/a{i}" for i in range(3)]
    for i, link in enumerate(links):
        feed = "feed-a" if i < 2 else "feed-b"
        await storage.save_item(_meta(link=link, feed=feed), "<html></html>", "t")
        time.sleep(0.01)  # distinct mtimes for deterministic ordering

    all_items = storage.list_saved()
    assert len(all_items) == 3
    # Newest first
    assert all_items[0]["link"] == links[2]

    only_a = storage.list_saved(feed_slug="feed-a")
    assert len(only_a) == 2
    assert {m["feed"] for m in only_a} == {"feed-a"}

    limited = storage.list_saved(limit=1)
    assert len(limited) == 1


async def test_read_content_by_item_id_and_path(tmp_path):
    storage = RSSStorage(tmp_path)
    meta = _meta()
    saved = await storage.save_item(meta, "<html>raw</html>", "clean text")

    assert await storage.read_content(meta.item_id, "text") == "clean text"
    assert await storage.read_content(meta.item_id, "html") == "<html>raw</html>"
    assert await storage.read_content(saved.text_path, "text") == "clean text"
    # Directory ref gets the format file appended
    item_dir = str(tmp_path / "example" / meta.item_id)
    assert await storage.read_content(item_dir, "html") == "<html>raw</html>"


def test_resolve_content_path_html(tmp_path):
    storage = RSSStorage(tmp_path)
    meta = _meta()
    item_dir = tmp_path / "example" / meta.item_id
    item_dir.mkdir(parents=True)
    (item_dir / "page.html").write_text("<html></html>")
    (item_dir / "item.json").write_text("{}")
    resolved = storage.resolve_content_path(meta.item_id, "html")
    assert resolved.name == "page.html"


def test_traversal_rejected(tmp_path):
    storage = RSSStorage(tmp_path / "store")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")

    with pytest.raises(ValueError, match="outside"):
        storage.resolve_content_path("../secret.txt", "text")
    with pytest.raises(ValueError, match="outside"):
        storage.resolve_content_path(str(outside), "text")
    with pytest.raises(ValueError, match="outside"):
        storage.resolve_content_path("/etc/passwd", "text")


def test_symlink_escape_rejected(tmp_path):
    storage = RSSStorage(tmp_path / "store")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    link = storage.base_dir / "sneaky.txt"
    link.symlink_to(outside)

    with pytest.raises(ValueError, match="outside"):
        storage.resolve_content_path("sneaky.txt", "text")


def test_unknown_format_and_missing_item(tmp_path):
    storage = RSSStorage(tmp_path)
    with pytest.raises(ValueError, match="format"):
        storage.resolve_content_path("a" * 16, "pdf")
    with pytest.raises(ValueError, match="No archived item"):
        storage.resolve_content_path("a" * 16, "text")
