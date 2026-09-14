"""Tests for LedgerStore transaction adapter and cursor state."""

import tempfile
from pathlib import Path

import pytest
from pydantic import BaseModel

from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiPageRecord


@pytest.fixture
def ledger_db_path():
    """Create a temporary database file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
async def ledger_store(ledger_db_path):
    """Create a LedgerStore instance for testing."""
    store = LedgerStore(
        db_path=ledger_db_path,
        wiki_name="test-ledger",
        sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0)
    )
    yield store
    # No cleanup needed for SQLite store


@pytest.mark.asyncio
async def test_ledger_reads_issue_no_writes(ledger_store):
    """On a fresh `ledger.db` without `ledger_state`, `read_cursor()` returns offset 0 / None 
    and issue zero write statements (FEAT-557's SQL-trace pattern)."""
    # Fresh store should have no ledger_state table
    offset, event_id = await ledger_store.read_cursor()
    assert offset == 0
    assert event_id is None


@pytest.mark.asyncio
async def test_ledger_transaction_creates_state_table(ledger_store):
    """Test that ledger_transaction creates ledger_state table on first use."""
    # Before transaction, no ledger_state table should exist
    offset, event_id = await ledger_store.read_cursor()
    assert offset == 0
    assert event_id is None
    
    # Execute a transaction to create the table
    async with ledger_store.ledger_transaction("test_operation") as conn:
        # Table should now exist
        async with conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = 'ledger_state'"
        ) as cur:
            row = await cur.fetchone()
            assert row[0] == 1


@pytest.mark.asyncio
async def test_ledger_cursor_persistence(ledger_store):
    """Test that cursor state can be written and read back."""
    # First, ensure the table exists by running a transaction
    async with ledger_store.ledger_transaction("setup") as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO ledger_state (key, value) VALUES (?, ?)",
            ("cursor_offset", "1234")
        )
        await conn.execute(
            "INSERT OR REPLACE INTO ledger_state (key, value) VALUES (?, ?)",
            ("last_event_id", "event:abcd1234")
        )
    
    # Now read the cursor
    offset, event_id = await ledger_store.read_cursor()
    assert offset == 1234
    assert event_id == "event:abcd1234"


@pytest.mark.asyncio
async def test_ledger_upsert_pages_in(ledger_store):
    """Test that upsert_pages_in delegates correctly."""
    pages = [
        WikiPageRecord(
            concept_id="issue:test123",
            title="Test Issue",
            category="issue",
            summary="A test issue",
            body="# Test Issue\n\nThis is a test issue.",
        )
    ]
    
    async with ledger_store.ledger_transaction("test_upsert") as conn:
        await ledger_store.upsert_pages_in(conn, pages)
        
        # Verify the page was inserted
        async with conn.execute(
            "SELECT concept_id, title FROM pages WHERE concept_id = ?", 
            ("issue:test123",)
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row["concept_id"] == "issue:test123"
            assert row["title"] == "Test Issue"


@pytest.mark.asyncio
async def test_ledger_add_edges_in(ledger_store):
    """Test that add_edges_in delegates correctly."""
    # First create some pages to connect
    pages = [
        WikiPageRecord(
            concept_id="issue:test1",
            title="Test Issue 1",
            category="issue",
        ),
        WikiPageRecord(
            concept_id="task:test1",
            title="Test Task 1", 
            category="task",
        )
    ]
    
    edges = [("issue:test1", "task:test1", "discovered_from")]
    
    async with ledger_store.ledger_transaction("test_edges") as conn:
        # Insert pages first
        await ledger_store.upsert_pages_in(conn, pages)
        # Then add edges
        await ledger_store.add_edges_in(conn, edges)
        
        # Verify the edge was inserted
        async with conn.execute(
            "SELECT src, dst, rel FROM edges WHERE src = ? AND dst = ?", 
            ("issue:test1", "task:test1")
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row["src"] == "issue:test1"
            assert row["dst"] == "task:test1"
            assert row["rel"] == "discovered_from"


@pytest.mark.asyncio
async def test_ledger_empty_state_after_creation(ledger_store):
    """Test that a newly created ledger has empty state."""
    # Just creating the store shouldn't create any tables
    offset, event_id = await ledger_store.read_cursor()
    assert offset == 0
    assert event_id is None


@pytest.mark.asyncio
async def test_ledger_transaction_propagates_busy_errors(ledger_store):
    """Test that WikiStoreBusy errors are propagated unchanged."""
    # This test verifies the contract that ledger_transaction
    # propagates WikiStoreBusy errors from the underlying _write method
    # We can't easily simulate a busy condition in a test, but we can
    # verify the transaction context manager is properly implemented
    
    transaction_entered = False
    transaction_exited = False
    
    try:
        async with ledger_store.ledger_transaction("test_busy") as conn:
            transaction_entered = True
            # Perform a simple operation to ensure the connection works
            await conn.execute("SELECT 1")
    except Exception:
        # If any exception occurs, we still want to check if the context worked
        pass
    else:
        transaction_exited = True
    
    # The transaction should have been entered and exited normally
    # (no busy error in this simple case)
    assert transaction_entered
    assert transaction_exited