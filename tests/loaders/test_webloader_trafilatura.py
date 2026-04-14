"""Tests for WebLoader trafilatura extraction pipeline.

Covers: trafilatura integration in clean_html(), metadata enrichment,
fallback logic, and backward compatibility.
"""
import pytest
from unittest.mock import patch, MagicMock

from parrot_loaders.web import WebLoader, HAS_TRAFILATURA


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def sample_html():
    """HTML with nav, footer, scripts, and main content."""
    return """
    <html lang="en">
    <head>
        <title>Product Page | Example Store</title>
        <meta name="description" content="Great products here">
        <script>var analytics = {};</script>
        <style>body { font-size: 16px; }</style>
    </head>
    <body>
        <nav><a href="/">Home</a><a href="/products">Products</a></nav>
        <main>
            <h1>Our Products</h1>
            <p>We offer the best products in the market with competitive pricing.</p>
            <p>Check out our latest collection of premium items.</p>
            <table>
                <thead><tr><th>Item</th><th>Price</th></tr></thead>
                <tbody>
                    <tr><td>Widget</td><td>$9.99</td></tr>
                </tbody>
            </table>
        </main>
        <footer>Copyright 2026</footer>
    </body>
    </html>
    """


@pytest.fixture
def default_tags():
    """Default HTML tags to extract."""
    return ["p", "h1", "h2", "h3", "section", "article"]


# ── Trafilatura extraction tests ─────────────────────────────────────


class TestWebLoaderTrafilatura:
    """Test trafilatura integration in WebLoader.clean_html()."""

    @pytest.mark.skipif(
        not HAS_TRAFILATURA, reason="trafilatura not installed"
    )
    def test_trafilatura_clean_html(self, sample_html, default_tags):
        """Trafilatura produces clean content from noisy HTML."""
        loader = WebLoader(content_extraction="auto")
        content, md_text, title = loader.clean_html(
            sample_html, default_tags
        )
        assert isinstance(content, list)
        assert isinstance(md_text, str)
        assert isinstance(title, str)
        assert title == "Product Page | Example Store"
        assert md_text  # Non-empty output
        # Trafilatura should have extracted main content
        assert loader._last_extraction_method in ("trafilatura", "markdownify_fallback")

    @pytest.mark.skipif(
        not HAS_TRAFILATURA, reason="trafilatura not installed"
    )
    def test_trafilatura_metadata_stored(self, sample_html, default_tags):
        """Trafilatura metadata is stored for _load() to use."""
        loader = WebLoader(content_extraction="auto")
        loader.clean_html(sample_html, default_tags)
        # Metadata should be a dict (may be empty if trafilatura
        # couldn't extract metadata from this simple HTML)
        assert isinstance(loader._last_trafilatura_meta, dict)

    def test_trafilatura_fallback_on_sparse(self, sample_html, default_tags):
        """Sparse trafilatura output triggers markdownify fallback."""
        with patch("parrot_loaders.web.trafilatura") as mock_traf, \
             patch("parrot_loaders.web.HAS_TRAFILATURA", True):
            mock_traf.extract.return_value = "x"  # Very sparse
            mock_traf.bare_extraction.return_value = MagicMock(
                author=None, date=None, sitename=None,
                categories=None, tags=None, title=None,
                description=None, language=None,
            )
            loader = WebLoader(
                content_extraction="auto",
                trafilatura_fallback_threshold=0.5,
            )
            content, md_text, title = loader.clean_html(
                sample_html, default_tags
            )
            assert md_text  # Should have content from markdownify
            assert loader._last_extraction_method == "markdownify_fallback"

    def test_markdown_mode_skips_trafilatura(
        self, sample_html, default_tags
    ):
        """content_extraction='markdown' uses markdownify directly."""
        loader = WebLoader(content_extraction="markdown")
        content, md_text, title = loader.clean_html(
            sample_html, default_tags
        )
        assert md_text
        assert loader._last_extraction_method == "markdown"

    def test_trafilatura_missing_raises_in_force_mode(
        self, sample_html, default_tags
    ):
        """content_extraction='trafilatura' raises ImportError when missing."""
        with patch("parrot_loaders.web.HAS_TRAFILATURA", False):
            loader = WebLoader(content_extraction="trafilatura")
            with pytest.raises(ImportError, match="trafilatura is required"):
                loader.clean_html(sample_html, default_tags)


class TestWebLoaderBackwardCompatibility:
    """Test that existing WebLoader API is not broken."""

    def test_default_instantiation(self):
        """Default instantiation without new params works."""
        loader = WebLoader()
        assert loader._content_extraction == "auto"
        assert loader._trafilatura_fallback_threshold == 0.1

    def test_clean_html_return_type(self, sample_html, default_tags):
        """clean_html() still returns (list, str, str) tuple."""
        loader = WebLoader()
        result = loader.clean_html(sample_html, default_tags)
        assert isinstance(result, tuple)
        assert len(result) == 3
        content, md_text, title = result
        assert isinstance(content, list)
        assert isinstance(md_text, str)
        assert isinstance(title, str)

    def test_tables_always_extracted(self, sample_html, default_tags):
        """Tables are extracted regardless of content_extraction mode."""
        loader = WebLoader(content_extraction="auto")
        content, md_text, title = loader.clean_html(
            sample_html, default_tags, parse_tables=True
        )
        # Content should include table markdown
        table_content = [c for c in content if "Widget" in c and "$9.99" in c]
        assert len(table_content) > 0

    def test_auto_mode_without_trafilatura(
        self, sample_html, default_tags
    ):
        """Auto mode silently falls back when trafilatura not installed."""
        with patch("parrot_loaders.web.HAS_TRAFILATURA", False):
            loader = WebLoader(content_extraction="auto")
            content, md_text, title = loader.clean_html(
                sample_html, default_tags
            )
            assert md_text  # Should still produce output via markdownify
            assert loader._last_extraction_method == "markdownify_fallback"
