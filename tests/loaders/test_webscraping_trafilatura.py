"""Tests for WebScrapingLoader trafilatura extraction pipeline.

Covers: trafilatura extraction, fallback logic, metadata enrichment,
backward compatibility, and import guard behavior.
"""
import pytest
from unittest.mock import MagicMock, patch
from bs4 import BeautifulSoup

from parrot_loaders.webscraping import WebScrapingLoader, HAS_TRAFILATURA
from parrot.stores.models import Document


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def sample_product_html():
    """HTML mimicking a product page with nav, footer, scripts, main content."""
    return """
    <html lang="en">
    <head>
        <title>Prepaid Plans | Example Wireless</title>
        <meta name="description" content="Check out our prepaid plans">
        <meta name="author" content="Example Wireless">
        <script>var tracking = true;</script>
        <style>.nav { color: blue; }</style>
    </head>
    <body>
        <nav><a href="/">Home</a><a href="/plans">Plans</a></nav>
        <main>
            <h1>Prepaid Plans</h1>
            <p>Get the best prepaid wireless plans starting at $25/mo.</p>
            <table>
                <thead><tr><th>Plan</th><th>Price</th><th>Data</th></tr></thead>
                <tbody>
                    <tr><td>Basic</td><td>$25/mo</td><td>5GB</td></tr>
                    <tr><td>Plus</td><td>$40/mo</td><td>15GB</td></tr>
                </tbody>
            </table>
            <h2>Why Choose Prepaid?</h2>
            <p>No credit check. No annual contract. No surprises.</p>
        </main>
        <footer>Copyright 2026 Example Wireless</footer>
        <script>analytics.track('page_view');</script>
    </body>
    </html>
    """


@pytest.fixture
def mock_scraping_result(sample_product_html):
    """Mock ScrapingResult with bs_soup from sample HTML."""
    result = MagicMock()
    result.success = True
    result.url = "https://example.com/plans"
    result.bs_soup = BeautifulSoup(sample_product_html, "html.parser")
    result.extracted_data = {}
    result.content = sample_product_html
    return result


@pytest.fixture
def minimal_html():
    """Minimal HTML page with very little content."""
    return """
    <html>
    <head><title>Tiny Page</title></head>
    <body><p>Hello.</p></body>
    </html>
    """


@pytest.fixture
def mock_minimal_result(minimal_html):
    """Mock ScrapingResult with minimal HTML."""
    result = MagicMock()
    result.success = True
    result.url = "https://example.com/tiny"
    result.bs_soup = BeautifulSoup(minimal_html, "html.parser")
    result.extracted_data = {}
    result.content = minimal_html
    return result


# ── Trafilatura extraction tests ─────────────────────────────────────


