"""Tests for RSSContentInterface."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.interfaces.rss_content import RSSContentInterface


@pytest.fixture
def rss_content_interface():
    """Create a mocked RSSContentInterface instance."""
    with patch('parrot.interfaces.http.HTTPService.__init__', return_value=None):
        interface = RSSContentInterface()
        interface._executor = MagicMock()
        interface._semaphore = AsyncMock()
        interface._variables = {}
        return interface


class TestContentExtraction:
    """Tests for content extraction from HTML."""

    def test_extract_from_main_tag(self, rss_content_interface):
        """Content should be extracted from <main> element."""
        html = """
        <html>
        <body>
            <header><p>Header content to ignore</p></header>
            <main>
                <p>This is the main article content that should be extracted.</p>
                <p>Second paragraph with more relevant information.</p>
            </main>
            <footer><p>Footer to ignore</p></footer>
        </body>
        </html>
        """
        result = rss_content_interface._extract_main_content(html, max_chars=1000)
        assert "main article content" in result
        assert "Second paragraph" in result
        assert "Header content" not in result
        assert "Footer to ignore" not in result

    def test_extract_from_article_tag(self, rss_content_interface):
        """Content should be extracted from <article> element."""
        html = """
        <html>
        <body>
            <nav><p>Navigation menu</p></nav>
            <article>
                <p>Article content goes here with important information.</p>
                <p>More article content to be captured.</p>
            </article>
            <aside><p>Sidebar content</p></aside>
        </body>
        </html>
        """
        result = rss_content_interface._extract_main_content(html, max_chars=1000)
        assert "Article content goes here" in result
        assert "Navigation menu" not in result
        assert "Sidebar content" not in result

    def test_extract_from_content_class(self, rss_content_interface):
        """Content should be extracted from .content div."""
        html = """
        <html>
        <body>
            <div class="header">Header</div>
            <div class="content">
                <p>Blog post content that contains the main information.</p>
                <p>Additional paragraphs with useful details.</p>
            </div>
        </body>
        </html>
        """
        result = rss_content_interface._extract_main_content(html, max_chars=1000)
        assert "Blog post content" in result

    def test_fallback_to_paragraphs(self, rss_content_interface):
        """Should fallback to <p> tags when no container found."""
        html = """
        <html>
        <body>
            <p>First paragraph with substantial content for extraction.</p>
            <p>Second paragraph continues the narrative.</p>
        </body>
        </html>
        """
        result = rss_content_interface._extract_main_content(html, max_chars=1000)
        assert "First paragraph" in result

    def test_max_chars_limit(self, rss_content_interface):
        """Content should be limited to max_chars."""
        html = """
        <html>
        <body>
            <main>
                <p>This is a very long paragraph that contains a lot of text. It goes on and on with
                many words and sentences. The quick brown fox jumps over the lazy dog. Lorem ipsum
                dolor sit amet, consectetur adipiscing elit.</p>
            </main>
        </body>
        </html>
        """
        result = rss_content_interface._extract_main_content(html, max_chars=50)
        assert len(result) <= 60  # Some buffer for word boundary

    def test_boilerplate_filtering(self, rss_content_interface):
        """Boilerplate text should be filtered out."""
        html = """
        <html>
        <body>
            <main>
                <p>Subscribe to our newsletter for updates.</p>
                <p>Actual content that should be extracted from the page.</p>
                <p>Please accept our cookie policy.</p>
            </main>
        </body>
        </html>
        """
        result = rss_content_interface._extract_main_content(html, max_chars=1000)
        assert "Actual content" in result
        assert "cookie" not in result.lower()

    def test_clean_and_summarize(self, rss_content_interface):
        """Text should be cleaned and normalized."""
        text = "  Multiple   spaces   and   newlines\n\n\nshould   be   normalized.  "
        result = rss_content_interface._clean_and_summarize(text, max_chars=1000)
        assert "  " not in result
        assert "\n" not in result

    def test_sentence_boundary_truncation(self, rss_content_interface):
        """Long text should truncate at sentence boundary."""
        text = "First sentence here. Second sentence follows. Third is cut."
        result = rss_content_interface._clean_and_summarize(text, max_chars=45)
        assert result.endswith(".")
        assert "Third" not in result


class TestRSSWithContent:
    """Tests for read_rss_with_content integration."""

    @pytest.mark.asyncio
    async def test_read_rss_with_content_success(self, rss_content_interface):
        """Should fetch RSS and add content summaries."""
        mock_rss = {
            "title": "Test Feed",
            "url": "http://example.com/rss",
            "items": [
                {
                    "title": "Article 1",
                    "link": "http://example.com/1",
                    "description": "Short desc",
                    "pubDate": "2024-01-01"
                }
            ]
        }

        mock_html = """
        <main>
            <p>This is the full article content extracted from the page.</p>
        </main>
        """

        # Mock read_rss (parent method)
        rss_content_interface.read_rss = AsyncMock(return_value=mock_rss)
        # Mock async_request for content fetch
        rss_content_interface.async_request = AsyncMock(return_value=(mock_html, None))

        result = await rss_content_interface.read_rss_with_content(
            url="http://example.com/rss",
            limit=5
        )

        assert result['items'][0]['content_summary'] != ''
        assert "full article content" in result['items'][0]['content_summary']

    @pytest.mark.asyncio
    async def test_read_rss_with_content_fetch_error(self, rss_content_interface):
        """Should handle content fetch errors gracefully."""
        mock_rss = {
            "title": "Test Feed",
            "url": "http://example.com/rss",
            "items": [
                {
                    "title": "Article 1",
                    "link": "http://example.com/1",
                    "description": "Desc"
                }
            ]
        }

        rss_content_interface.read_rss = AsyncMock(return_value=mock_rss)
        rss_content_interface.async_request = AsyncMock(return_value=(None, "404 Not Found"))

        result = await rss_content_interface.read_rss_with_content(
            url="http://example.com/rss"
        )

        # Should still return result, just with empty summary
        assert result['items'][0]['content_summary'] == ''

    @pytest.mark.asyncio
    async def test_read_rss_with_content_no_fetch(self, rss_content_interface):
        """Should skip content fetching when fetch_content=False."""
        mock_rss = {
            "title": "Test Feed",
            "url": "http://example.com/rss",
            "items": [{"title": "Item", "link": "http://example.com/1"}]
        }

        rss_content_interface.read_rss = AsyncMock(return_value=mock_rss)
        rss_content_interface.async_request = AsyncMock()

        await rss_content_interface.read_rss_with_content(
            url="http://example.com/rss",
            fetch_content=False
        )

        # async_request should not be called for content
        rss_content_interface.async_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_markdown_output_format(self, rss_content_interface):
        """Should return markdown formatted output."""
        mock_rss = {
            "title": "Test Feed",
            "url": "http://example.com/rss",
            "items": [
                {
                    "title": "Test Article",
                    "link": "http://example.com/1",
                    "pubDate": "2024-01-01",
                    "content_summary": "Summary text"
                }
            ]
        }

        rss_content_interface.read_rss = AsyncMock(return_value=mock_rss)
        rss_content_interface._fetch_and_summarize = AsyncMock(return_value="Summary text")

        result = await rss_content_interface.read_rss_with_content(
            url="http://example.com/rss",
            output_format='markdown'
        )

        assert "# Test Feed" in result
        assert "## [Test Article]" in result


class TestHelperMethods:
    """Tests for helper methods."""

    def test_is_boilerplate_true(self, rss_content_interface):
        """Should detect boilerplate text."""
        assert rss_content_interface._is_boilerplate("Subscribe to our newsletter") is True
        assert rss_content_interface._is_boilerplate("Accept cookie policy") is True
        assert rss_content_interface._is_boilerplate("All Rights Reserved 2024") is True

    def test_is_boilerplate_false(self, rss_content_interface):
        """Should not flag real content as boilerplate."""
        assert rss_content_interface._is_boilerplate("Market analysis shows growth") is False
        assert rss_content_interface._is_boilerplate("The company announced new products") is False

    def test_find_content_container_priority(self, rss_content_interface):
        """Should find container in priority order."""
        from bs4 import BeautifulSoup

        html = """
        <body>
            <main><p>Main content here with enough text to pass the 100 char threshold for detection. This needs to be a bit longer to ensure it passes validation checks in the container finder method.</p></main>
            <article><p>Article content</p></article>
        </body>
        """
        soup = BeautifulSoup(html, 'html.parser')
        container = rss_content_interface._find_content_container(soup)

        assert container is not None
        assert container.name == 'main'
