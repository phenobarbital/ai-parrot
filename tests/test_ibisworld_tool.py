"""
Test suite for IBISWorld Tool
"""
import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from parrot.tools.ibisworld import IBISWorldTool, IBISWorldSearchArgs


class TestIBISWorldSearchArgsSchema:
    """Test the Pydantic schema for IBISWorld search arguments."""

    def test_valid_schema(self):
        """Test valid schema instantiation."""
        schema = IBISWorldSearchArgs(
            query="restaurant industry",
            max_results=5,
            extract_content=True,
            include_tables=True
        )
        assert schema.query == "restaurant industry"
        assert schema.max_results == 5
        assert schema.extract_content is True
        assert schema.include_tables is True

    def test_default_values(self):
        """Test default values are applied correctly."""
        schema = IBISWorldSearchArgs(query="test")
        assert schema.max_results == 5
        assert schema.extract_content is True
        assert schema.include_tables is True

    def test_max_results_validation(self):
        """Test max_results validation constraints."""
        # Should fail - too low
        with pytest.raises(ValueError):
            IBISWorldSearchArgs(query="test", max_results=0)

        # Should fail - too high
        with pytest.raises(ValueError):
            IBISWorldSearchArgs(query="test", max_results=11)

        # Should pass
        schema = IBISWorldSearchArgs(query="test", max_results=10)
        assert schema.max_results == 10


class TestIBISWorldTool:
    """Test the IBISWorldTool functionality."""

    @pytest.fixture
    def ibisworld_tool(self):
        """Create an IBISWorldTool instance for testing."""
        return IBISWorldTool()

    def test_tool_initialization(self, ibisworld_tool):
        """Test tool is initialized correctly."""
        assert ibisworld_tool.name == "ibisworld_search"
        assert ibisworld_tool.description is not None
        assert ibisworld_tool.args_schema == IBISWorldSearchArgs
        assert ibisworld_tool.IBISWORLD_DOMAIN == "ibisworld.com"

    def test_tool_schema_generation(self, ibisworld_tool):
        """Test get_tool_schema returns valid schema."""
        schema = ibisworld_tool.get_tool_schema()

        assert "name" in schema
        assert schema["name"] == "ibisworld_search"
        assert "description" in schema
        assert "parameters" in schema

        params = schema["parameters"]
        assert "properties" in params
        assert "query" in params["properties"]
        assert "max_results" in params["properties"]
        assert "extract_content" in params["properties"]
        assert "include_tables" in params["properties"]

    def test_extract_title(self, ibisworld_tool):
        """Test title extraction from HTML."""
        from bs4 import BeautifulSoup

        # Test with article-title class
        html = '<html><h1 class="article-title">Test Title</h1></html>'
        soup = BeautifulSoup(html, 'html.parser')
        title = ibisworld_tool._extract_title(soup)
        assert title == "Test Title"

        # Test with fallback to regular h1
        html = '<html><h1>Fallback Title</h1></html>'
        soup = BeautifulSoup(html, 'html.parser')
        title = ibisworld_tool._extract_title(soup)
        assert title == "Fallback Title"

    def test_extract_main_content(self, ibisworld_tool):
        """Test content extraction from HTML."""
        from bs4 import BeautifulSoup

        html = '''
        <html>
            <div class="article-content">
                <p>First paragraph with content.</p>
                <p>Second paragraph with more content.</p>
            </div>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        content = ibisworld_tool._extract_main_content(soup)

        assert "First paragraph" in content
        assert "Second paragraph" in content

    def test_extract_metadata(self, ibisworld_tool):
        """Test metadata extraction from HTML."""
        from bs4 import BeautifulSoup

        html = '''
        <html>
            <head>
                <meta name="author" content="John Doe">
                <meta property="article:published_time" content="2024-01-15">
            </head>
            <body>
                <span class="publish-date">2024-01-15</span>
            </body>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        metadata = ibisworld_tool._extract_metadata(soup)

        assert "author" in metadata
        assert metadata["author"] == "John Doe"
        assert "publication_date" in metadata

    def test_extract_tables(self, ibisworld_tool):
        """Test table extraction from HTML."""
        from bs4 import BeautifulSoup

        html = '''
        <html>
            <table>
                <tr>
                    <th>Header 1</th>
                    <th>Header 2</th>
                </tr>
                <tr>
                    <td>Data 1</td>
                    <td>Data 2</td>
                </tr>
                <tr>
                    <td>Data 3</td>
                    <td>Data 4</td>
                </tr>
            </table>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        tables = ibisworld_tool._extract_tables(soup)

        assert len(tables) == 1
        table = tables[0]
        assert "headers" in table
        assert "rows" in table
        assert len(table["headers"]) == 2
        assert len(table["rows"]) == 3  # Including header row

    def test_extract_statistics(self, ibisworld_tool):
        """Test statistics extraction from HTML."""
        from bs4 import BeautifulSoup

        html = '''
        <html>
            <div class="key-stats">
                <dt>Market Size: $100 billion</dt>
                <dd>Growth Rate: 5.2%</dd>
            </div>
        </html>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        stats = ibisworld_tool._extract_statistics(soup)

        assert isinstance(stats, dict)
        # Statistics extraction may vary based on HTML structure

    @pytest.mark.asyncio
    async def test_extract_article_content_mock(self, ibisworld_tool):
        """Test article content extraction with mocked HTTP response."""
        mock_html = '''
        <html>
            <head>
                <title>Test Article</title>
            </head>
            <body>
                <h1>Industry Report Title</h1>
                <div class="article-content">
                    <p>This is the main content of the article.</p>
                    <p>More detailed information here.</p>
                </div>
                <table>
                    <tr><th>Year</th><th>Revenue</th></tr>
                    <tr><td>2023</td><td>$1B</td></tr>
                </table>
            </body>
        </html>
        '''

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.text = AsyncMock(return_value=mock_html)

        with patch('aiohttp.ClientSession') as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            result = await ibisworld_tool._extract_article_content(
                "https://ibisworld.com/test",
                include_tables=True
            )

            assert result is not None
            assert "title" in result
            assert "content" in result
            assert "tables" in result
            assert "metadata" in result
            assert "statistics" in result

    @pytest.mark.asyncio
    async def test_extract_article_content_http_error(self, ibisworld_tool):
        """Test article content extraction handles HTTP errors."""
        mock_response = AsyncMock()
        mock_response.status = 404

        with patch('aiohttp.ClientSession') as mock_session:
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_response

            result = await ibisworld_tool._extract_article_content(
                "https://ibisworld.com/nonexistent"
            )

            assert "error" in result
            assert result["error"] == "HTTP 404"

    @pytest.mark.asyncio
    async def test_basic_search_mock(self, ibisworld_tool):
        """Test basic search with mocked Google Site Search."""
        mock_search_result = {
            'query': 'restaurant industry',
            'site': 'ibisworld.com',
            'search_query': 'restaurant industry site:ibisworld.com',
            'total_results': 2,
            'results': [
                {
                    'title': 'Restaurant Industry Overview',
                    'link': 'https://ibisworld.com/restaurant',
                    'snippet': 'Industry analysis...',
                    'description': 'Industry analysis...'
                },
                {
                    'title': 'Fast Food Trends',
                    'link': 'https://ibisworld.com/fast-food',
                    'snippet': 'Market trends...',
                    'description': 'Market trends...'
                }
            ]
        }

        # Mock the parent class _execute method
        with patch.object(
            ibisworld_tool.__class__.__bases__[0],
            '_execute',
            new_callable=AsyncMock,
            return_value=mock_search_result
        ):
            # Mock content extraction
            mock_content = {
                'url': 'https://ibisworld.com/restaurant',
                'title': 'Restaurant Industry Overview',
                'content': 'Full article content here.',
                'metadata': {},
                'tables': [],
                'statistics': {}
            }

            with patch.object(
                ibisworld_tool,
                '_extract_article_content',
                new_callable=AsyncMock,
                return_value=mock_content
            ):
                result = await ibisworld_tool._execute(
                    query="restaurant industry",
                    max_results=2,
                    extract_content=True,
                    include_tables=True
                )

                assert result is not None
                assert result['source'] == 'IBISWorld'
                assert result['domain'] == 'ibisworld.com'
                assert result['content_extracted'] is True
                assert len(result['results']) == 2

    @pytest.mark.asyncio
    async def test_search_without_content_extraction(self, ibisworld_tool):
        """Test search without content extraction."""
        mock_search_result = {
            'query': 'automotive',
            'site': 'ibisworld.com',
            'search_query': 'automotive site:ibisworld.com',
            'total_results': 1,
            'results': [
                {
                    'title': 'Automotive Industry',
                    'link': 'https://ibisworld.com/automotive',
                    'snippet': 'Industry overview...',
                    'description': 'Industry overview...'
                }
            ]
        }

        with patch.object(
            ibisworld_tool.__class__.__bases__[0],
            '_execute',
            new_callable=AsyncMock,
            return_value=mock_search_result
        ):
            result = await ibisworld_tool._execute(
                query="automotive",
                max_results=1,
                extract_content=False,
                include_tables=False
            )

            assert result is not None
            assert result['content_extracted'] is False
            # Should not have extracted_content in results
            for item in result['results']:
                assert 'extracted_content' not in item


