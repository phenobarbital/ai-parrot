"""Tests for WebScrapingLoader.

Uses mocked ScrapingResult / CrawlResult to avoid real browser sessions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from bs4 import BeautifulSoup

from parrot_loaders.webscraping import WebScrapingLoader
from parrot.stores.models import Document


# ── Fixtures ──────────────────────────────────────────────────────────

SAMPLE_HTML = """\
<html lang="en">
<head>
    <title>Test Page</title>
    <meta name="description" content="A test page for scraping">
</head>
<body>
    <nav>
        <ul>
            <li><a href="/home">Home</a></li>
            <li><a href="/about">About</a></li>
        </ul>
    </nav>
    <article>
        <h1>Main Title</h1>
        <p>First paragraph with some content.</p>
        <p>Second paragraph with more content.</p>
        <table>
            <thead><tr><th>Name</th><th>Value</th></tr></thead>
            <tbody><tr><td>alpha</td><td>100</td></tr></tbody>
        </table>
        <iframe src="https://youtube.com/embed/abc123"></iframe>
    </article>
    <section>
        <h2>Section Title</h2>
        <p>Section content here.</p>
    </section>
</body>
</html>
"""


@dataclass
class FakeScrapingResult:
    """Mimics ScrapingResult from parrot_tools.scraping.models."""
    url: str
    content: str
    bs_soup: BeautifulSoup
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class FakeCrawlResult:
    """Mimics CrawlResult from parrot_tools.scraping.crawl_graph."""
    start_url: str
    depth: int
    pages: List[Any]
    visited_urls: List[str]
    failed_urls: List[str]
    total_pages: int
    total_elapsed_seconds: float
    plan_used: Optional[str] = None


def _make_result(
    url: str = "https://example.com",
    html: str = SAMPLE_HTML,
    extracted_data: Optional[Dict[str, Any]] = None,
    success: bool = True,
) -> FakeScrapingResult:
    return FakeScrapingResult(
        url=url,
        content=html,
        bs_soup=BeautifulSoup(html, "html.parser"),
        extracted_data=extracted_data or {},
        success=success,
        error_message=None if success else "test error",
    )


def _mock_toolkit(scrape_result=None, crawl_result=None):
    """Create a mock WebScrapingToolkit."""
    mock = MagicMock()
    if scrape_result is not None:
        mock.scrape = AsyncMock(return_value=scrape_result)
    if crawl_result is not None:
        mock.crawl = AsyncMock(return_value=crawl_result)
    return mock


# ── Tests: Basic single-page scrape ──────────────────────────────────

@pytest.mark.asyncio
async def test_basic_scrape_produces_documents():
    """Default single-page scrape should produce markdown_full, no fragments.

    Fragments are opt-in as of the per-tag noise fix — callers must pass
    an explicit ``tags=[...]`` list to get them.
    """
    result = _make_result()
    loader = WebScrapingLoader(source="https://example.com")
    loader._toolkit = _mock_toolkit(scrape_result=result)

    docs = await loader._load("https://example.com")

    assert len(docs) > 0
    kinds = {d.metadata.get("content_kind") for d in docs}
    # Either trafilatura_main (when trafilatura is installed and the
    # extraction ratio is above threshold) or markdown_full (fallback).
    assert kinds & {"markdown_full", "trafilatura_main"}
    # Fragments must NOT be emitted by default.
    assert "fragment" not in kinds

    # All docs should have source URL; source_type is "url" after TASK-860 refactor
    for doc in docs:
        assert doc.metadata["url"] == "https://example.com"
        assert doc.metadata["source_type"] == "url"


@pytest.mark.asyncio
async def test_fragments_opt_in():
    """Passing an explicit tags list re-enables fragment emission."""
    result = _make_result()
    loader = WebScrapingLoader(
        source="https://example.com",
        tags=["p", "h1", "h2", "article", "section"],
    )
    loader._toolkit = _mock_toolkit(scrape_result=result)

    docs = await loader._load("https://example.com")

    kinds = {d.metadata.get("content_kind") for d in docs}
    assert "fragment" in kinds


@pytest.mark.asyncio
async def test_scrape_with_selectors():
    """Selectors should appear in toolkit.scrape() call."""
    result = _make_result(extracted_data={"title": "Main Title", "body": "content"})
    selectors = [
        {"name": "title", "selector": "h1", "extract_type": "text"},
        {"name": "body", "selector": "article", "extract_type": "text"},
    ]
    loader = WebScrapingLoader(
        source="https://example.com",
        selectors=selectors,
    )
    mock_tk = _mock_toolkit(scrape_result=result)
    loader._toolkit = mock_tk

    docs = await loader._load("https://example.com")

    # Should have selector documents
    selector_docs = [d for d in docs if d.metadata.get("content_kind") == "selector"]
    assert len(selector_docs) == 2
    names = {d.metadata["selector_name"] for d in selector_docs}
    assert names == {"title", "body"}

    # Verify selectors were passed to toolkit
    call_kwargs = mock_tk.scrape.call_args.kwargs
    assert call_kwargs["selectors"] == selectors


@pytest.mark.asyncio
async def test_scrape_with_custom_tags():
    """Custom tags should filter which HTML elements become fragments."""
    result = _make_result()
    loader = WebScrapingLoader(
        source="https://example.com",
        tags=["h1"],  # Only h1 tags
    )
    loader._toolkit = _mock_toolkit(scrape_result=result)

    docs = await loader._load("https://example.com")

    fragments = [d for d in docs if d.metadata.get("content_kind") == "fragment"]
    # Only h1 tags should be extracted
    for frag in fragments:
        assert frag.metadata["html_tag"] == "h1"


@pytest.mark.asyncio
async def test_scrape_with_steps():
    """Custom steps should be passed directly to toolkit.scrape()."""
    result = _make_result()
    steps = [
        {"action": "navigate", "url": "https://example.com/login"},
        {"action": "fill", "selector": "#email", "value": "test@test.com"},
        {"action": "click", "selector": "button[type=submit]"},
    ]
    loader = WebScrapingLoader(
        source="https://example.com",
        steps=steps,
    )
    mock_tk = _mock_toolkit(scrape_result=result)
    loader._toolkit = mock_tk

    await loader._load("https://example.com")

    call_kwargs = mock_tk.scrape.call_args.kwargs
    assert call_kwargs["steps"] == steps


@pytest.mark.asyncio
async def test_scrape_with_objective():
    """Objective should trigger plan auto-generation in toolkit."""
    result = _make_result()
    loader = WebScrapingLoader(
        source="https://example.com",
        objective="Extract product prices",
    )
    mock_tk = _mock_toolkit(scrape_result=result)
    loader._toolkit = mock_tk

    await loader._load("https://example.com")

    call_kwargs = mock_tk.scrape.call_args.kwargs
    assert call_kwargs["objective"] == "Extract product prices"
    assert "steps" not in call_kwargs


# ── Tests: Content extraction features ────────────────────────────────

@pytest.mark.asyncio
async def test_video_links_extracted():
    """Videos should be extracted when parse_videos=True."""
    result = _make_result()
    loader = WebScrapingLoader(
        source="https://example.com",
        parse_videos=True,
    )
    loader._toolkit = _mock_toolkit(scrape_result=result)

    docs = await loader._load("https://example.com")

    video_docs = [d for d in docs if d.metadata.get("content_kind") == "video_link"]
    assert len(video_docs) >= 1
    assert "youtube.com" in video_docs[0].page_content


@pytest.mark.asyncio
async def test_no_videos_when_disabled():
    """No video documents when parse_videos=False."""
    result = _make_result()
    loader = WebScrapingLoader(
        source="https://example.com",
        parse_videos=False,
    )
    loader._toolkit = _mock_toolkit(scrape_result=result)

    docs = await loader._load("https://example.com")

    video_docs = [d for d in docs if d.metadata.get("content_kind") == "video_link"]
    assert len(video_docs) == 0


@pytest.mark.asyncio
async def test_tables_extracted():
    """Tables should be extracted as markdown when parse_tables=True."""
    result = _make_result()
    loader = WebScrapingLoader(
        source="https://example.com",
        parse_tables=True,
    )
    loader._toolkit = _mock_toolkit(scrape_result=result)

    docs = await loader._load("https://example.com")

    table_docs = [d for d in docs if d.metadata.get("content_kind") == "table"]
    assert len(table_docs) >= 1
    assert "Name" in table_docs[0].page_content
    assert "alpha" in table_docs[0].page_content


@pytest.mark.asyncio
async def test_navbars_extracted():
    """Navbars should be extracted when parse_navs=True."""
    result = _make_result()
    loader = WebScrapingLoader(
        source="https://example.com",
        parse_navs=True,
    )
    loader._toolkit = _mock_toolkit(scrape_result=result)

    docs = await loader._load("https://example.com")

    nav_docs = [d for d in docs if d.metadata.get("content_kind") == "navigation"]
    assert len(nav_docs) >= 1
    assert "Home" in nav_docs[0].page_content


@pytest.mark.asyncio
async def test_text_format():
    """content_format='text' should produce text_full instead of markdown_full."""
    result = _make_result()
    loader = WebScrapingLoader(
        source="https://example.com",
        content_format="text",
    )
    loader._toolkit = _mock_toolkit(scrape_result=result)

    docs = await loader._load("https://example.com")

    kinds = {d.metadata.get("content_kind") for d in docs}
    assert "text_full" in kinds
    assert "markdown_full" not in kinds


# ── Tests: Metadata ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metadata_fields():
    """Documents should have complete metadata."""
    result = _make_result()
    loader = WebScrapingLoader(source="https://example.com")
    loader._toolkit = _mock_toolkit(scrape_result=result)

    docs = await loader._load("https://example.com")

    doc = docs[0]
    assert doc.metadata["url"] == "https://example.com"
    assert doc.metadata["source"] == "https://example.com"
    assert doc.metadata["filename"] == "Test Page"
    assert doc.metadata["type"] == "webpage"
    assert doc.metadata["document_meta"]["title"] == "Test Page"
    assert doc.metadata["document_meta"]["language"] == "en"
    # description is a top-level key after TASK-860 canonical metadata refactor
    assert doc.metadata["description"] == "A test page for scraping"
    assert "description" not in doc.metadata["document_meta"]


# ── Tests: Crawling ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crawl_mode():
    """Crawl mode should call toolkit.crawl() and return docs from all pages."""
    page1 = _make_result(url="https://example.com")
    page2 = _make_result(
        url="https://example.com/about",
        html="<html><head><title>About</title></head><body><p>About us</p></body></html>",
    )
    crawl_result = FakeCrawlResult(
        start_url="https://example.com",
        depth=1,
        pages=[page1, page2],
        visited_urls=["https://example.com", "https://example.com/about"],
        failed_urls=[],
        total_pages=2,
        total_elapsed_seconds=3.5,
    )

    loader = WebScrapingLoader(
        source="https://example.com",
        crawl=True,
        depth=1,
        max_pages=10,
        follow_pattern=r"/.*",
    )
    mock_tk = _mock_toolkit(crawl_result=crawl_result)
    loader._toolkit = mock_tk

    docs = await loader._load("https://example.com")

    assert len(docs) > 0
    # Should have docs from both pages
    urls = {d.metadata["url"] for d in docs}
    assert "https://example.com" in urls
    assert "https://example.com/about" in urls

    # Verify crawl params
    call_kwargs = mock_tk.crawl.call_args.kwargs
    assert call_kwargs["depth"] == 1
    assert call_kwargs["max_pages"] == 10
    assert call_kwargs["follow_pattern"] == r"/.*"


@pytest.mark.asyncio
async def test_crawl_with_follow_selector():
    """follow_selector should be forwarded to crawl()."""
    crawl_result = FakeCrawlResult(
        start_url="https://example.com",
        depth=1,
        pages=[_make_result()],
        visited_urls=["https://example.com"],
        failed_urls=[],
        total_pages=1,
        total_elapsed_seconds=1.0,
    )

    loader = WebScrapingLoader(
        source="https://example.com",
        crawl=True,
        follow_selector="nav a[href]",
    )
    mock_tk = _mock_toolkit(crawl_result=crawl_result)
    loader._toolkit = mock_tk

    await loader._load("https://example.com")

    call_kwargs = mock_tk.crawl.call_args.kwargs
    assert call_kwargs["follow_selector"] == "nav a[href]"


# ── Tests: Failed results ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failed_result_produces_no_documents():
    """A failed ScrapingResult should be skipped."""
    result = _make_result(success=False)
    loader = WebScrapingLoader(source="https://example.com")
    loader._toolkit = _mock_toolkit(scrape_result=result)

    docs = await loader._load("https://example.com")
    assert len(docs) == 0


# ── Tests: Default navigate step ─────────────────────────────────────

@pytest.mark.asyncio
async def test_default_navigate_step():
    """Without steps/plan/objective, a navigate step should be auto-generated."""
    result = _make_result()
    loader = WebScrapingLoader(source="https://example.com")
    mock_tk = _mock_toolkit(scrape_result=result)
    loader._toolkit = mock_tk

    await loader._load("https://example.com")

    call_kwargs = mock_tk.scrape.call_args.kwargs
    assert call_kwargs["steps"] == [
        {
            "action": "navigate",
            "url": "https://example.com",
            "description": "Navigate to https://example.com",
        }
    ]


# ── Tests: Import paths ─────────────────────────────────────────────

def test_import_from_parrot_loaders():
    """WebScrapingLoader should be importable from parrot_loaders."""
    from parrot_loaders.webscraping import WebScrapingLoader as WL
    assert WL.__name__ == "WebScrapingLoader"


def test_registry_entry():
    """WebScrapingLoader should be in the LOADER_REGISTRY."""
    from parrot_loaders import LOADER_REGISTRY
    assert "WebScrapingLoader" in LOADER_REGISTRY
    assert LOADER_REGISTRY["WebScrapingLoader"] == "parrot_loaders.webscraping.WebScrapingLoader"
