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


# ── Tests: JSON-LD FAQPage extraction ───────────────────────────────
#
# Real-world motivating case: schema.org/FAQPage embedded in
# <script type="application/ld+json"> on att.com/prepaid/. The loader
# must extract Q&A pairs deterministically and emit one Document per
# pair so the embedder receives (question + answer) as a single semantic
# unit. Without this, scrapers separate the question (in <h*>) from the
# answer (in a sibling panel) and the vector store ends up with
# answer-only chunks that never match user queries phrased as questions.

ATT_FAQ_FIXTURE_HTML = '''
<html><head><title>AT&T Prepaid Plans</title></head><body>
<div data-comp="accordion-duc">
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "What is AT&T Level Up?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "AT&amp;T Level Up is a feature that lets you use your payment history to &quot;level up&quot; to a new phone."
      }
    },
    {
      "@type": "Question",
      "name": "How do I access my AT&T Prepaid account?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "<p>You can access and manage your AT&amp;T Prepaid account by logging into <a href=\\"https://example.com\\">your account</a>.</p>\\nYour AT&amp;T Prepaid account allows you to see your data usage, change your plan, check your balance, enroll &amp; set up AutoPay."
      }
    },
    {
      "@type": "Question",
      "name": "How do I lease-to-own a phone with Progressive Leasing?",
      "acceptedAnswer": {
        "@type": "Answer",
        "text": "<p>Choose the phone you want. During checkout,&nbsp;you&rsquo;ll&nbsp;have the opportunity to select the Progressive lease-to-own payment&nbsp;option.</p>"
      }
    }
  ]
}
</script>
</div></body></html>
'''


@pytest.fixture
def stub_loader():
    """Bypass __init__ — these tests target pure helper methods."""
    import logging
    loader = WebScrapingLoader.__new__(WebScrapingLoader)
    loader.logger = logging.getLogger("test_faqpage")
    return loader


