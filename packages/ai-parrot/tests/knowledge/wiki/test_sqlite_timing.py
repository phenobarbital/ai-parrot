"""FEAT-902 timing records preserve SQLite and ledger semantics."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, SQLiteWikiStore, WikiPageRecord, WikiStoreBusy


def _opened_event(number: int, body: str = "Timing test body.") -> LedgerEvent:
    """Build one valid, deterministic ledger event."""
    return LedgerEvent(
        kind="issue.opened",
        subject=f"issue:{number:012d}",
        actor="agent:timing-test",
        ts=f"2026-11-16T00:00:{number:02d}+00:00",
        payload={
            "title": f"Timing event {number}",
            "body": body,
            "kind": "bug",
            "severity": "minor",
            "discovered_from": "test:TASK-5716",
            "about": [],
        },
    )


@pytest.mark.asyncio
async def test_phase_records_and_counts(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Connection, transaction, probe, replay and fsync observations are attributable."""
    caplog.set_level(logging.DEBUG)
    policy = SQLitePragmaPolicy(busy_timeout_s=1)
    store = SQLiteWikiStore(tmp_path / "wiki.db", sqlite_policy=policy)
    service = LedgerService.from_dir(tmp_path / "ledger", sqlite_policy=policy)

    assert (
        await store.upsert_pages([WikiPageRecord(concept_id="file:timing.md", title="Timing", body="phase test")]) == 1
    )
    await asyncio.to_thread(service.log.append, _opened_event(1))
    assert await service.index.sync() == 1
    assert await service.index.sync() == 0
    await asyncio.to_thread(service.log.append_line, _opened_event(2).model_dump_json())
    assert await service.index.sync() == 1

    records = [record for record in caplog.records if getattr(record, "event", None) == "wiki.sqlite.timing"]
    phases = {record.phase for record in records}
    assert {
        "connection_open",
        "connection_setup",
        "begin_wait",
        "transaction_body",
        "commit",
        "log_append",
        "log_fsync",
        "sync_probe",
        "replay",
    } <= phases
    for record in records:
        assert isinstance(record.operation, str)
        assert record.outcome in {"success", "error", "cancelled"}
        assert record.duration_ms >= 0
        assert record.pid > 0
        assert record.db_name in {"wiki.db", "ledger.db"}

    probe_records = [record for record in records if record.phase == "sync_probe"]
    assert any(record.fast_path is False for record in probe_records)
    assert any(record.fast_path is True for record in probe_records)
    replay_records = [record for record in records if record.phase == "replay" and record.outcome == "success"]
    assert [record.applied_events for record in replay_records] == [1, 1]


class _RaisingHandler(logging.Handler):
    """A logger handler that simulates a telemetry destination failure."""

    def emit(self, record: logging.LogRecord) -> None:
        """Raise after a timing record reaches the handler."""
        raise RuntimeError("telemetry sink unavailable")


@pytest.mark.asyncio
async def test_telemetry_failure_does_not_change_storage(tmp_path: Path) -> None:
    """A throwing logging handler cannot change a commit/error/cancel outcome."""
    store = SQLiteWikiStore(tmp_path / "wiki.db", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1))
    timing_logger = logging.getLogger("parrot.knowledge.wiki.store")
    handler = _RaisingHandler()
    previous_level = timing_logger.level
    timing_logger.setLevel(logging.DEBUG)
    timing_logger.addHandler(handler)
    try:
        committed = WikiPageRecord(concept_id="file:committed.md", title="Committed", body="saved")
        assert await store.upsert_pages([committed]) == 1
        assert [page["concept_id"] for page in await store.list_pages()] == [committed.concept_id]

        rolled_back = WikiPageRecord(concept_id="file:rolled-back.md", title="Rolled back", body="discarded")
        with pytest.raises(RuntimeError, match="body failure"):
            async with store._write("body_failure") as conn:
                await store._upsert_pages_conn(conn, [rolled_back])
                raise RuntimeError("body failure")
        assert [page["concept_id"] for page in await store.list_pages()] == [committed.concept_id]

        peer = sqlite3.connect(str(store.db_path), timeout=1, isolation_level=None)
        try:
            peer.execute("BEGIN IMMEDIATE")
            with pytest.raises(WikiStoreBusy):
                await store.upsert_pages([WikiPageRecord(concept_id="file:busy.md", title="Busy", body="not saved")])
        finally:
            peer.execute("ROLLBACK")
            peer.close()

        entered = asyncio.Event()

        async def cancelled_write() -> None:
            """Hold a transaction body until cancellation reaches it."""
            async with store._write("cancelled_write"):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(cancelled_write())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (
            await store.upsert_pages([WikiPageRecord(concept_id="file:after-cancel.md", title="After", body="saved")])
            == 1
        )
    finally:
        timing_logger.removeHandler(handler)
        timing_logger.setLevel(previous_level)


@pytest.mark.asyncio
async def test_payload_free_timings_and_readonly_fts(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Timing output excludes sensitive fields and preserves wiki FTS/read-only behavior."""
    caplog.set_level(logging.DEBUG)
    policy = SQLitePragmaPolicy(busy_timeout_s=1)
    payload = "PRIVATE-TIMING-PAYLOAD"
    store_path = tmp_path / "private" / "wiki.db"
    store = SQLiteWikiStore(store_path, sqlite_policy=policy)
    await store.upsert_pages(
        [WikiPageRecord(concept_id="file:private.md", title="Private timing", body=f"FTS {payload}")]
    )
    assert [row["concept_id"] for row in await store.search_fts("PRIVATE-TIMING-PAYLOAD")] == ["file:private.md"]

    read_only = SQLiteWikiStore(store_path, read_only=True, sqlite_policy=policy)
    assert [row["concept_id"] for row in await read_only.search_fts("PRIVATE-TIMING-PAYLOAD")] == ["file:private.md"]

    log = LedgerLog(str(tmp_path / "private" / "events.jsonl"))
    await asyncio.to_thread(log.append_line, _opened_event(3, payload).model_dump_json())
    rendered_records = "\n".join(str(record.__dict__) for record in caplog.records)
    assert payload not in rendered_records
    assert str(store_path) not in rendered_records

    caplog.clear()
    log_logger = logging.getLogger("parrot.knowledge.wiki.ledger.log")
    previous_level = log_logger.level
    log_logger.setLevel(logging.INFO)
    try:
        await asyncio.to_thread(log.append_line, _opened_event(4).model_dump_json())
    finally:
        log_logger.setLevel(previous_level)
    assert not [record for record in caplog.records if getattr(record, "event", None) == "wiki.sqlite.timing"]
