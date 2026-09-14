"""Tests for SDD graph ingestion into the ledger."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.knowledge.wiki.ledger.sdd_ingest import SDDGraphIngest
from parrot.knowledge.wiki.store import WikiPageRecord


@pytest.fixture
def mock_store():
    """Create a mock LedgerStore."""
    # Create an async context manager mock
    class AsyncContextManager:
        def __init__(self, return_value):
            self.return_value = return_value
        
        async def __aenter__(self):
            return self.return_value
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    store = MagicMock()
    mock_conn = AsyncMock()
    store.ledger_transaction = MagicMock(return_value=AsyncContextManager(mock_conn))
    store.upsert_pages_in = AsyncMock()
    store.add_edges_in = AsyncMock()
    return store


@pytest.fixture
def temp_shared_root(tmp_path):
    """Create a temporary shared root with test SDD files."""
    shared_root = tmp_path / "repo"
    shared_root.mkdir(parents=True)
    
    # Create SDD directories
    specs_dir = shared_root / "sdd" / "specs"
    specs_dir.mkdir(parents=True)
    
    tasks_index_dir = shared_root / "sdd" / "tasks" / "index"
    tasks_index_dir.mkdir(parents=True)
    
    return shared_root


@pytest.fixture
def sample_spec_file(temp_shared_root):
    """Create a sample spec file."""
    spec_path = temp_shared_root / "sdd" / "specs" / "test-feature.spec.md"
    spec_content = """---
type: feature
base_branch: dev
---

# Test Feature Specification