class TestFAQPageJSONLD:
    """JSON-LD FAQPage extraction → Q&A pair list."""

    def test_extracts_three_pairs_from_att_fixture(self, stub_loader):
        soup = BeautifulSoup(ATT_FAQ_FIXTURE_HTML, "html.parser")
        pairs = stub_loader._extract_faqpage_jsonld(soup)
        assert len(pairs) == 3
        questions = [p["question"] for p in pairs]
        assert "How do I access my AT&T Prepaid account?" in questions
        assert "How do I lease-to-own a phone with Progressive Leasing?" in questions

    def test_decodes_html_entities(self, stub_loader):
        soup = BeautifulSoup(ATT_FAQ_FIXTURE_HTML, "html.parser")
        pairs = stub_loader._extract_faqpage_jsonld(soup)
        autopay = next(
            p for p in pairs if "access my AT&T" in p["question"]
        )
        assert "AT&T Prepaid" in autopay["answer"]
        assert "&amp;" not in autopay["answer"]

    def test_strips_html_tags_from_answer(self, stub_loader):
        soup = BeautifulSoup(ATT_FAQ_FIXTURE_HTML, "html.parser")
        pairs = stub_loader._extract_faqpage_jsonld(soup)
        for p in pairs:
            assert "<p>" not in p["answer"]
            assert "<a " not in p["answer"]

    def test_collapses_whitespace_runs(self, stub_loader):
        soup = BeautifulSoup(ATT_FAQ_FIXTURE_HTML, "html.parser")
        pairs = stub_loader._extract_faqpage_jsonld(soup)
        for p in pairs:
            assert "  " not in p["answer"]
            assert p["answer"] == p["answer"].strip()

    def test_preserves_autopay_keyword(self, stub_loader):
        # The motivating regression: AutoPay must survive the answer
        # cleanup so the embedder gets the keyword users query against.
        soup = BeautifulSoup(ATT_FAQ_FIXTURE_HTML, "html.parser")
        pairs = stub_loader._extract_faqpage_jsonld(soup)
        autopay = next(
            p for p in pairs if "access my AT&T" in p["question"]
        )
        assert "AutoPay" in autopay["answer"]

    def test_returns_empty_list_when_no_jsonld(self, stub_loader):
        soup = BeautifulSoup(
            "<html><body><p>No FAQ here.</p></body></html>",
            "html.parser",
        )
        assert stub_loader._extract_faqpage_jsonld(soup) == []

    def test_tolerates_malformed_jsonld(self, stub_loader):
        bad_html = (
            '<script type="application/ld+json">{ broken json </script>'
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"FAQPage","mainEntity":'
            '[{"@type":"Question","name":"Q1?","acceptedAnswer":{"@type":"Answer","text":"A1"}}]}'
            "</script>"
        )
        soup = BeautifulSoup(bad_html, "html.parser")
        assert stub_loader._extract_faqpage_jsonld(soup) == [
            {"question": "Q1?", "answer": "A1"}
        ]

    def test_handles_at_graph_wrapper(self, stub_loader):
        graph_html = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@graph":['
            '{"@type":"WebPage","name":"page"},'
            '{"@type":"FAQPage","mainEntity":[{"@type":"Question",'
            '"name":"Wrapped?","acceptedAnswer":{"@type":"Answer","text":"Yes"}}]}]}'
            "</script>"
        )
        soup = BeautifulSoup(graph_html, "html.parser")
        assert stub_loader._extract_faqpage_jsonld(soup) == [
            {"question": "Wrapped?", "answer": "Yes"}
        ]

    def test_dedupes_questions_across_blocks(self, stub_loader):
        # Same Q in two blocks → first wins.
        dup_html = (
            '<script type="application/ld+json">'
            '{"@type":"FAQPage","mainEntity":[{"@type":"Question",'
            '"name":"Same?","acceptedAnswer":{"@type":"Answer","text":"first"}}]}'
            "</script>"
            '<script type="application/ld+json">'
            '{"@type":"FAQPage","mainEntity":[{"@type":"Question",'
            '"name":"Same?","acceptedAnswer":{"@type":"Answer","text":"second"}}]}'
            "</script>"
        )
        soup = BeautifulSoup(dup_html, "html.parser")
        pairs = stub_loader._extract_faqpage_jsonld(soup)
        assert len(pairs) == 1
        assert pairs[0]["answer"] == "first"

    def test_skips_question_with_empty_answer(self, stub_loader):
        empty_ans_html = (
            '<script type="application/ld+json">'
            '{"@type":"FAQPage","mainEntity":[{"@type":"Question",'
            '"name":"Empty?","acceptedAnswer":{"@type":"Answer","text":""}}]}'
            "</script>"
        )
        soup = BeautifulSoup(empty_ans_html, "html.parser")
        assert stub_loader._extract_faqpage_jsonld(soup) == []


class TestFAQPageDocumentEmission:
    """Document shape for FAQ pairs — page_content format and metadata."""

    def test_page_content_uses_q_and_a_prefixes(self, stub_loader):
        pairs = [{"question": "Can I do X?", "answer": "Yes."}]
        docs = stub_loader._docs_from_faqpage(pairs, {"source": "u"})
        assert docs[0].page_content == "Q: Can I do X?\n\nA: Yes."

    def test_metadata_has_qa_in_row_data(self, stub_loader):
        pairs = [{"question": "Q?", "answer": "A!"}]
        docs = stub_loader._docs_from_faqpage(pairs, {"source": "u"})
        meta = docs[0].metadata
        assert meta["content_kind"] == "faq"
        assert meta["selector_name"] == "faq"
        assert meta["source_type"] == "faq-jsonld"
        assert meta["row_data"] == {"question": "Q?", "answer": "A!"}
        assert meta["row_index"] == 0
        assert meta["row_count"] == 1

    def test_metadata_inherits_base_fields(self, stub_loader):
        pairs = [{"question": "Q?", "answer": "A!"}]
        docs = stub_loader._docs_from_faqpage(pairs, {
            "source": "https://www.att.com/prepaid/",
            "category": "prepaid-faq",
            "title": "AT&T Prepaid Plans",
        })
        meta = docs[0].metadata
        assert meta["source"] == "https://www.att.com/prepaid/"
        assert meta["category"] == "prepaid-faq"
        assert meta["title"] == "AT&T Prepaid Plans"

    def test_one_document_per_pair(self, stub_loader):
        pairs = [
            {"question": "Q1?", "answer": "A1"},
            {"question": "Q2?", "answer": "A2"},
            {"question": "Q3?", "answer": "A3"},
        ]
        docs = stub_loader._docs_from_faqpage(pairs, {"source": "u"})
        assert len(docs) == 3
        for i, d in enumerate(docs):
            assert d.metadata["row_index"] == i
            assert d.metadata["row_count"] == 3


