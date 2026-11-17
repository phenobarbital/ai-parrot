"""FEAT-902 cancelled append ownership and durable recovery."""

import asyncio
import multiprocessing
import threading
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.store import SQLitePragmaPolicy


def _opened_event(issue_id: str) -> LedgerEvent:
    """Build a deterministic issue-opened event for isolated recovery tests."""
    return LedgerEvent(
        kind="issue.opened",
        subject=issue_id,
        actor="agent:test",
        ts="2026-11-16T00:00:00+00:00",
        payload={
            "title": "Cancellation coverage",
            "body": "Disposable test state.",
            "kind": "bug",
            "severity": "minor",
            "discovered_from": "test:TASK-5715",
            "about": [],
        },
    )


def _probe_writer(db_path: str, completed: Any, acquired: Any) -> None:
    """Attempt a distinct-process immediate transaction and report whether it entered."""
    import sqlite3

    connection = None
    try:
        connection = sqlite3.connect(db_path, isolation_level=None, timeout=0.2)
        connection.execute("BEGIN IMMEDIATE")
        acquired.value = 1
        connection.execute("ROLLBACK")
    except sqlite3.OperationalError:
        acquired.value = 0
    finally:
        if connection is not None:
            connection.close()
        completed.set()


def _append_then_pause_before_commit(ledger_dir: str, issue_id: str, durable: Any, release: Any) -> None:
    """Fsync a child append while a real SQLite transaction remains uncommitted."""
    import sqlite3

    connection = sqlite3.connect(str(Path(ledger_dir) / "ledger.db"), isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        LedgerLog(str(Path(ledger_dir) / "events.jsonl")).append(
            LedgerEvent(
                kind="issue.claimed",
                subject=issue_id,
                actor="agent:child",
                ts="2026-11-16T00:00:01+00:00",
                payload={"claimed_by": "agent:child"},
            )
        )
        durable.set()
        release.wait(60)
        connection.execute("COMMIT")
    finally:
        connection.close()


@pytest.fixture
def service(tmp_path: Path) -> LedgerService:
    """Construct temporary WAL/log state with a bounded peer timeout."""
    return LedgerService.from_dir(tmp_path / "ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1))


async def _open_issue(service: LedgerService, title: str = "Cancellation coverage") -> str:
    """Create one disposable open issue through the public service API."""
    return await service.open_issue(
        title,
        "Disposable test state.",
        discovered_from="test:TASK-5715",
        about=[],
        actor="agent:test",
    )


@pytest.mark.asyncio
async def test_cancel_keeps_writer_until_append_settles(
    service: LedgerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated cancellation cannot let a peer enter during gated append/fsync."""
    issue_id = await _open_issue(service)
    append_started = threading.Event()
    release_append = threading.Event()
    append = service.log.append

    def gated_append(event: LedgerEvent) -> tuple[str, int]:
        append_started.set()
        if not release_append.wait(10):
            raise TimeoutError("test did not release gated append")
        return append(event)

    monkeypatch.setattr(service.log, "append", gated_append)
    mutation = asyncio.create_task(service.index.claim_issue(issue_id, "agent:cancelled"))
    peer = None
    try:
        assert await asyncio.to_thread(append_started.wait, 5)
        mutation.cancel()
        mutation.cancel()

        context = multiprocessing.get_context("spawn")
        completed = context.Event()
        acquired = context.Value("i", -1)
        peer = context.Process(
            target=_probe_writer,
            args=(str(Path(service.log.path).with_name("ledger.db")), completed, acquired),
        )
        peer.start()
        assert await asyncio.to_thread(completed.wait, 5)
        assert acquired.value == 0
    finally:
        release_append.set()
        if peer is not None:
            await asyncio.to_thread(peer.join, 10)
            if peer.is_alive():
                peer.terminate()
                await asyncio.to_thread(peer.join, 10)

    with pytest.raises(asyncio.CancelledError):
        await mutation
    assert peer is not None
    assert peer.exitcode == 0
    assert await service.index.sync() == 1
    assert (await service.get_issue(issue_id))["status"] == "claimed"


@pytest.mark.asyncio
async def test_cancel_and_append_failure_preserve_both(service: LedgerService, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancellation wins while the append error remains diagnosable."""
    issue_id = await _open_issue(service)
    append_started = threading.Event()
    release_append = threading.Event()

    def failing_append(event: LedgerEvent) -> tuple[str, int]:
        append_started.set()
        if not release_append.wait(10):
            raise TimeoutError("test did not release failing append")
        raise OSError("append failed after cancellation")

    monkeypatch.setattr(service.log, "append", failing_append)
    mutation = asyncio.create_task(service.index.claim_issue(issue_id, "agent:cancelled"))
    try:
        assert await asyncio.to_thread(append_started.wait, 5)
        mutation.cancel()
        mutation.cancel()
    finally:
        release_append.set()

    with pytest.raises(asyncio.CancelledError) as cancellation:
        await mutation
    assert isinstance(cancellation.value.__cause__, OSError)
    assert [event.kind for event, _offset in service.log.iter_events()] == ["issue.opened"]


@pytest.mark.asyncio
async def test_cancel_before_dispatch_appends_nothing(service: LedgerService, monkeypatch: pytest.MonkeyPatch) -> None:
    """A mutation cancelled before it starts dispatches no append work."""
    issue_id = await _open_issue(service)
    append_calls: list[LedgerEvent] = []

    def record_append(event: LedgerEvent) -> tuple[str, int]:
        append_calls.append(event)
        raise AssertionError("cancelled mutation dispatched an append")

    monkeypatch.setattr(service.log, "append", record_append)
    mutation = asyncio.create_task(service.index.claim_issue(issue_id, "agent:cancelled"))
    mutation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await mutation
    assert append_calls == []
    assert [event.kind for event, _offset in service.log.iter_events()] == ["issue.opened"]


@pytest.mark.asyncio
async def test_guarded_mutations_use_durable_append_and_retain_normal_semantics(
    service: LedgerService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claim, unclaim, and close retain their successful append/replay behavior."""
    issue_id = await _open_issue(service)
    calls: list[str] = []
    append_durably = service.index._append_durably

    async def record_append(event: LedgerEvent) -> tuple[str, int]:
        calls.append(event.kind)
        return await append_durably(event)

    monkeypatch.setattr(service.index, "_append_durably", record_append)
    assert await service.claim(issue_id, "agent:owner")
    assert await service.unclaim(issue_id, "released", "agent:owner")
    assert await service.claim(issue_id, "agent:owner")
    assert await service.close_issue(issue_id, "done", "agent:owner")
    assert calls == ["issue.claimed", "issue.unclaimed", "issue.claimed", "issue.closed"]
    assert (await service.get_issue(issue_id))["status"] == "closed"


@pytest.mark.asyncio
async def test_uncancelled_append_error_propagates(service: LedgerService, monkeypatch: pytest.MonkeyPatch) -> None:
    """An ordinary append failure keeps its existing error semantics."""

    def failing_append(event: LedgerEvent) -> tuple[str, int]:
        raise OSError("ordinary append failure")

    monkeypatch.setattr(service.log, "append", failing_append)
    event = LedgerEvent(
        kind="issue.claimed",
        subject="issue:failure",
        actor="agent:test",
        payload={"claimed_by": "agent:test"},
    )
    with pytest.raises(OSError, match="ordinary append failure"):
        await service.index._append_durably(event)


def test_process_death_after_fsync_recovers(tmp_path: Path) -> None:
    """A real child dying before SQL commit leaves a replayable durable event."""
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    issue_id = "issue:000000000001"
    LedgerLog(str(ledger_dir / "events.jsonl")).append(_opened_event(issue_id))

    context = multiprocessing.get_context("spawn")
    durable = context.Event()
    release = context.Event()
    child = context.Process(
        target=_append_then_pause_before_commit,
        args=(str(ledger_dir), issue_id, durable, release),
    )
    child.start()
    try:
        assert durable.wait(10)
        child.terminate()
        child.join(10)
    finally:
        if child.is_alive():
            child.terminate()
            child.join(10)

    assert child.exitcode not in (None, 0)

    async def recover() -> None:
        service = LedgerService.from_dir(ledger_dir, sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1))
        assert await service.index.sync() == 2
        before_rebuild = await service.get_issue(issue_id)
        assert before_rebuild is not None
        assert before_rebuild["status"] == "claimed"
        assert await service.index.sync() == 0
        assert await service.index.rebuild() == 2
        assert await service.get_issue(issue_id) == before_rebuild

    asyncio.run(recover())
