"""Tests for ReceivedLedger."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from parrot.interagent import CallCost
from parrot.squawk.client.received_ledger import ReceivedLedger, ReceivedLedgerEntry


@pytest.fixture
def cost():
    return CallCost(
        tokens_in=100,
        tokens_out=200,
        duration_ms=500,
        rows=None,
        bytes=None,
        cost_usd=0.001,
    )


@pytest.fixture
def sample_entry(cost):
    return ReceivedLedgerEntry(
        remote_agent="test-agent",
        cap_id="test.category.action",
        contract_hash="abc123",
        handle_key="handle-key-1",
        descriptor_digest="digest-123",
        cost=cost,
        trace_id="test-trace-id",
    )


@pytest.mark.asyncio
async def test_received_ledger_append(sample_entry):
    """Test that entries can be appended to the ledger."""
    ledger = ReceivedLedger()
    
    await ledger.append(sample_entry)
    
    entries = ledger.recent()
    assert len(entries) == 1
    assert entries[0] == sample_entry


@pytest.mark.asyncio
async def test_received_ledger_recent_limit():
    """Test that recent() respects the limit parameter."""
    ledger = ReceivedLedger()
    
    # Add more entries than the default limit
    for i in range(150):
        entry = ReceivedLedgerEntry(
            remote_agent="test-agent",
            cap_id=f"test.category.action{i}",
            contract_hash="abc123",
            handle_key=f"handle-key-{i}",
            descriptor_digest=f"digest-{i}",
            cost=CallCost(duration_ms=100),
            trace_id=f"test-trace-id-{i}",
        )
        await ledger.append(entry)
    
    # Default limit is 100
    entries = ledger.recent()
    assert len(entries) == 100
    
    # Test with custom limit
    entries = ledger.recent(limit=10)
    assert len(entries) == 10
    
    # Most recent entries should be last
    assert entries[-1].cap_id == "test.category.action149"


def test_received_ledger_max_entries():
    """Test that the ledger respects max_entries limit."""
    ledger = ReceivedLedger(max_entries=3)
    
    # Add more entries than max_entries
    for i in range(5):
        entry = ReceivedLedgerEntry(
            remote_agent="test-agent",
            cap_id=f"test.category.action{i}",
            contract_hash="abc123",
            handle_key=f"handle-key-{i}",
            descriptor_digest=f"digest-{i}",
            cost=CallCost(duration_ms=100),
            trace_id=f"test-trace-id-{i}",
        )
        ledger._recent.append(entry)  # Directly append to bypass async for this test
    
    entries = ledger.recent()
    assert len(entries) == 3
    # Should have the most recent entries (2, 3, 4)
    assert entries[0].cap_id == "test.category.action2"
    assert entries[1].cap_id == "test.category.action3"
    assert entries[2].cap_id == "test.category.action4"


@pytest.mark.asyncio
async def test_received_ledger_note_follow_up(sample_entry):
    """Test that note_follow_up adds follow-ups to the correct entry."""
    ledger = ReceivedLedger()
    
    # Add an entry
    await ledger.append(sample_entry)
    
    # Add a follow-up
    ledger.note_follow_up("handle-key-1", "test_tool")
    
    # Check that the entry was updated
    entries = ledger.recent()
    assert len(entries) == 1
    assert entries[0].follow_ups == ("test_tool",)


@pytest.mark.asyncio
async def test_received_ledger_note_follow_up_multiple(sample_entry):
    """Test that note_follow_up can add multiple follow-ups to the same entry."""
    ledger = ReceivedLedger()
    
    # Add an entry
    await ledger.append(sample_entry)
    
    # Add multiple follow-ups
    ledger.note_follow_up("handle-key-1", "tool1")
    ledger.note_follow_up("handle-key-1", "tool2")
    
    # Check that both follow-ups were added
    entries = ledger.recent()
    assert len(entries) == 1
    assert entries[0].follow_ups == ("tool1", "tool2")


@pytest.mark.asyncio
async def test_received_ledger_note_follow_up_latest_only():
    """Test that note_follow_up only affects the latest entry with the handle_key."""
    ledger = ReceivedLedger()
    
    # Add two entries with the same handle_key
    entry1 = ReceivedLedgerEntry(
        remote_agent="test-agent-1",
        cap_id="test.category.action1",
        contract_hash="abc123",
        handle_key="same-handle",
        descriptor_digest="digest-1",
        cost=CallCost(duration_ms=100),
        trace_id="test-trace-id-1",
    )
    
    entry2 = ReceivedLedgerEntry(
        remote_agent="test-agent-2",
        cap_id="test.category.action2",
        contract_hash="def456",
        handle_key="same-handle",
        descriptor_digest="digest-2",
        cost=CallCost(duration_ms=200),
        trace_id="test-trace-id-2",
    )
    
    await ledger.append(entry1)
    await ledger.append(entry2)
    
    # Add a follow-up - should only affect the latest entry (entry2)
    ledger.note_follow_up("same-handle", "test_tool")
    
    entries = ledger.recent()
    assert len(entries) == 2
    # First entry should be unchanged
    assert entries[0].follow_ups == ()
    # Second entry should have the follow-up
    assert entries[1].follow_ups == ("test_tool",)


def test_received_ledger_note_follow_up_no_matching_handle():
    """Test that note_follow_up does nothing when no entry has the handle_key."""
    ledger = ReceivedLedger()
    
    # Try to add a follow-up for a non-existent handle
    ledger.note_follow_up("non-existent-handle", "test_tool")
    
    # Should not raise and should have no entries
    entries = ledger.recent()
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_received_ledger_sink_called(sample_entry):
    """Test that the sink is called when provided."""
    mock_sink = AsyncMock()
    ledger = ReceivedLedger(sink=mock_sink)
    
    await ledger.append(sample_entry)
    
    # Sink should have been called
    mock_sink.assert_called_once()


@pytest.mark.asyncio
async def test_received_ledger_sink_failure(caplog):
    """Test that sink failures are handled gracefully."""
    failing_sink = AsyncMock()
    failing_sink.side_effect = RuntimeError("Sink failure")
    
    ledger = ReceivedLedger(sink=failing_sink)
    
    # Should not raise despite sink failure
    await ledger.append(sample_entry)
    
    # Should log the exception
    assert "ReceivedLedger: sink failed" in caplog.text


@pytest.mark.asyncio
async def test_received_ledger_no_sink():
    """Test that the ledger works without a sink."""
    ledger = ReceivedLedger(sink=None)  # Explicitly None
    
    entry = ReceivedLedgerEntry(
        remote_agent="test-agent",
        cap_id="test.category.action",
        contract_hash="abc123",
        handle_key="handle-key-1",
        descriptor_digest="digest-123",
        cost=CallCost(duration_ms=100),
        trace_id="test-trace-id",
    )
    
    # Should not raise
    await ledger.append(entry)
    
    entries = ledger.recent()
    assert len(entries) == 1
    assert entries[0] == entry