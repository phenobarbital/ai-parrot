"""Tests for URL normalization utilities."""
import pytest

from parrot.tools.scraping.url_utils import normalize_url


class TestNormalizeUrl:
    """Tests for normalize_url()."""

    # --- Relative URL resolution ---

    def test_relative_url(self):
        result = normalize_url("/products", "https://example.com/page")
        assert result == "https://example.com/products"

    def test_relative_url_with_base_path(self):
        result = normalize_url("child", "https://example.com/parent/")
        assert result == "https://example.com/parent/child"

    def test_relative_url_dot_dot(self):
        result = normalize_url("../other", "https://example.com/a/b/")
        assert result == "https://example.com/a/other"

    # --- Query and fragment stripping ---

    def test_strips_query_and_fragment(self):
        result = normalize_url(
            "https://example.com/page?utm_source=google#top", ""
        )
        assert result == "https://example.com/page"

    def test_strips_query_only(self):
        result = normalize_url("https://example.com/page?q=1&r=2", "")
        assert result == "https://example.com/page"

    def test_strips_fragment_only(self):
        result = normalize_url("https://example.com/page#section", "")
        assert result == "https://example.com/page"

    # --- www. removal ---

    def test_removes_www(self):
        result = normalize_url("https://www.example.com/page", "")
        assert result == "https://example.com/page"

    def test_preserves_non_www_subdomain(self):
        result = normalize_url("https://blog.example.com/page", "")
        assert result == "https://blog.example.com/page"

    # --- Trailing slash ---

    def test_removes_trailing_slash(self):
        result = normalize_url("https://example.com/products/", "")
        assert result == "https://example.com/products"

    def test_root_path_preserved(self):
        result = normalize_url("https://example.com/", "")
        assert result == "https://example.com/"

    def test_root_without_slash(self):
        result = normalize_url("https://example.com", "")
        assert result == "https://example.com/"

    # --- Scheme normalization ---

    def test_lowercase_scheme(self):
        result = normalize_url("HTTPS://Example.Com/Page", "")
        assert result == "https://example.com/Page"

    def test_http_scheme_allowed(self):
        result = normalize_url("http://example.com/page", "")
        assert result == "http://example.com/page"

    # --- Rejected schemes ---

    def test_rejects_mailto(self):
        assert normalize_url("mailto:user@example.com", "") is None

    def test_rejects_javascript(self):
        assert normalize_url("javascript:void(0)", "") is None

    def test_rejects_data_uri(self):
        assert normalize_url("data:text/html,<h1>Hi</h1>", "") is None

    def test_rejects_ftp(self):
        assert normalize_url("ftp://example.com/file", "") is None

    def test_rejects_tel(self):
        assert normalize_url("tel:+1234567890", "") is None

    # --- Empty / malformed ---

    def test_empty_url_returns_none(self):
        assert normalize_url("", "https://example.com") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_url("   ", "") is None

    def test_none_like_empty(self):
        assert normalize_url("", "") is None

    # --- Idempotence ---

    def test_already_normalized(self):
        url = "https://example.com/products"
        assert normalize_url(url, "") == url

    def test_double_normalization(self):
        first = normalize_url("https://www.example.com/path/?q=1#frag", "")
        second = normalize_url(first, "")
        assert first == second