# ── Tests: JSON-LD multi-type integration (TASK-975) ─────────────────────────

# HTML fixture templates for each JSON-LD type
PRODUCT_JSONLD_HTML = '''<html><head><title>Widget Shop</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Widget Pro",
 "description":"A great widget.","offers":{"@type":"Offer","price":"29.99","priceCurrency":"USD"}}
</script>
<p>Product page content here.</p>
</body></html>'''

EVENT_JSONLD_HTML = '''<html><head><title>Tech Conference</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Event","name":"Tech Conf 2026",
 "startDate":"2026-09-15","location":{"@type":"Place","name":"Convention Center"}}
</script>
<p>Event details.</p>
</body></html>'''

PERSON_JSONLD_HTML = '''<html><head><title>Jane Doe</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Person","name":"Jane Doe","jobTitle":"Senior Engineer"}
</script>
<p>Bio page.</p>
</body></html>'''

PLACE_JSONLD_HTML = '''<html><head><title>Joe's Pizza</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"LocalBusiness","name":"Joe's Pizza",
 "address":{"@type":"PostalAddress","streetAddress":"123 Main St","addressLocality":"Springfield"}}
</script>
<p>Restaurant info.</p>
</body></html>'''

RECIPE_JSONLD_HTML = '''<html><head><title>Chocolate Cake</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Recipe","name":"Chocolate Cake",
 "recipeIngredient":["flour","sugar","cocoa"],
 "recipeInstructions":[{"@type":"HowToStep","text":"Mix dry ingredients."}]}
</script>
<p>Delicious recipe.</p>
</body></html>'''

ARTICLE_JSONLD_HTML = '''<html><head><title>Breaking News</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Article","headline":"Breaking News",
 "author":{"@type":"Person","name":"Reporter"},"datePublished":"2026-01-15"}
</script>
<p>Article body text.</p>
</body></html>'''

ORGANIZATION_JSONLD_HTML = '''<html><head><title>Acme Corp</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Organization","name":"Acme Corp",
 "url":"https://acme.com","telephone":"+1-800-555-0100"}
</script>
<p>Company information.</p>
</body></html>'''

HOWTO_JSONLD_HTML = '''<html><head><title>Change a Tire</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"HowTo","name":"Change a Tire",
 "step":[{"@type":"HowToStep","text":"Loosen the nuts."},
         {"@type":"HowToStep","text":"Jack up the car."}]}
</script>
<p>Step by step guide.</p>
</body></html>'''

BREADCRUMB_JSONLD_HTML = '''<html><head><title>Products > Widget</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"BreadcrumbList",
 "itemListElement":[
   {"@type":"ListItem","position":1,"name":"Home"},
   {"@type":"ListItem","position":2,"name":"Products"},
   {"@type":"ListItem","position":3,"name":"Widget Pro"}
 ]}
</script>
<p>Widget product page.</p>
</body></html>'''

MIXED_GRAPH_HTML = '''<html><head><title>Mixed Page</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"FAQPage","mainEntity":[
    {"@type":"Question","name":"What is this?","acceptedAnswer":{"@type":"Answer","text":"A mixed page."}}
  ]},
  {"@type":"Product","name":"Mixed Widget","description":"A widget on a mixed page."}
]}
</script>
<p>Page with both FAQ and Product JSON-LD.</p>
</body></html>'''

MIXED_CONTENT_HTML = '''<html><head><title>Full Page with JSON-LD</title></head><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Full Page Widget",
 "offers":{"@type":"Offer","price":"49.99","priceCurrency":"USD"}}
</script>
<article>
<h1>Full Page Title</h1>
<p>This page has regular content alongside JSON-LD structured data.</p>
<p>The loader should emit both types of documents.</p>
<table>
  <thead><tr><th>Feature</th><th>Value</th></tr></thead>
  <tbody><tr><td>Color</td><td>Blue</td></tr></tbody>
</table>
</article>
</body></html>'''


