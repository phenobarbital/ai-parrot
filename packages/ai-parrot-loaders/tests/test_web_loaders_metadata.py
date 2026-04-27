"""
Tests for canonical metadata shape in WebLoader and WebScrapingLoader (TASK-860).
All tests use create_metadata directly to verify the shape without
needing to actually run browser/scraping infrastructure.
"""
from __future__ import annotations
import pytest

CANONICAL_DOC_META_KEYS = {"source_type", "category", "type", "language", "title"}


class TestWebScrapingLoaderMetadata:
    """Verify WebScrapingLoader emits canonical document_meta."""

    def test_canonical_document_meta(self):
        from parrot_loaders.webscraping import WebScrapingLoader
        loader = WebScrapingLoader()
        meta = loader.create_metadata(
            "https://example.com/page",
            doctype="web_page",
            source_type="url",
            content_kind="fragment",
            author="John",
            sitename="Example"
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "content_kind" in meta
        assert "author" in meta
        assert "sitename" in meta
        assert "content_kind" not in meta["document_meta"]
        assert "author" not in meta["document_meta"]

    def test_document_meta_closed_shape(self):
        from parrot_loaders.webscraping import WebScrapingLoader
        loader = WebScrapingLoader()
        meta = loader.create_metadata(
            "https://example.com",
            doctype="web_page",
            source_type="url"
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS

    def test_trafilatura_fields_at_top_level(self):
        """Trafilatura fields must go to top level, not into document_meta."""
        from parrot_loaders.webscraping import WebScrapingLoader
        loader = WebScrapingLoader()
        meta = loader.create_metadata(
            "https://example.com/article",
            doctype="webpage",
            source_type="url",
            author="Jane Doe",
            sitename="Example Site",
            date="2026-04-27",
            categories=["tech"],
            tags=["python"],
            description="A test article",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        # Trafilatura fields at top level
        assert "author" in meta
        assert "sitename" in meta
        assert "date" in meta
        assert "description" in meta
        # Not inside document_meta
        assert "author" not in meta["document_meta"]
        assert "sitename" not in meta["document_meta"]
        assert "description" not in meta["document_meta"]

    def test_content_kind_at_top_level(self):
        """content_kind is always a top-level key, never inside document_meta."""
        from parrot_loaders.webscraping import WebScrapingLoader
        loader = WebScrapingLoader()
        for kind in ("fragment", "video_link", "navigation", "table", "trafilatura_main", "markdown_full"):
            meta = loader.create_metadata(
                "https://example.com",
                doctype="webpage",
                source_type="url",
                content_kind=kind,
            )
            assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
            assert meta["content_kind"] == kind
            assert "content_kind" not in meta["document_meta"]

    def test_language_propagates_to_document_meta(self):
        from parrot_loaders.webscraping import WebScrapingLoader
        loader = WebScrapingLoader()
        meta = loader.create_metadata(
            "https://example.com/es/pagina",
            doctype="webpage",
            source_type="url",
            language="es",
        )
        assert meta["document_meta"]["language"] == "es"


class TestWebLoaderMetadata:
    """Verify WebLoader emits canonical document_meta."""

    def test_canonical_metadata(self):
        from parrot_loaders.web import WebLoader
        loader = WebLoader()
        meta = loader.create_metadata(
            "https://example.com/api",
            doctype="web_content",
            source_type="url",
            request_url="https://example.com/api",
            fetched_at="2026-04-27T10:00:00"
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "request_url" in meta
        assert "fetched_at" in meta

    def test_trafilatura_fields_not_in_document_meta(self):
        """Trafilatura extras must not leak into document_meta."""
        from parrot_loaders.web import WebLoader
        loader = WebLoader()
        meta = loader.create_metadata(
            "https://example.com",
            doctype="webpage",
            source_type="url",
            author="Test Author",
            sitename="Test Site",
            date="2026-01-01",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "author" in meta
        assert "sitename" in meta
        assert "author" not in meta["document_meta"]
        assert "sitename" not in meta["document_meta"]

    def test_content_extraction_at_top_level(self):
        """content_extraction label is a top-level key."""
        from parrot_loaders.web import WebLoader
        loader = WebLoader()
        meta = loader.create_metadata(
            "https://example.com",
            doctype="webpage",
            source_type="url",
            content_extraction="trafilatura",
        )
        assert set(meta["document_meta"].keys()) == CANONICAL_DOC_META_KEYS
        assert "content_extraction" in meta
        assert "content_extraction" not in meta["document_meta"]
