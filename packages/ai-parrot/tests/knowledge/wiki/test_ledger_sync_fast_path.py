"""FEAT-902 no-op sync, probe races and service-level concurrency."""

import asyncio
import multiprocessing
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.store import SQLitePragmaPolicy


def _event(number: int) -> LedgerEvent:
    """Create a deterministic, valid issue-opened event."""
    return LedgerEvent(
        kind="issue.opened",
        subject=f"issue:{number:012d}",
        actor="agent:test",
        ts=f"2026-01-01T00:00:{number:02d}+00:00",
        payload={
            "title": f"Issue {number}",
            "body": f"Body {number}",
            "kind": "bug",
            "severity": "minor",
            "discovered_from": "test:TASK-5714",
            "about": [],
        },
    )


def _hold_ledger_writer(db_path: str, ready: Any, release: Any, status: Any) -> None:
    """Hold the ledger writer in a spawned peer process until released."""
    import sqlite3

    try:
        connection = sqlite3.connect(db_path, isolation_level=None, timeout=1)
        connection.execute("BEGIN IMMEDIATE")
        status.value = 1
        ready.set()
        release.wait(60)
        connection.execute("ROLLBACK")
    except BaseException:
        status.value = 2
        ready.set()
        raise
    finally:
        if "connection" in locals():
            connection.close()


@pytest.fixture
def service(tmp_path: Path) -> LedgerService:
    """Use a disposable service, never the repository's real ledger."""
    return LedgerService.from_dir(tmp_path / "ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1))


@pytest.mark.asyncio
async def test_caught_up_reads_do_not_take_writer(service: LedgerService, monkeypatch: pytest.MonkeyPatch) -> None:
    """get/list/ready complete while a spawned peer holds BEGIN IMMEDIATE."""
    event = _event(1)
    await asyncio.to_thread(service.log.append, event)
    assert await service.index.sync() == 1

    @asynccontextmanager
    async def forbid_writer(operation: str):
        raise AssertionError(f"unexpected writer transaction: {operation}")
        yield

    monkeypatch.setattr(service.store, "ledger_transaction", forbid_writer)
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    status = context.Value("i", 0)
    peer = context.Process(
        target=_hold_ledger_writer,
        args=(str(Path(service.log.path).with_name("ledger.db")), ready, release, status),
    )
    peer.start()
    try:
        assert await asyncio.to_thread(ready.wait, 10)
        assert status.value == 1
        assert (await service.get_issue(event.subject))["issue_id"] == event.subject
        assert [row["issue_id"] for row in await service.list_issues()] == [event.subject]
        assert [row["issue_id"] for row in await service.ready_work()] == [event.subject]
    finally:
        release.set()
        await asyncio.to_thread(peer.join, 10)
        if peer.is_alive():
            peer.terminate()
            await asyncio.to_thread(peer.join, 10)
    assert peer.exitcode == 0


def test_probe_cursor_race_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replacement, truncation, malformed anchors and suffixes fail conservatively."""
    path = tmp_path / "events.jsonl"
    log = LedgerLog(str(path))
    first = _event(1)
    second = _event(2)
    offset = log.append(first)[1]

    read_sizes: list[int] = []
    raw_read = os.read

    def recording_read(fd: int, size: int) -> bytes:
        read_sizes.append(size)
        return raw_read(fd, size)

    monkeypatch.setattr(os, "read", recording_read)
    assert log.probe_cursor(offset, first.event_id) == "current"
    assert read_sizes == [4097, 1]

    log.append(second)
    assert log.probe_cursor(offset, first.event_id) == "replay"
    assert log.probe_cursor(offset, "not-the-event-id") == "uncertain"

    replacement = tmp_path / "replacement.jsonl"
    replacement.write_bytes(path.read_bytes())
    original_read = raw_read
    replaced = False

    def replace_after_read(fd: int, size: int) -> bytes:
        nonlocal replaced
        value = original_read(fd, size)
        if not replaced:
            os.replace(replacement, path)
            replaced = True
        return value

    monkeypatch.setattr(os, "read", replace_after_read)
    assert log.probe_cursor(offset, first.event_id) == "uncertain"

    path.write_bytes(b'{"event_id":"partial"')
    assert log.probe_cursor(0, first.event_id) == "uncertain"

    empty = LedgerLog(str(tmp_path / "empty.jsonl"))
    assert empty.probe_cursor(0, None) == "current"
    Path(empty.path).touch()
    assert empty.probe_cursor(0, None) == "current"


@pytest.mark.asyncio
async def test_pending_replay_revalidates_under_lock(service: LedgerService, monkeypatch: pytest.MonkeyPatch) -> None:
    """C1/C2 changes and append races use transactional replay without skips."""
    first = _event(1)
    second = _event(2)
    third = _event(3)
    await asyncio.to_thread(service.log.append, first)
    assert await service.index.sync() == 1
    await asyncio.to_thread(service.log.append, second)

    original_transaction = service.store.ledger_transaction
    transaction_count = 0

    @asynccontextmanager
    async def append_before_sync(operation: str):
        nonlocal transaction_count
        transaction_count += 1
        if operation == "ledger.sync":
            await asyncio.to_thread(service.log.append, third)
        async with original_transaction(operation) as conn:
            yield conn

    monkeypatch.setattr(service.store, "ledger_transaction", append_before_sync)
    assert await service.index.sync() == 2
    assert transaction_count == 1
    assert {row["issue_id"] for row in await service.list_issues()} == {
        first.subject,
        second.subject,
        third.subject,
    }