class TestIBISWorldToolIntegration:
    """Integration tests for IBISWorldTool."""

    @pytest.mark.asyncio
    async def test_tool_result_format(self):
        """Test that tool returns proper ToolResult object."""
        tool = IBISWorldTool()

        mock_result = {
            'query': 'test',
            'site': 'ibisworld.com',
            'search_query': 'test site:ibisworld.com',
            'total_results': 0,
            'results': []
        }

        with patch.object(
            tool.__class__.__bases__[0],
            '_execute',
            new_callable=AsyncMock,
            return_value=mock_result
        ):
            result = await tool.run(
                query="test",
                max_results=1,
                extract_content=False
            )

            # ToolResult attributes
            assert hasattr(result, "status")
            assert hasattr(result, "result")
            assert hasattr(result, "error")
            assert hasattr(result, "metadata")
            assert hasattr(result, "timestamp")

            # Verify timestamp format
            datetime.fromisoformat(result.timestamp)

    @pytest.mark.asyncio
    async def test_validate_args(self):
        """Test argument validation."""
        tool = IBISWorldTool()

        # Valid arguments
        validated = tool.validate_args(
            query="test",
            max_results=5,
            extract_content=True,
            include_tables=True
        )
        assert validated.query == "test"
        assert validated.max_results == 5

        # Invalid max_results
        with pytest.raises(ValueError):
            tool.validate_args(
                query="test",
                max_results=20  # Too high
            )


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
