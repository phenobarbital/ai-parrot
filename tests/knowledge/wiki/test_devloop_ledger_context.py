"""Tests for DevLoopWikiSearch ledger context integration."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch


@pytest.fixture
def mock_wiki_store():
    """Create a mock wiki store."""
    store = MagicMock()
    return store


@pytest.fixture
def mock_wiki_config():
    """Create a mock wiki config."""
    config = MagicMock()
    config.is_built.return_value = True
    config.storage_path.return_value = Path("/tmp/wiki")
    config.wiki_name = "test_wiki"
    config.backend = "sqlite"
    return config


class TestDevLoopWikiLedgerContext:
    """Test DevLoopWikiSearch with ledger context."""

    @pytest.mark.asyncio
    async def test_linked_worktree_opens_main_wiki(self) -> None:
        """Test that linked worktree opens main checkout's wiki plane."""
        with patch("parrot.knowledge.wiki.project.find_project_root") as mock_find_project, \
             patch("parrot.knowledge.wiki.project.find_shared_root") as mock_find_shared, \
             patch("parrot.knowledge.wiki.project.load_project_config") as mock_load_config, \
             patch("parrot.knowledge.wiki.store.create_wiki_store") as mock_create_store:
            
            # Simulate linked worktree scenario
            worktree_root = Path("/path/to/worktree")
            main_root = Path("/path/to/main")
            
            mock_find_project.return_value = worktree_root
            mock_find_shared.return_value = main_root
            mock_load_config.return_value = MagicMock()
            mock_load_config.return_value.is_built.return_value = True
            mock_load_config.return_value.storage_path.return_value = main_root / ".parrot" / "wiki"
            mock_load_config.return_value.wiki_name = "test_wiki"
            mock_load_config.return_value.backend = "sqlite"
            
            mock_create_store.return_value = MagicMock()
            
            # Should succeed and use shared root
            result = DevLoopWikiSearch.from_project(worktree_root)
            
            assert result is not None
            mock_find_shared.assert_called_once_with(worktree_root)
            mock_load_config.assert_called_once_with(main_root)

    @pytest.mark.asyncio
    async def test_ledger_context_appended_within_budget(self) -> None:
        """Test that relevant ledger context is appended within budget."""
        with patch("parrot.knowledge.wiki.project.find_project_root"), \
             patch("parrot.knowledge.wiki.project.find_shared_root"), \
             patch("parrot.knowledge.wiki.project.load_project_config"), \
             patch("parrot.knowledge.wiki.store.create_wiki_store"):
            
            # Create a search instance
            search = DevLoopWikiSearch(store=MagicMock(), wiki_name="test")
            
            # Mock wiki context
            with patch.object(search, "_get_ledger_context", new=AsyncMock(return_value="- [minor] issue:TEST-123 Test issue (open)")):
                with patch("parrot.knowledge.wiki.context.pack_results") as mock_pack:
                    # Mock wiki search results
                    mock_result = MagicMock()
                    mock_result.text = "# Wiki Content\nSome wiki content here"
                    mock_result.results_packed = True
                    mock_pack.return_value = mock_result
                    
                    with patch("parrot.knowledge.wiki.search.WikiCombinedSearch") as mock_search_class:
                        mock_search_instance = MagicMock()
                        mock_search_instance.search = AsyncMock(return_value=["result1", "result2"])
                        mock_search_class.return_value = mock_search_instance
                        
                        # Get research context
                        context = await search.build_research_context("Test query about TASK-123")
                        
                        assert context is not None
                        assert "Wiki Content" in context
                        assert "Related Issues" in context
                        assert "issue:TEST-123" in context

    @pytest.mark.asyncio
    async def test_unavailable_ledger_leaves_research_usable(self) -> None:
        """Test that unavailable ledger leaves research usable."""
        with patch("parrot.knowledge.wiki.project.find_project_root"), \
             patch("parrot.knowledge.wiki.project.find_shared_root"), \
             patch("parrot.knowledge.wiki.project.load_project_config"), \
             patch("parrot.knowledge.wiki.store.create_wiki_store"):
            
            # Create a search instance
            search = DevLoopWikiSearch(store=MagicMock(), wiki_name="test")
            
            # Mock ledger context to be unavailable
            with patch.object(search, "_get_ledger_context", new=AsyncMock(return_value=None)):
                with patch("parrot.knowledge.wiki.context.pack_results") as mock_pack:
                    # Mock wiki search results
                    mock_result = MagicMock()
                    mock_result.text = "# Wiki Content\nSome wiki content here"
                    mock_result.results_packed = True
                    mock_pack.return_value = mock_result
                    
                    with patch("parrot.knowledge.wiki.search.WikiCombinedSearch") as mock_search_class:
                        mock_search_instance = MagicMock()
                        mock_search_instance.search = AsyncMock(return_value=["result1", "result2"])
                        mock_search_class.return_value = mock_search_instance
                        
                        # Get research context
                        context = await search.build_research_context("Test query")
                        
                        assert context is not None
                        assert "Wiki Content" in context
                        # Should not have ledger section when ledger is unavailable
                        assert "Related Issues" not in context or "## Related Issues" not in context

    @pytest.mark.asyncio
    async def test_empty_ledger_context_handled_gracefully(self) -> None:
        """Test that empty ledger context is handled gracefully."""
        with patch("parrot.knowledge.wiki.project.find_project_root"), \
             patch("parrot.knowledge.wiki.project.find_shared_root"), \
             patch("parrot.knowledge.wiki.project.load_project_config"), \
             patch("parrot.knowledge.wiki.store.create_wiki_store"):
            
            # Create a search instance
            search = DevLoopWikiSearch(store=MagicMock(), wiki_name="test")
            
            # Mock empty ledger context
            with patch.object(search, "_get_ledger_context", new=AsyncMock(return_value="")):
                with patch("parrot.knowledge.wiki.context.pack_results") as mock_pack:
                    # Mock wiki search results
                    mock_result = MagicMock()
                    mock_result.text = "# Wiki Content\nSome wiki content here"
                    mock_result.results_packed = True
                    mock_pack.return_value = mock_result
                    
                    with patch("parrot.knowledge.wiki.search.WikiCombinedSearch") as mock_search_class:
                        mock_search_instance = MagicMock()
                        mock_search_instance.search = AsyncMock(return_value=["result1", "result2"])
                        mock_search_class.return_value = mock_search_instance
                        
                        # Get research context
                        context = await search.build_research_context("Test query")
                        
                        assert context is not None
                        assert "Wiki Content" in context
                        # Should not have ledger section when ledger context is empty
                        assert "Related Issues" not in context or "## Related Issues" not in context

    def test_extract_file_paths_from_query(self) -> None:
        """Test file path extraction from queries."""
        with patch("parrot.knowledge.wiki.project.find_project_root"), \
             patch("parrot.knowledge.wiki.project.find_shared_root"), \
             patch("parrot.knowledge.wiki.project.load_project_config"), \
             patch("parrot.knowledge.wiki.store.create_wiki_store"):
            
            # Create a search instance
            search = DevLoopWikiSearch(store=MagicMock(), wiki_name="test")
            
            # Test task ID extraction
            paths = search._extract_file_paths_from_query("Fix bug in TASK-123 implementation")
            assert "sdd/tasks/active/TASK-123.md" in paths
            assert "sdd/tasks/completed/TASK-123.md" in paths
            
            # Test file path extraction
            paths = search._extract_file_paths_from_query("Update wiki_search.py and config.json")
            assert "wiki_search.py" in paths
            assert "config.json" in paths
            
            # Test combined extraction
            paths = search._extract_file_paths_from_query("Implement feature in wiki_search.py related to TASK-456")
            assert "wiki_search.py" in paths
            assert "sdd/tasks/active/TASK-456.md" in paths


if __name__ == "__main__":
    pytest.main([__file__])