@pytest.fixture
def stub_loader_jsonld():
    """Stub loader for testing new JSON-LD pipeline methods directly."""
    import logging
    loader = WebScrapingLoader.__new__(WebScrapingLoader)
    loader.logger = logging.getLogger("test_jsonld")
    loader._jsonld_types = None  # None = all types
    return loader


class TestJsonLdMultiTypeIntegration:
    """Full pipeline tests for each JSON-LD type via _extract_jsonld."""

    def test_product_jsonld_extract(self, stub_loader_jsonld) -> None:
        """Product JSON-LD node is dispatched to product_extractor."""
        soup = BeautifulSoup(PRODUCT_JSONLD_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        product_items = [i for i in items if i.content_kind == "jsonld-product"]
        assert len(product_items) == 1
        assert "Widget Pro" in product_items[0].page_content
        assert product_items[0].source_type == "product-jsonld"

    def test_event_jsonld_extract(self, stub_loader_jsonld) -> None:
        """Event JSON-LD node is dispatched to event_extractor."""
        soup = BeautifulSoup(EVENT_JSONLD_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        event_items = [i for i in items if i.content_kind == "jsonld-event"]
        assert len(event_items) == 1
        assert "Tech Conf 2026" in event_items[0].page_content

    def test_person_jsonld_extract(self, stub_loader_jsonld) -> None:
        """Person JSON-LD node is dispatched to person_extractor."""
        soup = BeautifulSoup(PERSON_JSONLD_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        person_items = [i for i in items if i.content_kind == "jsonld-person"]
        assert len(person_items) == 1
        assert "Jane Doe" in person_items[0].page_content

    def test_place_jsonld_extract(self, stub_loader_jsonld) -> None:
        """LocalBusiness JSON-LD node is dispatched to place_extractor."""
        soup = BeautifulSoup(PLACE_JSONLD_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        place_items = [i for i in items if i.content_kind == "jsonld-place"]
        assert len(place_items) == 1
        assert "Joe's Pizza" in place_items[0].page_content

    def test_recipe_jsonld_extract(self, stub_loader_jsonld) -> None:
        """Recipe JSON-LD node is dispatched to recipe_extractor."""
        soup = BeautifulSoup(RECIPE_JSONLD_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        recipe_items = [i for i in items if i.content_kind == "jsonld-recipe"]
        assert len(recipe_items) == 1
        assert "Chocolate Cake" in recipe_items[0].page_content

    def test_article_jsonld_extract(self, stub_loader_jsonld) -> None:
        """Article JSON-LD node is dispatched to article_extractor."""
        soup = BeautifulSoup(ARTICLE_JSONLD_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        article_items = [i for i in items if i.content_kind == "jsonld-article"]
        assert len(article_items) == 1
        assert "Breaking News" in article_items[0].page_content

    def test_organization_jsonld_extract(self, stub_loader_jsonld) -> None:
        """Organization JSON-LD node is dispatched to organization_extractor."""
        soup = BeautifulSoup(ORGANIZATION_JSONLD_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        org_items = [i for i in items if i.content_kind == "jsonld-organization"]
        assert len(org_items) == 1
        assert "Acme Corp" in org_items[0].page_content

    def test_howto_jsonld_extract(self, stub_loader_jsonld) -> None:
        """HowTo JSON-LD node is dispatched to howto_extractor."""
        soup = BeautifulSoup(HOWTO_JSONLD_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        howto_items = [i for i in items if i.content_kind == "jsonld-howto"]
        assert len(howto_items) == 1
        assert "Change a Tire" in howto_items[0].page_content

    def test_breadcrumb_jsonld_extract(self, stub_loader_jsonld) -> None:
        """BreadcrumbList JSON-LD node is dispatched to breadcrumb_extractor."""
        soup = BeautifulSoup(BREADCRUMB_JSONLD_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        bc_items = [i for i in items if i.content_kind == "jsonld-breadcrumb"]
        assert len(bc_items) == 1
        assert "Home" in bc_items[0].page_content
        assert "Widget Pro" in bc_items[0].page_content

    def test_malformed_jsonld_skipped(self, stub_loader_jsonld) -> None:
        """Malformed JSON-LD blocks are logged and skipped gracefully."""
        html = (
            '<script type="application/ld+json">{ invalid json </script>'
            '<script type="application/ld+json">'
            '{"@type":"Product","name":"Valid Widget"}'
            "</script>"
        )
        soup = BeautifulSoup(html, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        # The malformed block is skipped; the valid Product block is extracted
        assert any(i.content_kind == "jsonld-product" for i in items)

    def test_empty_page_no_jsonld(self, stub_loader_jsonld) -> None:
        """Page with no JSON-LD returns empty list."""
        soup = BeautifulSoup("<html><body><p>No structured data.</p></body></html>", "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        assert items == []

    def test_deduplication(self, stub_loader_jsonld) -> None:
        """Duplicate JSON-LD blocks produce only one item."""
        html = (
            '<script type="application/ld+json">'
            '{"@type":"Product","name":"Widget"}'
            "</script>"
            '<script type="application/ld+json">'
            '{"@type":"Product","name":"Widget"}'
            "</script>"
        )
        soup = BeautifulSoup(html, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        product_items = [i for i in items if i.content_kind == "jsonld-product"]
        assert len(product_items) == 1


class TestJsonLdDocsFromItems:
    """Tests for _docs_from_jsonld_items."""

    def test_converts_single_item(self, stub_loader_jsonld) -> None:
        """Single JsonLdItem converts to one Document with correct metadata."""
        from parrot_loaders.jsonld_extractors import JsonLdItem

        item = JsonLdItem(
            content_kind="jsonld-product",
            source_type="product-jsonld",
            page_content="# Widget\nA great widget.",
            row_data={"name": "Widget"},
            selector_name="product",
        )
        docs = stub_loader_jsonld._docs_from_jsonld_items([item], {"url": "https://example.com"})
        assert len(docs) == 1
        assert docs[0].page_content == "# Widget\nA great widget."
        assert docs[0].metadata["content_kind"] == "jsonld-product"
        assert docs[0].metadata["source_type"] == "product-jsonld"
        assert docs[0].metadata["selector_name"] == "product"
        assert docs[0].metadata["row_index"] == 0
        assert docs[0].metadata["row_count"] == 1
        assert docs[0].metadata["row_data"] == {"name": "Widget"}
        assert docs[0].metadata["url"] == "https://example.com"

    def test_row_index_and_count_per_kind(self, stub_loader_jsonld) -> None:
        """row_index and row_count are computed per content_kind group."""
        from parrot_loaders.jsonld_extractors import JsonLdItem

        items = [
            JsonLdItem("faq", "faq-jsonld", "Q: A\n\nA: B", {"question": "A", "answer": "B"}, "faq"),
            JsonLdItem("faq", "faq-jsonld", "Q: C\n\nA: D", {"question": "C", "answer": "D"}, "faq"),
            JsonLdItem("jsonld-product", "product-jsonld", "# Widget", {"name": "Widget"}, "product"),
        ]
        docs = stub_loader_jsonld._docs_from_jsonld_items(items, {})
        faq_docs = [d for d in docs if d.metadata["content_kind"] == "faq"]
        product_docs = [d for d in docs if d.metadata["content_kind"] == "jsonld-product"]
        assert len(faq_docs) == 2
        assert faq_docs[0].metadata["row_index"] == 0
        assert faq_docs[0].metadata["row_count"] == 2
        assert faq_docs[1].metadata["row_index"] == 1
        assert faq_docs[1].metadata["row_count"] == 2
        assert product_docs[0].metadata["row_index"] == 0
        assert product_docs[0].metadata["row_count"] == 1

    def test_empty_items_returns_empty(self, stub_loader_jsonld) -> None:
        """Empty item list returns empty document list."""
        docs = stub_loader_jsonld._docs_from_jsonld_items([], {})
        assert docs == []


class TestJsonLdMixedContent:
    """Test JSON-LD extraction alongside other content types."""

    def test_mixed_graph_multiple_types(self, stub_loader_jsonld) -> None:
        """Page with @graph containing FAQ + Product yields both item types."""
        soup = BeautifulSoup(MIXED_GRAPH_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        kinds = {i.content_kind for i in items}
        assert "faq" in kinds
        assert "jsonld-product" in kinds

    def test_at_graph_walked_recursively(self, stub_loader_jsonld) -> None:
        """Nested @graph structures are fully walked."""
        html = '''<script type="application/ld+json">
        {"@context":"https://schema.org","@graph":[
          {"@type":"WebSite","name":"Example"},
          {"@type":"Product","name":"Graph Widget"},
          {"@type":"BreadcrumbList","itemListElement":[
            {"@type":"ListItem","position":1,"name":"Home"}
          ]}
        ]}
        </script>'''
        soup = BeautifulSoup(html, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        kinds = {i.content_kind for i in items}
        assert "jsonld-product" in kinds
        assert "jsonld-breadcrumb" in kinds

    @pytest.mark.asyncio
    async def test_jsonld_with_regular_content(self) -> None:
        """JSON-LD docs coexist with regular page content docs."""
        result = _make_result(html=MIXED_CONTENT_HTML)
        loader = WebScrapingLoader(source="https://example.com/product", parse_tables=False)
        loader._toolkit = _mock_toolkit(scrape_result=result)

        docs = await loader._load("https://example.com/product")

        kinds = {d.metadata.get("content_kind") for d in docs}
        # JSON-LD product document should always be present
        assert "jsonld-product" in kinds
        # At least one full-page or trafilatura content doc should also be present
        # (content_kind may be: markdown_full, trafilatura_main, or text_full
        # depending on the content extraction strategy)
        full_page_kinds = {"markdown_full", "trafilatura_main", "trafilatura_full", "text_full"}
        assert kinds & full_page_kinds, (
            f"Expected at least one full-page doc kind in {kinds}. "
            f"JSON-LD product was extracted but no page-level doc was emitted."
        )

    @pytest.mark.asyncio
    async def test_extract_only_includes_jsonld(self) -> None:
        """extract_only=True still emits JSON-LD documents."""
        result = _make_result(html=PRODUCT_JSONLD_HTML)
        loader = WebScrapingLoader(
            source="https://example.com/product",
            extract_only=True,
        )
        loader._toolkit = _mock_toolkit(scrape_result=result)

        docs = await loader._load("https://example.com/product")

        kinds = {d.metadata.get("content_kind") for d in docs}
        assert "jsonld-product" in kinds
        # Should NOT emit full-page markdown in extract_only mode
        assert "markdown_full" not in kinds


class TestJsonLdTypesFilter:
    """Test the jsonld_types constructor parameter filtering."""

    def test_filter_to_product_only(self, stub_loader_jsonld) -> None:
        """jsonld_types=['Product'] extracts only Product from mixed graph."""
        stub_loader_jsonld._jsonld_types = ["Product"]
        soup = BeautifulSoup(MIXED_GRAPH_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        kinds = {i.content_kind for i in items}
        assert "jsonld-product" in kinds
        assert "faq" not in kinds

    def test_filter_empty_disables_all(self, stub_loader_jsonld) -> None:
        """jsonld_types=[] disables all JSON-LD extraction."""
        stub_loader_jsonld._jsonld_types = []
        soup = BeautifulSoup(PRODUCT_JSONLD_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        assert items == []

    def test_filter_none_extracts_all(self, stub_loader_jsonld) -> None:
        """jsonld_types=None (default) extracts all supported types."""
        stub_loader_jsonld._jsonld_types = None
        soup = BeautifulSoup(MIXED_GRAPH_HTML, "html.parser")
        items = stub_loader_jsonld._extract_jsonld(soup)
        kinds = {i.content_kind for i in items}
        assert len(kinds) > 1  # Both FAQ and Product extracted

    @pytest.mark.asyncio
    async def test_constructor_jsonld_types_product_only(self) -> None:
        """WebScrapingLoader(jsonld_types=['Product']) filters to Product."""
        html = MIXED_GRAPH_HTML  # Contains FAQ + Product
        result = _make_result(html=html)
        loader = WebScrapingLoader(
            source="https://example.com",
            jsonld_types=["Product"],
        )
        loader._toolkit = _mock_toolkit(scrape_result=result)

        docs = await loader._load("https://example.com")

        kinds = {d.metadata.get("content_kind") for d in docs}
        assert "jsonld-product" in kinds
        assert "faq" not in kinds

    @pytest.mark.asyncio
    async def test_constructor_jsonld_types_empty_disables(self) -> None:
        """WebScrapingLoader(jsonld_types=[]) disables all JSON-LD extraction."""
        result = _make_result(html=PRODUCT_JSONLD_HTML)
        loader = WebScrapingLoader(
            source="https://example.com",
            jsonld_types=[],
        )
        loader._toolkit = _mock_toolkit(scrape_result=result)

        docs = await loader._load("https://example.com")

        kinds = {d.metadata.get("content_kind") for d in docs}
        assert "jsonld-product" not in kinds


class TestFAQPageBackwardCompat:
    """Regression: FAQPage via new pipeline must produce identical output."""

    @pytest.mark.asyncio
    async def test_att_fixture_produces_faq_docs(self) -> None:
        """ATT_FAQ_FIXTURE_HTML through new pipeline yields 3 FAQ docs."""
        result = _make_result(
            url="https://www.att.com/prepaid/",
            html=ATT_FAQ_FIXTURE_HTML,
        )
        loader = WebScrapingLoader(source="https://www.att.com/prepaid/")
        loader._toolkit = _mock_toolkit(scrape_result=result)

        docs = await loader._load("https://www.att.com/prepaid/")
        faq_docs = [d for d in docs if d.metadata.get("content_kind") == "faq"]
        assert len(faq_docs) == 3

    @pytest.mark.asyncio
    async def test_att_fixture_metadata_schema(self) -> None:
        """Every FAQ doc has the exact metadata fields required."""
        result = _make_result(
            url="https://www.att.com/prepaid/",
            html=ATT_FAQ_FIXTURE_HTML,
        )
        loader = WebScrapingLoader(source="https://www.att.com/prepaid/")
        loader._toolkit = _mock_toolkit(scrape_result=result)

        docs = await loader._load("https://www.att.com/prepaid/")
        faq_docs = [d for d in docs if d.metadata.get("content_kind") == "faq"]
        for doc in faq_docs:
            assert doc.metadata["content_kind"] == "faq"
            assert doc.metadata["source_type"] == "faq-jsonld"
            assert doc.metadata["selector_name"] == "faq"
            assert "question" in doc.metadata["row_data"]
            assert "answer" in doc.metadata["row_data"]
            assert doc.page_content.startswith("Q: ")
            assert "\n\nA: " in doc.page_content

    @pytest.mark.asyncio
    async def test_no_jsonld_faq_content_kind(self) -> None:
        """FAQPage must use content_kind='faq', never 'jsonld-faq'."""
        result = _make_result(html=ATT_FAQ_FIXTURE_HTML)
        loader = WebScrapingLoader(source="https://example.com")
        loader._toolkit = _mock_toolkit(scrape_result=result)

        docs = await loader._load("https://example.com")
        kinds = {d.metadata.get("content_kind") for d in docs}
        assert "jsonld-faq" not in kinds
        assert "faq" in kinds

    @pytest.mark.asyncio
    async def test_att_fixture_row_count_and_index(self) -> None:
        """FAQ docs have consecutive row_index and correct row_count."""
        result = _make_result(
            url="https://www.att.com/prepaid/",
            html=ATT_FAQ_FIXTURE_HTML,
        )
        loader = WebScrapingLoader(source="https://www.att.com/prepaid/")
        loader._toolkit = _mock_toolkit(scrape_result=result)

        docs = await loader._load("https://www.att.com/prepaid/")
        faq_docs = sorted(
            [d for d in docs if d.metadata.get("content_kind") == "faq"],
            key=lambda d: d.metadata["row_index"],
        )
        assert len(faq_docs) == 3
        for i, doc in enumerate(faq_docs):
            assert doc.metadata["row_index"] == i
            assert doc.metadata["row_count"] == 3

    @pytest.mark.asyncio
    async def test_faq_page_content_format(self) -> None:
        """FAQ page_content is exactly 'Q: <q>\\n\\nA: <a>' format."""
        result = _make_result(html=ATT_FAQ_FIXTURE_HTML)
        loader = WebScrapingLoader(source="https://example.com")
        loader._toolkit = _mock_toolkit(scrape_result=result)

        docs = await loader._load("https://example.com")
        faq_docs = [d for d in docs if d.metadata.get("content_kind") == "faq"]
        for doc in faq_docs:
            # Must start with "Q: " and contain "\n\nA: "
            lines = doc.page_content.split("\n\n")
            assert len(lines) == 2
            assert lines[0].startswith("Q: ")
            assert lines[1].startswith("A: ")
