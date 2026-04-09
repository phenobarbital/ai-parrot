"""Tests for VectorStoreHandler._load_urls() refactor.

Verifies that _load_urls() delegates to WebScrapingLoader instead of
legacy WebScrapingTool, handles YouTube URL routing, crawl mode
mapping, and content_extraction passthrough.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.stores.models import Document


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_store():
    """Mock AbstractStore instance."""
    store = AsyncMock()
    store.add_documents = AsyncMock()
    return store


@pytest.fixture
def mock_config():
    """Mock StoreConfig instance."""
    config = MagicMock()
    config.vector_store = "postgres"
    config.table = "test_table"
    config.schema = "public"
    return config


@pytest.fixture
def handler():
    """Create a minimal VectorStoreHandler for testing _load_urls.

    Since VectorStoreHandler inherits from BaseView (aiohttp),
    we create it with minimal mocking of the request context.
    """
    from parrot.handlers.stores.handler import VectorStoreHandler

    h = object.__new__(VectorStoreHandler)
    # Provide a logger so _load_urls can log
    import logging
    h.logger = logging.getLogger("test.VectorStoreHandler")
    return h


# ── Tests ────────────────────────────────────────────────────────────


class TestLoadUrlsRefactor:
    """Test that _load_urls uses WebScrapingLoader, not WebScrapingTool."""

    @pytest.mark.asyncio
    async def test_load_urls_uses_loader(
        self, handler, mock_store, mock_config
    ):
        """_load_urls() instantiates WebScrapingLoader, not WebScrapingTool."""
        mock_loader_instance = AsyncMock()
        mock_loader_instance.load = AsyncMock(return_value=[
            Document(page_content="test", metadata={"url": "https://example.com"}),
        ])

        with patch(
            "parrot_loaders.webscraping.WebScrapingLoader",
            return_value=mock_loader_instance,
        ) as MockLoader:
            docs = await handler._load_urls(
                mock_store,
                ["https://example.com"],
                mock_config,
            )
            MockLoader.assert_called_once()
            mock_loader_instance.load.assert_called_once()
            assert len(docs) == 1
            assert docs[0].page_content == "test"

    @pytest.mark.asyncio
    async def test_load_urls_crawl_mode(
        self, handler, mock_store, mock_config
    ):
        """crawl_entire_site=True maps to crawl=True, depth=2."""
        mock_loader_instance = AsyncMock()
        mock_loader_instance.load = AsyncMock(return_value=[])

        with patch(
            "parrot_loaders.webscraping.WebScrapingLoader",
            return_value=mock_loader_instance,
        ) as MockLoader:
            await handler._load_urls(
                mock_store,
                ["https://example.com"],
                mock_config,
                crawl_entire_site=True,
            )
            call_kwargs = MockLoader.call_args
            assert call_kwargs.kwargs.get("crawl") is True
            assert call_kwargs.kwargs.get("depth") == 2

    @pytest.mark.asyncio
    async def test_load_urls_no_crawl_mode(
        self, handler, mock_store, mock_config
    ):
        """Default (no crawl) maps to crawl=False, depth=1."""
        mock_loader_instance = AsyncMock()
        mock_loader_instance.load = AsyncMock(return_value=[])

        with patch(
            "parrot_loaders.webscraping.WebScrapingLoader",
            return_value=mock_loader_instance,
        ) as MockLoader:
            await handler._load_urls(
                mock_store,
                ["https://example.com"],
                mock_config,
                crawl_entire_site=False,
            )
            call_kwargs = MockLoader.call_args
            assert call_kwargs.kwargs.get("crawl") is False
            assert call_kwargs.kwargs.get("depth") == 1

    @pytest.mark.asyncio
    async def test_load_urls_youtube_bypass(
        self, handler, mock_store, mock_config
    ):
        """YouTube URLs route to YoutubeLoader, others to WebScrapingLoader."""
        mock_yt_instance = AsyncMock()
        mock_yt_instance.load = AsyncMock(return_value=[
            Document(
                page_content="yt content",
                metadata={"url": "https://youtube.com/watch?v=abc"},
            ),
        ])

        mock_ws_instance = AsyncMock()
        mock_ws_instance.load = AsyncMock(return_value=[
            Document(
                page_content="web content",
                metadata={"url": "https://example.com"},
            ),
        ])

        with patch(
            "parrot_loaders.youtube.YoutubeLoader",
            return_value=mock_yt_instance,
        ), patch(
            "parrot_loaders.webscraping.WebScrapingLoader",
            return_value=mock_ws_instance,
        ):
            docs = await handler._load_urls(
                mock_store,
                [
                    "https://youtube.com/watch?v=abc",
                    "https://example.com/page",
                ],
                mock_config,
            )
            assert len(docs) == 2
            contents = [d.page_content for d in docs]
            assert "yt content" in contents
            assert "web content" in contents

    @pytest.mark.asyncio
    async def test_load_urls_youtube_only(
        self, handler, mock_store, mock_config
    ):
        """Only YouTube URLs -- WebScrapingLoader should not be called."""
        mock_yt_instance = AsyncMock()
        mock_yt_instance.load = AsyncMock(return_value=[
            Document(page_content="yt", metadata={}),
        ])

        with patch(
            "parrot_loaders.youtube.YoutubeLoader",
            return_value=mock_yt_instance,
        ) as MockYT:
            docs = await handler._load_urls(
                mock_store,
                ["https://youtube.com/watch?v=test"],
                mock_config,
            )
            MockYT.assert_called_once()
            assert len(docs) == 1

    @pytest.mark.asyncio
    async def test_load_urls_content_extraction_passthrough(
        self, handler, mock_store, mock_config
    ):
        """content_extraction parameter is passed to WebScrapingLoader."""
        mock_loader_instance = AsyncMock()
        mock_loader_instance.load = AsyncMock(return_value=[])

        with patch(
            "parrot_loaders.webscraping.WebScrapingLoader",
            return_value=mock_loader_instance,
        ) as MockLoader:
            await handler._load_urls(
                mock_store,
                ["https://example.com"],
                mock_config,
                content_extraction="trafilatura",
            )
            call_kwargs = MockLoader.call_args
            assert call_kwargs.kwargs.get("content_extraction") == "trafilatura"

    @pytest.mark.asyncio
    async def test_load_urls_default_content_extraction(
        self, handler, mock_store, mock_config
    ):
        """Default content_extraction is 'auto'."""
        mock_loader_instance = AsyncMock()
        mock_loader_instance.load = AsyncMock(return_value=[])

        with patch(
            "parrot_loaders.webscraping.WebScrapingLoader",
            return_value=mock_loader_instance,
        ) as MockLoader:
            await handler._load_urls(
                mock_store,
                ["https://example.com"],
                mock_config,
            )
            call_kwargs = MockLoader.call_args
            assert call_kwargs.kwargs.get("content_extraction") == "auto"

    @pytest.mark.asyncio
    async def test_load_urls_empty_list(
        self, handler, mock_store, mock_config
    ):
        """Empty URL list returns empty docs."""
        docs = await handler._load_urls(
            mock_store,
            [],
            mock_config,
        )
        assert docs == []


class TestNoLegacyImports:
    """Verify legacy scraping imports are removed from handler."""

    def test_no_webscraping_tool_import(self):
        """WebScrapingTool should not be imported in handler module."""
        import parrot.handlers.stores.handler as handler_mod
        source = handler_mod.__file__
        with open(source) as f:
            code = f.read()
        assert "WebScrapingTool" not in code
        assert "ScrapingStep" not in code
        assert "Navigate" not in code
