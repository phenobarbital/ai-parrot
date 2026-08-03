from unittest.mock import AsyncMock

import pytest
from parrot.knowledge.wiki.tools import (
    WikiNoteTool,
    WikiPageTool,
    WikiQueryTool,
    WikiRelatedTool,
    WikiRememberTool,
    WikiStatusTool,
    create_wiki_tools,
)


@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.search_fts.return_value = [
        {"concept_id": "page-1", "title": "Test Page", "score": 0.9}
    ]
    store.get_page.return_value = {
        "concept_id": "page-1", "title": "Test Page", "body": "Content here"
    }
    store.neighbors.return_value = [
        {"concept_id": "page-2", "title": "Related", "rel": "references"}
    ]
    store.stats.return_value = {"total_pages": 100, "last_build": "2026-08-01"}
    store.upsert_pages.return_value = 1
    store.add_edges.return_value = 1
    return store


class TestWikiQueryTool:
    @pytest.mark.asyncio
    async def test_query_returns_results(self, mock_store):
        tool = WikiQueryTool(mock_store)
        result = await tool._execute(question="test query")
        mock_store.search_fts.assert_called_once()
        assert isinstance(result, str)


class TestWikiPageTool:
    @pytest.mark.asyncio
    async def test_get_page(self, mock_store):
        tool = WikiPageTool(mock_store)
        result = await tool._execute(page_id="page-1")
        mock_store.get_page.assert_called_once_with("page-1", include_body=True)
        assert result["concept_id"] == "page-1"

    @pytest.mark.asyncio
    async def test_get_page_not_found(self, mock_store):
        mock_store.get_page.return_value = None
        tool = WikiPageTool(mock_store)
        result = await tool._execute(page_id="missing")
        assert isinstance(result, str)
        assert "not found" in result.lower()


class TestWikiRelatedTool:
    @pytest.mark.asyncio
    async def test_get_related(self, mock_store):
        tool = WikiRelatedTool(mock_store)
        result = await tool._execute(page_id="page-1")
        mock_store.neighbors.assert_called_once()
        assert result == mock_store.neighbors.return_value


class TestWikiRememberTool:
    @pytest.mark.asyncio
    async def test_remember_saves(self, mock_store):
        tool = WikiRememberTool(mock_store)
        result = await tool._execute(fact="Important finding", category="decision")
        mock_store.upsert_pages.assert_called_once()
        assert result["category"] == "decision"
        assert result["linked"] is False

    @pytest.mark.asyncio
    async def test_remember_links(self, mock_store):
        tool = WikiRememberTool(mock_store)
        result = await tool._execute(
            fact="Important finding", category="decision", link_page_id="page-1"
        )
        mock_store.add_edges.assert_called_once()
        assert result["linked"] is True


class TestWikiNoteTool:
    @pytest.mark.asyncio
    async def test_note_appends(self, mock_store):
        tool = WikiNoteTool(mock_store)
        result = await tool._execute(page_id="page-1", text="A note")
        mock_store.get_page.assert_called_once()
        mock_store.upsert_pages.assert_called_once()
        assert result["status"] == "noted"

    @pytest.mark.asyncio
    async def test_note_page_not_found(self, mock_store):
        mock_store.get_page.return_value = None
        tool = WikiNoteTool(mock_store)
        result = await tool._execute(page_id="missing", text="A note")
        assert result["status"] == "error"
        mock_store.upsert_pages.assert_not_called()


class TestWikiStatusTool:
    @pytest.mark.asyncio
    async def test_status_returns_stats(self, mock_store):
        tool = WikiStatusTool(mock_store)
        result = await tool._execute()
        mock_store.stats.assert_called_once()
        assert result["total_pages"] == 100


class TestFactory:
    def test_create_wiki_tools(self, mock_store):
        tools = create_wiki_tools(mock_store)
        assert len(tools) == 6
        names = {t.name for t in tools}
        assert names == {"wiki_query", "wiki_page", "wiki_related",
                         "wiki_remember", "wiki_note", "wiki_status"}
