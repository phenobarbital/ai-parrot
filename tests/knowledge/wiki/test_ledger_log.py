import os
import multiprocessing
import pytest
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog


def _worker_append(args) -> None:
    """Worker function for multiprocessing append test."""
    path, event_data, barrier = args
    # Wait for all processes to be ready
    barrier.wait()
    
    # Append the event
    log = LedgerLog(path)
    event = LedgerEvent(**event_data)
    log.append(event)


def test_ledger_log_basic_append_and_iter(tmp_path):
    log_path = str(tmp_path / "events.jsonl")
    log = LedgerLog(log_path)

    event1 = LedgerEvent(
        kind="issue.opened",
        subject="issue:1234567890ab",
        actor="agent:codex",
        payload={"title": "Test Issue 1", "body": "Body 1"},
    )
    event2 = LedgerEvent(
        kind="issue.closed",
        subject="issue:1234567890ab",
        actor="human:jesus",
        payload={"reason": "fixed", "closed_by": "human:jesus"},
    )

    # Append event 1
    eid1, offset1 = log.append(event1)
    assert eid1 == event1.event_id
    assert offset1 == 0

    # Append event 2
    eid2, offset2 = log.append(event2)
    assert eid2 == event2.event_id
    assert offset2 > 0

    # Read them back
    events = list(log.iter_events())
    assert len(events) == 2
    assert events[0][0].event_id == event1.event_id
    assert events[0][1] == offset1
    assert events[1][0].event_id == event2.event_id
    assert events[1][1] == offset2

    # Read from offset2
    events_from_offset = list(log.iter_events(from_offset=offset2))
    assert len(events_from_offset) == 1
    assert events_from_offset[0][0].event_id == event2.event_id
    assert events_from_offset[0][1] == offset2


def test_ledger_log_oversized_rejection(tmp_path):
    log_path = str(tmp_path / "events.jsonl")
    log = LedgerLog(log_path)

    # Create an event with a very large payload to exceed 4 KiB
    large_payload = {"data": "x" * 4096}
    event = LedgerEvent(
        kind="issue.opened",
        subject="issue:1234567890ab",
        actor="agent:codex",
        payload=large_payload,
    )

    with pytest.raises(ValueError, match="exceeds the 4 KiB limit"):
        log.append(event)

    # Verify file is empty or doesn't exist
    if os.path.exists(log_path):
        assert os.path.getsize(log_path) == 0


def test_ledger_log_corruption_handling(tmp_path):
    log_path = str(tmp_path / "events.jsonl")
    log = LedgerLog(log_path)

    event1 = LedgerEvent(
        kind="issue.opened",
        subject="issue:1234567890ab",
        actor="agent:codex",
        payload={"title": "Test Issue 1"},
    )
    log.append(event1)

    # Write some corrupted/malformed line manually
    with open(log_path, "a") as f:
        f.write("this is not valid json\n")

    event2 = LedgerEvent(
        kind="issue.closed",
        subject="issue:1234567890ab",
        actor="human:jesus",
        payload={"reason": "fixed", "closed_by": "human:jesus"},
    )
    log.append(event2)

    # Iterating should skip the malformed line and log a warning, yielding event1 and event2
    events = list(log.iter_events())
    assert len(events) == 2
    assert events[0][0].event_id == event1.event_id
    assert events[1][0].event_id == event2.event_id


def test_ledger_log_multiprocess_append(tmp_path):
    log_path = str(tmp_path / "events.jsonl")
    
    # We will spawn 8 processes to append simultaneously
    num_processes = 8
    manager = multiprocessing.Manager()
    barrier = manager.Barrier(num_processes)

    events_data = [
        {
            "kind": "issue.opened",
            "subject": f"issue:proc_{i}",
            "actor": f"agent:proc_{i}",
            "payload": {"index": i, "padding": "y" * 100},
        }
        for i in range(num_processes)
    ]

    args = [(log_path, data, barrier) for data in events_data]

    with multiprocessing.Pool(processes=num_processes) as pool:
        pool.map(_worker_append, args)

    # Read back and verify all 8 events are present and none are interleaved/corrupted
    log = LedgerLog(log_path)
    events = list(log.iter_events())
    assert len(events) == num_processes

    subjects = {evt.subject for evt, _ in events}
    assert len(subjects) == num_processes
    for i in range(num_processes):
        assert f"issue:proc_{i}" in subjects