class TestTrafilaturaExtraction:
    """Test trafilatura-based content extraction in WebScrapingLoader."""

    @pytest.mark.skipif(
        not HAS_TRAFILATURA, reason="trafilatura not installed"
    )
    def test_trafilatura_extraction_clean_content(self, mock_scraping_result):
        """Trafilatura extracts main content, strips nav/footer/scripts."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="auto",
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        assert len(docs) > 0
        main_doc = docs[0]
        assert "Prepaid Plans" in main_doc.page_content or \
               "prepaid" in main_doc.page_content.lower()
        assert "<script>" not in main_doc.page_content
        assert "<nav>" not in main_doc.page_content

    @pytest.mark.skipif(
        not HAS_TRAFILATURA, reason="trafilatura not installed"
    )
    def test_trafilatura_metadata_extraction(self, mock_scraping_result):
        """Metadata includes title and description from trafilatura/soup."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="auto",
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        assert len(docs) > 0
        meta = docs[0].metadata.get("document_meta", {})
        assert "title" in meta
        assert meta["title"]  # Non-empty title

    @pytest.mark.skipif(
        not HAS_TRAFILATURA, reason="trafilatura not installed"
    )
    def test_trafilatura_content_extraction_label(self, mock_scraping_result):
        """Document metadata indicates 'trafilatura' extraction method."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="auto",
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        assert len(docs) > 0
        # The first doc should indicate which extraction was used
        first_doc = docs[0]
        extraction = first_doc.metadata.get("content_extraction")
        assert extraction in ("trafilatura", "markdownify_fallback")

    def test_trafilatura_fallback_on_sparse_output(self, sample_product_html):
        """When trafilatura returns sparse output, fallback to markdownify."""
        result = MagicMock()
        result.success = True
        result.url = "https://example.com/plans"
        result.bs_soup = BeautifulSoup(sample_product_html, "html.parser")
        result.extracted_data = {}
        result.content = sample_product_html

        with patch("parrot_loaders.webscraping.trafilatura") as mock_traf, \
             patch("parrot_loaders.webscraping.HAS_TRAFILATURA", True):
            mock_traf.extract.return_value = "tiny"  # Very sparse
            mock_traf.bare_extraction.return_value = MagicMock(
                author=None, date=None, sitename=None,
                categories=None, tags=None, title=None,
                description=None, language=None,
            )
            loader = WebScrapingLoader(
                source="https://example.com/plans",
                content_extraction="auto",
                trafilatura_fallback_threshold=0.5,
            )
            docs = loader._result_to_documents(
                result, "https://example.com/plans"
            )
            assert len(docs) > 0
            assert docs[0].metadata.get("content_extraction") in (
                "markdownify_fallback", "markdown"
            )

    def test_trafilatura_fallback_on_empty_output(self, sample_product_html):
        """When trafilatura returns None, fallback to markdownify."""
        result = MagicMock()
        result.success = True
        result.url = "https://example.com/plans"
        result.bs_soup = BeautifulSoup(sample_product_html, "html.parser")
        result.extracted_data = {}
        result.content = sample_product_html

        with patch("parrot_loaders.webscraping.trafilatura") as mock_traf, \
             patch("parrot_loaders.webscraping.HAS_TRAFILATURA", True):
            mock_traf.extract.return_value = None
            mock_traf.bare_extraction.return_value = MagicMock(
                author=None, date=None, sitename=None,
                categories=None, tags=None, title=None,
                description=None, language=None,
            )
            loader = WebScrapingLoader(
                source="https://example.com/plans",
                content_extraction="auto",
            )
            docs = loader._result_to_documents(
                result, "https://example.com/plans"
            )
            assert len(docs) > 0
            assert docs[0].metadata.get("content_extraction") == "markdownify_fallback"


class TestContentExtractionModes:
    """Test different content_extraction modes."""

    def test_content_extraction_mode_markdown(self, mock_scraping_result):
        """content_extraction='markdown' skips trafilatura entirely."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="markdown",
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        assert len(docs) > 0
        # Should use markdownify path
        main_doc = docs[0]
        assert main_doc.metadata.get("content_extraction") == "markdown"
        assert main_doc.metadata.get("content_kind") == "markdown_full"

    def test_content_extraction_mode_text(self, mock_scraping_result):
        """content_extraction='text' produces plain text output."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="text",
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        assert len(docs) > 0
        main_doc = docs[0]
        assert main_doc.metadata.get("content_extraction") == "text"
        assert main_doc.metadata.get("content_kind") == "text_full"

    @pytest.mark.skipif(
        not HAS_TRAFILATURA, reason="trafilatura not installed"
    )
    def test_content_extraction_mode_trafilatura_force(
        self, mock_scraping_result
    ):
        """content_extraction='trafilatura' forces trafilatura, no fallback."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="trafilatura",
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        assert len(docs) > 0
        main_doc = docs[0]
        assert main_doc.metadata.get("content_extraction") == "trafilatura"
        assert main_doc.metadata.get("content_kind") == "trafilatura_main"

    def test_content_extraction_trafilatura_missing_raises(self):
        """content_extraction='trafilatura' raises ImportError if not installed."""
        result = MagicMock()
        result.success = True
        result.url = "https://example.com"
        result.bs_soup = BeautifulSoup("<html><body>Hello</body></html>", "html.parser")
        result.extracted_data = {}
        result.content = "<html><body>Hello</body></html>"

        with patch("parrot_loaders.webscraping.HAS_TRAFILATURA", False):
            loader = WebScrapingLoader(
                source="https://example.com",
                content_extraction="trafilatura",
            )
            with pytest.raises(ImportError, match="trafilatura is required"):
                loader._result_to_documents(result, "https://example.com")


class TestTablesExtraction:
    """Test that tables are extracted separately regardless of extraction mode."""

    def test_tables_extracted_separately(self, mock_scraping_result):
        """Tables always extracted as separate Documents."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="auto",
            parse_tables=True,
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        table_docs = [
            d for d in docs if d.metadata.get("content_kind") == "table"
        ]
        assert len(table_docs) > 0
        # Verify table content includes the data from the HTML
        table_content = table_docs[0].page_content
        assert "Basic" in table_content
        assert "$25/mo" in table_content

    def test_tables_extracted_in_markdown_mode(self, mock_scraping_result):
        """Tables extracted even in markdown mode."""
        loader = WebScrapingLoader(
            source="https://example.com/plans",
            content_extraction="markdown",
            parse_tables=True,
        )
        docs = loader._result_to_documents(
            mock_scraping_result, "https://example.com/plans"
        )
        table_docs = [
            d for d in docs if d.metadata.get("content_kind") == "table"
        ]
        assert len(table_docs) > 0


class TestBackwardCompatibility:
    """Test that existing WebScrapingLoader API is not broken."""

    def test_default_instantiation(self):
        """Default instantiation without new params works."""
        loader = WebScrapingLoader(source="https://example.com")
        assert loader._content_extraction == "auto"
        assert loader._trafilatura_fallback_threshold == 0.1

    def test_existing_params_still_work(self):
        """All existing constructor params still accepted."""
        loader = WebScrapingLoader(
            source="https://example.com",
            crawl=True,
            depth=2,
            max_pages=50,
            headless=True,
            parse_videos=True,
            parse_tables=True,
            content_format="markdown",
        )
        assert loader._crawl is True
        assert loader._depth == 2

    def test_failed_result_returns_empty(self):
        """Failed ScrapingResult returns empty list."""
        result = MagicMock()
        result.success = False
        result.error_message = "Connection timeout"
        loader = WebScrapingLoader(source="https://example.com")
        docs = loader._result_to_documents(result, "https://example.com")
        assert docs == []


class TestTrafilaturaImportGuard:
    """Test behavior when trafilatura is not installed."""

    def test_missing_trafilatura_auto_fallback(self, mock_scraping_result):
        """auto mode falls back silently when trafilatura not installed."""
        with patch("parrot_loaders.webscraping.HAS_TRAFILATURA", False):
            loader = WebScrapingLoader(
                source="https://example.com/plans",
                content_extraction="auto",
            )
            docs = loader._result_to_documents(
                mock_scraping_result, "https://example.com/plans"
            )
            assert len(docs) > 0
            # Should use markdownify fallback
            assert docs[0].metadata.get("content_extraction") == "markdownify_fallback"
