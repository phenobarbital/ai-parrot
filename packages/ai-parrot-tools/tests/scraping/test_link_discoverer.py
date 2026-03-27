"""Tests for parrot.tools.scraping.link_discoverer."""
from __future__ import annotations

import pytest

from parrot.tools.scraping.link_discoverer import LinkDiscoverer


SAMPLE_HTML = """
<html><body>
  <a href="/products">Products</a>
  <a href="/about">About</a>
  <a href="https://external.com/page">External</a>
  <a href="/products?utm=123#section">Products with tracking</a>
  <a href="mailto:test@example.com">Email</a>
</body></html>
"""

BASE_URL = "https://www.example.com/"


class TestLinkDiscoverer:
    """Unit tests for LinkDiscoverer."""

    def test_basic_discovery(self) -> None:
        """Discovers internal /products and /about links."""
        ld = LinkDiscoverer(base_domain="example.com")
        urls = ld.discover(SAMPLE_HTML, BASE_URL, current_depth=0, max_depth=2)
        assert "https://example.com/products" in urls
        assert "https://example.com/about" in urls

    def test_domain_scoping(self) -> None:
        """Blocks external.com links when allow_external=False."""
        ld = LinkDiscoverer(base_domain="example.com", allow_external=False)
        urls = ld.discover(SAMPLE_HTML, BASE_URL, current_depth=0, max_depth=2)
        external = [u for u in urls if "external.com" in u]
        assert external == []

    def test_allow_external(self) -> None:
        """Includes external.com link when allow_external=True."""
        ld = LinkDiscoverer(base_domain="example.com", allow_external=True)
        urls = ld.discover(SAMPLE_HTML, BASE_URL, current_depth=0, max_depth=2)
        assert "https://external.com/page" in urls

    def test_pattern_filter(self) -> None:
        """Only returns URLs matching /products pattern."""
        ld = LinkDiscoverer(
            base_domain="example.com",
            follow_pattern=r"/products",
        )
        urls = ld.discover(SAMPLE_HTML, BASE_URL, current_depth=0, max_depth=2)
        assert all("/products" in u for u in urls)
        assert "https://example.com/about" not in urls

    def test_depth_guard(self) -> None:
        """Returns empty list when current_depth >= max_depth."""
        ld = LinkDiscoverer(base_domain="example.com")
        assert ld.discover(SAMPLE_HTML, BASE_URL, current_depth=2, max_depth=2) == []
        assert ld.discover(SAMPLE_HTML, BASE_URL, current_depth=3, max_depth=2) == []

    def test_deduplication(self) -> None:
        """normalize_url strips query/fragment, so /products appears only once."""
        ld = LinkDiscoverer(base_domain="example.com")
        urls = ld.discover(SAMPLE_HTML, BASE_URL, current_depth=0, max_depth=2)
        products_urls = [u for u in urls if "products" in u]
        assert len(products_urls) == 1

    def test_rejects_mailto(self) -> None:
        """No mailto links appear in output."""
        ld = LinkDiscoverer(base_domain="example.com")
        urls = ld.discover(SAMPLE_HTML, BASE_URL, current_depth=0, max_depth=2)
        assert not any("mailto" in u for u in urls)

    def test_custom_selector(self) -> None:
        """Using a custom CSS selector only picks matching elements."""
        html = """
        <html><body>
          <a class="nav-link" href="/nav1">Nav 1</a>
          <a href="/other">Other</a>
          <a class="nav-link" href="/nav2">Nav 2</a>
        </body></html>
        """
        ld = LinkDiscoverer(
            follow_selector="a.nav-link[href]",
            base_domain="example.com",
        )
        urls = ld.discover(html, BASE_URL, current_depth=0, max_depth=2)
        assert "https://example.com/nav1" in urls
        assert "https://example.com/nav2" in urls
        assert "https://example.com/other" not in urls

    def test_empty_html(self) -> None:
        """Handles empty string without crash."""
        ld = LinkDiscoverer(base_domain="example.com")
        urls = ld.discover("", BASE_URL, current_depth=0, max_depth=2)
        assert urls == []

    def test_malformed_html(self) -> None:
        """Handles broken HTML without crash."""
        broken = "<html><body><a href='/ok'><div><a href='/also-ok'"
        ld = LinkDiscoverer(base_domain="example.com")
        urls = ld.discover(broken, BASE_URL, current_depth=0, max_depth=2)
        # Should not raise; may or may not find links depending on parser
        assert isinstance(urls, list)
