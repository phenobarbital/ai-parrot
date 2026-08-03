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
from parrot.tools.abstract import ToolResult


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
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.result["concept_id"] == "page-1"

    @pytest.mark.asyncio
    async def test_get_page_not_found(self, mock_store):
        mock_store.get_page.return_value = None
        tool = WikiPageTool(mock_store)
        result = await tool._execute(page_id="missing")
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "not found" in result.error.lower()


class TestWikiRelatedTool:
    @pytest.mark.asyncio
    async def test_get_related(self, mock_store):
        tool = WikiRelatedTool(mock_store)
        result = await tool._execute(page_id="page-1")
        mock_store.neighbors.assert_called_once()
        assert isinstance(result, ToolResult)
        assert result.result["neighbors"] == mock_store.neighbors.return_value


class TestWikiRememberTool:
    @pytest.mark.asyncio
    async def test_remember_saves(self, mock_store):
        tool = WikiRememberTool(mock_store)
        result = await tool._execute(fact="Important finding", category="decision")
        mock_store.upsert_pages.assert_called_once()
        assert isinstance(result, ToolResult)
        assert result.result["category"] == "decision"
        assert result.result["linked"] is False

    @pytest.mark.asyncio
    async def test_remember_links(self, mock_store):
        tool = WikiRememberTool(mock_store)
        result = await tool._execute(
            fact="Important finding", category="decision", link_page_id="page-1"
        )
        mock_store.add_edges.assert_called_once()
        assert result.result["linked"] is True

    @pytest.mark.asyncio
    async def test_remember_logs_to_bookkeeper(self, mock_store, tmp_path):
        tool = WikiRememberTool(mock_store, storage_dir=tmp_path)
        await tool._execute(fact="Important finding", category="decision")
        log_path = tmp_path / "log.md"
        assert log_path.exists()
        assert "[REMEMBER]" in log_path.read_text()

    @pytest.mark.asyncio
    async def test_remember_no_bookkeeper_when_storage_dir_none(self, mock_store):
        # Default (no storage_dir) must not raise and must not write anything.
        tool = WikiRememberTool(mock_store)
        result = await tool._execute(fact="Important finding")
        assert result.success is True


class TestWikiNoteTool:
    @pytest.mark.asyncio
    async def test_note_appends(self, mock_store):
        tool = WikiNoteTool(mock_store)
        result = await tool._execute(page_id="page-1", text="A note")
        mock_store.get_page.assert_called_once()
        mock_store.upsert_pages.assert_called_once()
        assert result.result["status"] == "noted"

    @pytest.mark.asyncio
    async def test_note_page_not_found(self, mock_store):
        mock_store.get_page.return_value = None
        tool = WikiNoteTool(mock_store)
        result = await tool._execute(page_id="missing", text="A note")
        assert result.success is False
        mock_store.upsert_pages.assert_not_called()

    @pytest.mark.asyncio
    async def test_note_logs_to_bookkeeper(self, mock_store, tmp_path):
        tool = WikiNoteTool(mock_store, storage_dir=tmp_path)
        await tool._execute(page_id="page-1", text="A note")
        log_path = tmp_path / "log.md"
        assert log_path.exists()
        assert "[NOTE]" in log_path.read_text()


class TestWikiStatusTool:
    @pytest.mark.asyncio
    async def test_status_returns_stats(self, mock_store):
        tool = WikiStatusTool(mock_store)
        result = await tool._execute()
        mock_store.stats.assert_called_once()
        assert result.result["total_pages"] == 100


class TestFactory:
    def test_create_wiki_tools(self, mock_store):
        tools = create_wiki_tools(mock_store)
        assert len(tools) == 6
        names = {t.name for t in tools}
        assert names == {"wiki_query", "wiki_page", "wiki_related",
                         "wiki_remember", "wiki_note", "wiki_status"}

    def test_create_wiki_tools_wires_storage_dir_for_bookkeeping(self, mock_store, tmp_path):
        from parrot.knowledge.wiki.project import WikiProjectConfig

        config = WikiProjectConfig(wiki_name="test")
        tools = create_wiki_tools(mock_store, root=tmp_path, config=config)
        by_name = {t.name: t for t in tools}
        assert by_name["wiki_remember"]._storage_dir == config.storage_path(tmp_path)
        assert by_name["wiki_note"]._storage_dir == config.storage_path(tmp_path)
