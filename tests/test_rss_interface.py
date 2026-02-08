import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.interfaces.rss import RSSInterface

@pytest.fixture
def rss_interface():
    # Mock HTTPService init as it requires args/kwargs
    with patch('parrot.interfaces.http.HTTPService.__init__', return_value=None):
        interface = RSSInterface()
        interface._executor = MagicMock() # Mock executor
        interface._semaphore = AsyncMock() # Mock semaphore
        interface._variables = {} # Mock variables
        return interface

@pytest.mark.asyncio
async def test_read_rss_success_rss2(rss_interface):
    # Mock XML response for RSS 2.0
    mock_xml = """
    <rss version="2.0">
        <channel>
            <title>Test Feed</title>
            <item>
                <title>Item 1</title>
                <link>http://example.com/1</link>
                <description>Desc 1</description>
                <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
                <guid>1</guid>
            </item>
            <item>
                <title>Item 2</title>
                <link>http://example.com/2</link>
                 <description>Desc 2</description>
            </item>
        </channel>
    </rss>
    """
    
    # Mock async_request
    rss_interface.async_request = AsyncMock(return_value=(mock_xml, None))

    result = await rss_interface.read_rss("http://test.com/rss", output_format='dict')

    assert result['title'] == 'Test Feed'
    assert len(result['items']) == 2
    assert result['items'][0]['title'] == 'Item 1'
    assert result['items'][0]['link'] == 'http://example.com/1'

@pytest.mark.asyncio
async def test_read_rss_success_atom(rss_interface):
    # Mock XML response for Atom
    mock_xml = """
    <feed xmlns="http://www.w3.org/2005/Atom">
        <title>Atom Feed</title>
        <entry>
            <title>Atom Entry</title>
            <link href="http://example.com/atom"/>
            <updated>2024-01-01T00:00:00Z</updated>
            <id>atom1</id>
            <summary>Atom Summary</summary>
        </entry>
    </feed>
    """
    
    rss_interface.async_request = AsyncMock(return_value=(mock_xml, None))

    result = await rss_interface.read_rss("http://test.com/atom", output_format='dict')

    assert result['title'] == 'Atom Feed'
    assert len(result['items']) == 1
    assert result['items'][0]['title'] == 'Atom Entry'
    # The parsing logic might return list of links or dict depending on xmltodict structure
    # Our implementation logic handles list of links or single dict
    assert result['items'][0]['link'] == 'http://example.com/atom'

@pytest.mark.asyncio
async def test_read_rss_limit(rss_interface):
    # Mock RSS with 5 items
    items = "".join([f"<item><title>Item {i}</title></item>" for i in range(5)])
    mock_xml = f"<rss><channel><title>Limit Test</title>{items}</channel></rss>"
    
    rss_interface.async_request = AsyncMock(return_value=(mock_xml, None))

    result = await rss_interface.read_rss("http://test.com", limit=2)
    
    assert len(result['items']) == 2
    assert result['items'][1]['title'] == 'Item 1'

@pytest.mark.asyncio
async def test_read_rss_markdown_format(rss_interface):
    mock_xml = """
    <rss>
        <channel>
            <title>Markdown Feed</title>
            <item>
                <title>MD Item</title>
                <link>http://md.com</link>
                <description>Content</description>
                <pubDate>2024</pubDate>
            </item>
        </channel>
    </rss>
    """
    rss_interface.async_request = AsyncMock(return_value=(mock_xml, None))

    md = await rss_interface.read_rss("http://test.com", output_format='markdown')

    assert "# Markdown Feed" in md
    assert "## [MD Item](http://md.com)" in md
    assert "**Date:** 2024" in md

@pytest.mark.asyncio
async def test_read_rss_error_handling(rss_interface):
    # Mock request error
    rss_interface.async_request = AsyncMock(return_value=(None, "404 Not Found"))
    
    result = await rss_interface.read_rss("http://bad.com")
    
    assert result == []

@pytest.mark.asyncio
async def test_read_rss_invalid_xml(rss_interface):
    # Mock valid response but invalid XML
    rss_interface.async_request = AsyncMock(return_value=("Not XML", None))
    
    result = await rss_interface.read_rss("http://text.com")
    
    assert result == []
