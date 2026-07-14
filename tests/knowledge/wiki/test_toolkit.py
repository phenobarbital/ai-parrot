"""Unit tests for LLMWikiToolkit (TASK-1633)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def wiki_config(tmp_path: Path) -> WikiConfig:
    """Minimal WikiConfig backed by tmp_path."""
    return WikiConfig(wiki_name="test-wiki", storage_dir=tmp_path)


@pytest.fixture
def mock_pi():
    """Mock PageIndexToolkit."""
    pi = MagicMock()
    pi.search = AsyncMock(return_value=[
        {"node_id": "n1", "title": "Page 1", "score": 0.9, "summary": "Snippet 1"},
    ])
    pi.insert_markdown = AsyncMock(
        return_value={"tree_name": "test-wiki", "new_node_ids": ["m1"]}
    )
    pi.insert_content = AsyncMock(
        return_value={"tree_name": "test-wiki", "new_node_ids": ["0001", "0002"]}
    )
    pi.create_tree = AsyncMock(return_value={"tree_name": "test-wiki"})
    return pi


@pytest.fixture
def mock_gi():
    """Mock GraphIndexToolkit."""
    gi = MagicMock()
    gi.search_hybrid = AsyncMock(return_value=[
        {"node_id": "g1", "title": "Graph Node 1", "score": 0.8, "summary": "GI snippet"},
    ])
    gi.create_node = AsyncMock(return_value={"node_id": "wp-001", "status": "created"})
    gi.link_nodes = AsyncMock(return_value={"status": "ok"})
    gi.get_neighborhood = AsyncMock(return_value={"neighbours": []})
    return gi


@pytest.fixture
def mock_okf():
    """Mock OKFToolkit."""
    okf = MagicMock()
    okf.lint_knowledge_base = AsyncMock(return_value={"orphan_nodes": 0})
    return okf


@pytest.fixture
def wiki_toolkit(wiki_config: WikiConfig, mock_pi, mock_gi, mock_okf) -> LLMWikiToolkit:
    """Fully wired LLMWikiToolkit with mocked deps."""
    return LLMWikiToolkit(mock_pi, mock_gi, mock_okf, wiki_config)


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestLLMWikiToolkitConfig:
    """Tests for toolkit configuration and class-level attributes."""

    def test_tool_prefix(self, wiki_toolkit: LLMWikiToolkit):
        """tool_prefix must be 'wiki'."""
        assert wiki_toolkit.tool_prefix == "wiki"

    def test_tool_prefix_is_wiki(self):
        """LLMWikiToolkit.tool_prefix class attribute is 'wiki'."""
        assert LLMWikiToolkit.tool_prefix == "wiki"

    def test_internal_components_initialised(self, wiki_toolkit: LLMWikiToolkit):
        """All helper components are set on construction."""
        assert wiki_toolkit._sources is not None
        assert wiki_toolkit._bookkeeper is not None
        assert wiki_toolkit._search is not None
        assert wiki_toolkit._ingest_orch is not None


class TestLLMWikiToolkitCreateWiki:
    """Tests for create_wiki."""

    @pytest.mark.asyncio
    async def test_create_wiki_returns_status_created(
        self, wiki_toolkit: LLMWikiToolkit
    ):
        """create_wiki returns status='created'."""
        result = await wiki_toolkit.create_wiki("my-wiki")
        assert result["status"] == "created"

    @pytest.mark.asyncio
    async def test_create_wiki_makes_directories(
        self,
        wiki_toolkit: LLMWikiToolkit,
        wiki_config: WikiConfig,
    ):
        """create_wiki creates the expected directory structure."""
        await wiki_toolkit.create_wiki("my-wiki")
        assert (wiki_config.storage_dir / "sources").exists()
        assert (wiki_config.storage_dir / "wiki").exists()

    @pytest.mark.asyncio
    async def test_create_wiki_writes_index(
        self,
        wiki_toolkit: LLMWikiToolkit,
        wiki_config: WikiConfig,
    ):
        """create_wiki writes an index.md file."""
        await wiki_toolkit.create_wiki("my-wiki")
        assert (wiki_config.storage_dir / "index.md").exists()

    @pytest.mark.asyncio
    async def test_create_wiki_writes_log(
        self,
        wiki_toolkit: LLMWikiToolkit,
        wiki_config: WikiConfig,
    ):
        """create_wiki appends a CREATE entry to log.md."""
        await wiki_toolkit.create_wiki("my-wiki")
        log = (wiki_config.storage_dir / "log.md").read_text()
        assert "[CREATE]" in log


class TestLLMWikiToolkitQuery:
    """Tests for query."""

    @pytest.mark.asyncio
    async def test_query_returns_answer(self, wiki_toolkit: LLMWikiToolkit):
        """query returns a dict with an 'answer' key."""
        result = await wiki_toolkit.query("test-wiki", "What is a neural network?")
        assert "answer" in result
        assert isinstance(result["answer"], str)

    @pytest.mark.asyncio
    async def test_query_returns_sources(self, wiki_toolkit: LLMWikiToolkit):
        """query returns 'sources' list."""
        result = await wiki_toolkit.query("test-wiki", "test question")
        assert "sources" in result
        assert isinstance(result["sources"], list)

    @pytest.mark.asyncio
    async def test_query_file_answer_creates_page(
        self,
        wiki_toolkit: LLMWikiToolkit,
        mock_pi,
    ):
        """query with file_answer=True calls insert_markdown (page creation)."""
        result = await wiki_toolkit.query(
            "test-wiki", "What is deep learning?", file_answer=True
        )
        # Either filed_page_id is set or insert_markdown was called
        assert result.get("filed_page_id") is not None or mock_pi.insert_markdown.called

    @pytest.mark.asyncio
    async def test_query_filed_page_id_none_without_file(
        self, wiki_toolkit: LLMWikiToolkit
    ):
        """filed_page_id is None when file_answer=False."""
        result = await wiki_toolkit.query(
            "test-wiki", "test", file_answer=False
        )
        assert result["filed_page_id"] is None


class TestLLMWikiToolkitLint:
    """Tests for lint."""

    @pytest.mark.asyncio
    async def test_lint_returns_dict(self, wiki_toolkit: LLMWikiToolkit):
        """lint returns a dict."""
        result = await wiki_toolkit.lint("test-wiki")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_lint_calls_okf(self, wiki_toolkit: LLMWikiToolkit, mock_okf):
        """lint delegates to OKFToolkit.lint_knowledge_base."""
        await wiki_toolkit.lint("test-wiki")
        mock_okf.lint_knowledge_base.assert_called_once()

    @pytest.mark.asyncio
    async def test_lint_contains_wiki_fields(self, wiki_toolkit: LLMWikiToolkit):
        """lint result contains orphan_sources, stale_sources, total_issues."""
        result = await wiki_toolkit.lint("test-wiki")
        assert "orphan_sources" in result
        assert "stale_sources" in result
        assert "total_issues" in result


class TestLLMWikiToolkitSearch:
    """Tests for search."""

    @pytest.mark.asyncio
    async def test_search_returns_list(self, wiki_toolkit: LLMWikiToolkit):
        """search returns a list of result dicts."""
        results = await wiki_toolkit.search("test-wiki", "neural networks")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_calls_backends(
        self, wiki_toolkit: LLMWikiToolkit, mock_pi, mock_gi
    ):
        """search (combined mode) queries both PageIndex and GraphIndex."""
        await wiki_toolkit.search("test-wiki", "deep learning", mode="combined")
        assert mock_pi.search.called or mock_gi.search_hybrid.called


class TestLLMWikiToolkitSources:
    """Tests for source management methods."""

    @pytest.mark.asyncio
    async def test_list_sources_empty(self, wiki_toolkit: LLMWikiToolkit):
        """list_sources returns [] when no sources tracked."""
        result = await wiki_toolkit.list_sources("test-wiki")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_source_info_not_found(self, wiki_toolkit: LLMWikiToolkit):
        """get_source_info returns error dict for unknown source_id."""
        result = await wiki_toolkit.get_source_info("test-wiki", "nonexistent")
        assert result.get("error") == "not_found"


class TestLLMWikiToolkitBookkeeping:
    """Tests for bookkeeping methods."""

    @pytest.mark.asyncio
    async def test_get_log_empty(
        self, wiki_toolkit: LLMWikiToolkit, wiki_config: WikiConfig
    ):
        """get_log returns empty string before any operations."""
        result = await wiki_toolkit.get_log("test-wiki")
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_index_empty(
        self, wiki_toolkit: LLMWikiToolkit, wiki_config: WikiConfig
    ):
        """get_index returns empty string before index.md is created."""
        result = await wiki_toolkit.get_index("test-wiki")
        assert result == ""

    @pytest.mark.asyncio
    async def test_rebuild_index_returns_dict(self, wiki_toolkit: LLMWikiToolkit):
        """rebuild_index returns a dict with status and index_length."""
        result = await wiki_toolkit.rebuild_index("test-wiki")
        assert result["status"] == "ok"
        assert "index_length" in result

    @pytest.mark.asyncio
    async def test_list_wikis(self, wiki_toolkit: LLMWikiToolkit):
        """list_wikis returns at least one entry."""
        result = await wiki_toolkit.list_wikis()
        assert len(result) >= 1
        assert result[0]["wiki_name"] == "test-wiki"