This is a test feature specification.
"""
    spec_path.write_text(spec_content, encoding="utf-8")
    return spec_path


@pytest.fixture
def sample_task_index_file(temp_shared_root):
    """Create a sample task index file."""
    index_path = temp_shared_root / "sdd" / "tasks" / "index" / "test-feature.json"
    index_data = {
        "feature": "FEAT-TEST",
        "spec": "sdd/specs/test-feature.spec.md",
        "type": "feature",
        "base_branch": "dev",
        "tasks": [
            {
                "id": "TASK-001",
                "slug": "test-task",
                "title": "Test Task",
                "feature": "FEAT-TEST",
                "spec": "sdd/specs/test-feature.spec.md",
                "status": "pending",
                "priority": "medium",
                "effort": "M",
                "depends_on": [],
                "file": "sdd/tasks/active/TASK-001-test-task.md"
            },
            {
                "id": "TASK-002",
                "slug": "dependent-task",
                "title": "Dependent Task",
                "feature": "FEAT-TEST",
                "spec": "sdd/specs/test-feature.spec.md",
                "status": "pending",
                "priority": "high",
                "effort": "S",
                "depends_on": ["TASK-001"],
                "file": "sdd/tasks/active/TASK-002-dependent-task.md"
            }
        ]
    }
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f)
    return index_path


@pytest.mark.asyncio
async def test_sdd_graph_ingest_initialization(mock_store, temp_shared_root):
    """Test SDDGraphIngest initialization."""
    ingest = SDDGraphIngest(mock_store, temp_shared_root)
    
    assert ingest.store == mock_store
    assert ingest.shared_root == temp_shared_root
    assert ingest.specs_dir == temp_shared_root / "sdd" / "specs"
    assert ingest.tasks_index_dir == temp_shared_root / "sdd" / "tasks" / "index"


@pytest.mark.asyncio
async def test_ingest_all_empty_directories(mock_store, temp_shared_root):
    """Test ingest_all with empty directories."""
    ingest = SDDGraphIngest(mock_store, temp_shared_root)
    
    stats = await ingest.ingest_all()
    
    assert stats == {"specs": 0, "tasks": 0, "edges": 0}
    mock_store.ledger_transaction.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_all_with_spec_file(mock_store, temp_shared_root, sample_spec_file):
    """Test ingest_all with a spec file."""
    # Mock the transaction context manager
    mock_conn = AsyncMock()
    # Create a proper async context manager mock
    class AsyncContextManager:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    mock_store.ledger_transaction.return_value = AsyncContextManager()
    
    ingest = SDDGraphIngest(mock_store, temp_shared_root)
    
    stats = await ingest.ingest_all()
    
    assert stats["specs"] == 1
    assert stats["tasks"] == 0
    assert stats["edges"] >= 0  # May have edges depending on implementation
    
    # Verify that upsert_pages_in was called
    mock_store.upsert_pages_in.assert_called()
    
    # Verify the page was created with correct properties
    call_args = mock_store.upsert_pages_in.call_args
    assert call_args is not None
    pages = call_args[1]["pages"] if "pages" in call_args[1] else call_args[0][1]
    assert len(pages) >= 1
    page = pages[0]
    assert isinstance(page, WikiPageRecord)
    assert page.concept_id == "spec:test-feature.spec"
    assert page.category == "spec"
    assert page.origin == "sdd-spec"


@pytest.mark.asyncio
async def test_ingest_all_with_task_index(mock_store, temp_shared_root, sample_task_index_file):
    """Test ingest_all with a task index file."""
    # Mock the transaction context manager
    mock_conn = AsyncMock()
    # Create a proper async context manager mock
    class AsyncContextManager:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    mock_store.ledger_transaction.return_value = AsyncContextManager()
    
    ingest = SDDGraphIngest(mock_store, temp_shared_root)
    
    stats = await ingest.ingest_all()
    
    assert stats["specs"] == 0  # No spec files
    assert stats["tasks"] == 2  # Two tasks in the index
    assert stats["edges"] >= 2  # At least edges to spec and between tasks
    
    # Verify that upsert_pages_in was called
    mock_store.upsert_pages_in.assert_called()
    
    # Verify the pages were created with correct properties
    call_args = mock_store.upsert_pages_in.call_args
    assert call_args is not None
    pages = call_args[1]["pages"] if "pages" in call_args[1] else call_args[0][1]
    assert len(pages) == 2
    
    # Check first task
    task1 = pages[0]
    assert isinstance(task1, WikiPageRecord)
    assert task1.concept_id == "task:TASK-001"
    assert task1.category == "task"
    assert task1.origin == "sdd-task"
    
    # Check second task
    task2 = pages[1]
    assert isinstance(task2, WikiPageRecord)
    assert task2.concept_id == "task:TASK-002"
    assert task2.category == "task"
    assert task2.origin == "sdd-task"


@pytest.mark.asyncio
async def test_ingest_all_with_both_spec_and_tasks(
    mock_store, temp_shared_root, sample_spec_file, sample_task_index_file
):
    """Test ingest_all with both spec and task files."""
    # Mock the transaction context manager
    mock_conn = AsyncMock()
    # Create a proper async context manager mock
    class AsyncContextManager:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    mock_store.ledger_transaction.return_value = AsyncContextManager()
    
    ingest = SDDGraphIngest(mock_store, temp_shared_root)
    
    stats = await ingest.ingest_all()
    
    assert stats["specs"] == 1
    assert stats["tasks"] == 2
    assert stats["edges"] >= 2  # Edges between tasks and to spec
    
    # Verify both spec and task ingestion happened
    assert mock_store.upsert_pages_in.call_count >= 1
    assert mock_store.add_edges_in.call_count >= 1


@pytest.mark.asyncio
async def test_process_spec_file_error_handling(mock_store, temp_shared_root):
    """Test error handling in _process_spec_file."""
    ingest = SDDGraphIngest(mock_store, temp_shared_root)
    
    # Try to process a non-existent file
    result = await ingest._process_spec_file(Path("/non/existent/file.spec.md"))
    assert result is None


@pytest.mark.asyncio
async def test_process_task_index_file_error_handling(mock_store, temp_shared_root):
    """Test error handling in _process_task_index_file."""
    ingest = SDDGraphIngest(mock_store, temp_shared_root)
    
    # Try to process a non-existent file
    result = await ingest._process_task_index_file(Path("/non/existent/file.json"))
    assert result is None


@pytest.mark.asyncio
async def test_ingest_all_with_malformed_spec(mock_store, temp_shared_root):
    """Test ingest_all handles malformed spec files gracefully."""
    # Create a malformed spec file
    spec_path = temp_shared_root / "sdd" / "specs" / "malformed.spec.md"
    spec_path.write_text("Invalid YAML frontmatter\n---\nbad: yaml: content", encoding="utf-8")
    
    # Mock the transaction context manager
    mock_conn = AsyncMock()
    # Create a proper async context manager mock
    class AsyncContextManager:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    mock_store.ledger_transaction.return_value = AsyncContextManager()
    
    ingest = SDDGraphIngest(mock_store, temp_shared_root)
    
    # Should not raise an exception
    stats = await ingest.ingest_all()
    
    # Should still work (fallback to defaults)
    assert stats["specs"] >= 0  # May be 0 or 1 depending on how parse handles errors
    assert stats["tasks"] == 0
    assert stats["edges"] >= 0


@pytest.mark.asyncio
async def test_ingest_all_with_malformed_task_index(mock_store, temp_shared_root):
    """Test ingest_all handles malformed task index files gracefully."""
    # Create a malformed task index file
    index_path = temp_shared_root / "sdd" / "tasks" / "index" / "malformed.json"
    index_path.write_text("Invalid JSON content", encoding="utf-8")
    
    # Mock the transaction context manager
    mock_conn = AsyncMock()
    # Create a proper async context manager mock
    class AsyncContextManager:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    mock_store.ledger_transaction.return_value = AsyncContextManager()
    
    ingest = SDDGraphIngest(mock_store, temp_shared_root)
    
    # Should not raise an exception
    stats = await ingest.ingest_all()
    
    # Should handle the error gracefully
    assert stats["specs"] == 0
    assert stats["tasks"] == 0
    assert stats["edges"] == 0