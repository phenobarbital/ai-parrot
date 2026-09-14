"""Tests for LedgerIndex: event reduction, replay cursor, and atomic claim."""

from __future__ import annotations

import asyncio
import multiprocessing
import sqlite3

import pytest

from parrot.knowledge.wiki.ledger.events import (
    LedgerEvent,
    compute_issue_id,
)
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy
from tests.knowledge.wiki.test_store_concurrency import _peer_writer


def _issue_id(title: str, discovered_from: str = "task:TASK-3200", kind: str = "bug") -> str:
    return compute_issue_id(kind, title, discovered_from)


def _opened_event(
    title: str,
    discovered_from: str = "task:TASK-3200",
    kind: str = "bug",
    severity: str = "minor",
    about: list[str] | None = None,
    actor: str = "agent:sdd",
) -> LedgerEvent:
    return LedgerEvent(
        kind="issue.opened",
        subject=_issue_id(title, discovered_from, kind),
        actor=actor,
        payload={
            "title": title,
            "body": f"Body for {title}",
            "kind": kind,
            "severity": severity,
            "discovered_from": discovered_from,
            "about": about or [],
        },
    )


@pytest.fixture
def ledger_paths(tmp_path):
    """Return (db_path, log_path) inside an isolated tmp_path."""
    return tmp_path / "ledger.db", tmp_path / "events.jsonl"


@pytest.fixture
async def ledger_store(ledger_paths):
    db_path, _ = ledger_paths
    store = LedgerStore(
        db_path=db_path,
        wiki_name="test-ledger",
        sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0),
    )
    yield store


@pytest.fixture
def ledger_log(ledger_paths):
    _, log_path = ledger_paths
    return LedgerLog(str(log_path))


@pytest.fixture
def ledger_index(ledger_store, ledger_log):
    return LedgerIndex(ledger_store, ledger_log)


async def _get_status(index: LedgerIndex, issue_id: str) -> str | None:
    async with index.store.ledger_transaction("test-read") as conn:
        state = await index._read_issue(conn, issue_id)
    return state.get("status") if state else None


class TestReplayAndCursor:
    async def test_sync_applies_appended_events_and_advances_cursor(self, ledger_index):
        event = _opened_event("Leak in connection pool")
        ledger_index.log.append(event)

        applied = await ledger_index.sync()

        assert applied == 1
        assert await _get_status(ledger_index, event.subject) == "open"
        offset, last_event_id = await ledger_index.store.read_cursor()
        assert last_event_id == event.event_id
        assert offset == 0  # start offset of the (only, first) applied event's line

    async def test_repeated_sync_with_no_new_events_is_a_noop(self, ledger_index):
        event = _opened_event("Duplicate cleanup crash")
        ledger_index.log.append(event)
        assert await ledger_index.sync() == 1

        # Nothing new appended: a second sync applies zero events and does
        # not rescan/reapply anything already-applied.
        assert await ledger_index.sync() == 0

    async def test_rebuild_and_repeated_sync_produce_identical_state(self, ledger_index):
        e1 = _opened_event("Race in claim path")
        e2 = LedgerEvent(
            kind="issue.claimed",
            subject=e1.subject,
            actor="task:TASK-9001",
            payload={"claimed_by": "task:TASK-9001"},
        )
        ledger_index.log.append(e1)
        ledger_index.log.append(e2)

        applied_via_sync = await ledger_index.sync()
        status_after_sync = await _get_status(ledger_index, e1.subject)
        cursor_after_sync = await ledger_index.store.read_cursor()

        applied_via_rebuild = await ledger_index.rebuild()
        status_after_rebuild = await _get_status(ledger_index, e1.subject)
        cursor_after_rebuild = await ledger_index.store.read_cursor()

        assert applied_via_sync == 2
        assert applied_via_rebuild == 2
        assert status_after_sync == status_after_rebuild == "claimed"
        assert cursor_after_sync == cursor_after_rebuild

    async def test_cursor_mismatch_triggers_rebuild(self, ledger_index):
        e1 = _opened_event("First issue")
        ledger_index.log.append(e1)
        assert await ledger_index.sync() == 1

        # Corrupt the persisted cursor so it no longer matches the log.
        async with ledger_index.store.ledger_transaction("corrupt") as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO ledger_state (key, value) VALUES ('last_event_id', 'not-a-real-event')"
            )

        e2 = _opened_event("Second issue", discovered_from="task:TASK-3201")
        ledger_index.log.append(e2)

        applied = await ledger_index.sync()

        # A full rebuild replays both events from offset 0.
        assert applied == 2
        assert await _get_status(ledger_index, e1.subject) == "open"
        assert await _get_status(ledger_index, e2.subject) == "open"

    async def test_issue_opened_dedup_is_noop_except_discovered_from_edge(self, ledger_index):
        e1 = _opened_event("Same bug reported twice")
        e2 = LedgerEvent(
            kind="issue.opened",
            subject=e1.subject,
            actor="agent:codex",
            payload={
                "title": "Same bug reported twice",
                "body": "A different body should NOT overwrite the original",
                "kind": "bug",
                "severity": "critical",
                "discovered_from": "task:TASK-4000",
                "about": [],
            },
        )
        ledger_index.log.append(e1)
        ledger_index.log.append(e2)

        await ledger_index.sync()

        async with ledger_index.store.ledger_transaction("read") as conn:
            state = await ledger_index._read_issue(conn, e1.subject)
            async with conn.execute(
                "SELECT 1 FROM edges WHERE src = ? AND dst = ? AND rel = 'discovered-from'",
                (e1.subject, "task:TASK-4000"),
            ) as cur:
                edge_row = await cur.fetchone()

        # Original fields untouched (severity stays "minor", not "critical").
        assert state["severity"] == "minor"
        assert edge_row is not None

    async def test_acknowledge_sets_flag_without_changing_status(self, ledger_index):
        e1 = _opened_event("Needs a human call")
        ledger_index.log.append(e1)
        await ledger_index.sync()

        ack = LedgerEvent(
            kind="issue.acknowledged",
            subject=e1.subject,
            actor="human:jesus",
            payload={"acknowledged_by": "human:jesus", "reason": "known, tracked elsewhere"},
        )
        ledger_index.log.append(ack)
        await ledger_index.sync()

        async with ledger_index.store.ledger_transaction("read") as conn:
            state = await ledger_index._read_issue(conn, e1.subject)

        assert state["status"] == "open"
        assert state["acknowledged"] is True

    async def test_acknowledge_ignored_once_closed(self, ledger_index):
        e1 = _opened_event("Already resolved")
        ledger_index.log.append(e1)
        close = LedgerEvent(
            kind="issue.closed",
            subject=e1.subject,
            actor="human:jesus",
            payload={"reason": "fixed", "closed_by": "human:jesus"},
        )
        ledger_index.log.append(close)
        ack = LedgerEvent(
            kind="issue.acknowledged",
            subject=e1.subject,
            actor="human:jesus",
            payload={"acknowledged_by": "human:jesus", "reason": "too late"},
        )
        ledger_index.log.append(ack)

        await ledger_index.sync()

        async with ledger_index.store.ledger_transaction("read") as conn:
            state = await ledger_index._read_issue(conn, e1.subject)

        assert state["status"] == "closed"
        assert state["acknowledged"] is False

    async def test_compact_never_rewrites_events_log(self, ledger_index, ledger_paths):
        _, log_path = ledger_paths
        e1 = _opened_event("Old resolved issue")
        close = LedgerEvent(
            kind="issue.closed",
            subject=e1.subject,
            actor="human:jesus",
            payload={"reason": "fixed", "closed_by": "human:jesus"},
        )
        ledger_index.log.append(e1)
        ledger_index.log.append(close)
        await ledger_index.sync()

        before = log_path.read_bytes()
        folded = await ledger_index.compact(older_than_days=-1)
        after = log_path.read_bytes()

        assert folded == 1
        assert before == after


class TestAtomicClaim:
    async def test_claim_open_issue_succeeds_and_persists_claimed_by(self, ledger_index):
        e1 = _opened_event("Claimable issue")
        ledger_index.log.append(e1)
        await ledger_index.sync()

        claimed = await ledger_index.claim_issue(e1.subject, "task:TASK-3205")

        assert claimed is True
        async with ledger_index.store.ledger_transaction("read") as conn:
            state = await ledger_index._read_issue(conn, e1.subject)
        assert state["status"] == "claimed"
        assert state["claimed_by"] == "task:TASK-3205"

    async def test_claim_already_claimed_issue_fails(self, ledger_index):
        e1 = _opened_event("Contested issue")
        ledger_index.log.append(e1)
        await ledger_index.sync()

        first = await ledger_index.claim_issue(e1.subject, "task:TASK-1")
        second = await ledger_index.claim_issue(e1.subject, "task:TASK-2")

        assert first is True
        assert second is False

    async def test_exactly_one_concurrent_claimant_succeeds(self, ledger_index):
        e1 = _opened_event("Concurrently claimed issue")
        ledger_index.log.append(e1)
        await ledger_index.sync()

        results = await asyncio.gather(
            ledger_index.claim_issue(e1.subject, "task:TASK-A"),
            ledger_index.claim_issue(e1.subject, "task:TASK-B"),
        )

        assert sorted(results) == [False, True]
        async with ledger_index.store.ledger_transaction("read") as conn:
            state = await ledger_index._read_issue(conn, e1.subject)
        assert state["status"] == "claimed"
        assert state["claimed_by"] in ("task:TASK-A", "task:TASK-B")

    async def test_claim_synchronizes_stale_index_before_checking_status(self, ledger_index):
        # Simulate another writer appending directly to the log without
        # anyone ever having called sync() for this index instance yet.
        e1 = _opened_event("Never synced before claim")
        ledger_index.log.append(e1)

        claimed = await ledger_index.claim_issue(e1.subject, "task:TASK-9")

        assert claimed is True

    async def test_claim_never_skips_an_event_appended_in_the_race_window(self, ledger_index):
        """Regression test: a concurrent writer's event landing between
        claim_issue's initial sync and its own append must still be applied,
        not silently and permanently skipped by the cursor advance.

        LedgerLog.append()'s returned offset for the CLAIM event is only
        accurate about the claim event's own position — it says nothing
        about whether some OTHER event landed just before it that was
        never itself applied. Advancing the cursor straight to "the claim
        event's position" (the old, buggy behavior) would leave that other
        event physically in the log but permanently unapplied, since a
        later sync() would resume scanning from after it.
        """
        e1 = _opened_event("Claimable during race")
        ledger_index.log.append(e1)
        await ledger_index.sync()

        e2 = _opened_event("Concurrent open during claim", discovered_from="task:TASK-9999")
        original_append = ledger_index.log.append

        def racy_append(event):
            # Simulate another writer's event landing in the file BETWEEN
            # claim_issue's initial sync and its own append call.
            original_append(e2)
            return original_append(event)

        ledger_index.log.append = racy_append
        try:
            claimed = await ledger_index.claim_issue(e1.subject, "task:TASK-1")
        finally:
            ledger_index.log.append = original_append

        assert claimed is True
        async with ledger_index.store.ledger_transaction("read") as conn:
            e2_state = await ledger_index._read_issue(conn, e2.subject)
        assert e2_state is not None, "concurrently-appended event was silently skipped"
        assert e2_state["status"] == "open"

        # A later sync() finds nothing new — everything already applied.
        assert await ledger_index.sync() == 0


@pytest.mark.slow
class TestBusyBehaviour:
    """AC: a busy claim appends no issue.claimed; a busy open remains replayable."""

    async def test_busy_claim_appends_no_issue_claimed_event(self, ledger_paths):
        db_path, log_path = ledger_paths
        store = LedgerStore(
            db_path=db_path,
            wiki_name="test-ledger",
            sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0),
        )
        log = LedgerLog(str(log_path))
        index = LedgerIndex(store, log)

        e1 = _opened_event("Busy claim target")
        log.append(e1)
        await index.sync()

        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Event()
        release = ctx.Event()
        result = ctx.Value("c", b" ")
        p = ctx.Process(target=_peer_writer, args=(str(db_path), ready, release, result))
        p.start()
        try:
            ready.wait(timeout=5.0)
            lines_before = log_path.read_text().splitlines()

            with pytest.raises(WikiStoreBusy):
                await index.claim_issue(e1.subject, "task:TASK-busy")

            lines_after = log_path.read_text().splitlines()
            assert lines_after == lines_before
        finally:
            release.set()
            p.join(timeout=5.0)

        assert result.value == b"O"
        # Once the peer releases, the issue is still claimable normally.
        assert await index.claim_issue(e1.subject, "task:TASK-after") is True

    async def test_busy_sync_leaves_event_durable_and_later_replayable(self, ledger_paths):
        db_path, log_path = ledger_paths
        store = LedgerStore(
            db_path=db_path,
            wiki_name="test-ledger",
            sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0),
        )
        log = LedgerLog(str(log_path))
        index = LedgerIndex(store, log)

        # Prime the store (schema/WAL setup) before contending on it, same
        # as FEAT-557's own concurrency tests — otherwise the very first
        # write anywhere can itself surface a raw sqlite3.OperationalError
        # instead of the typed WikiStoreBusy this test is asserting on.
        async with store.ledger_transaction("prime"):
            pass

        # Event is durable in the log the moment it is appended, independent
        # of whether the index write ever succeeds.
        e1 = _opened_event("Durable despite busy index")
        log.append(e1)

        ctx = multiprocessing.get_context("spawn")
        ready = ctx.Event()
        release = ctx.Event()
        result = ctx.Value("c", b" ")
        p = ctx.Process(target=_peer_writer, args=(str(db_path), ready, release, result))
        p.start()
        try:
            ready.wait(timeout=5.0)

            with pytest.raises(WikiStoreBusy):
                await index.sync()
        finally:
            release.set()
            p.join(timeout=5.0)

        assert result.value == b"O"

        # The event was never lost: a later sync (once the peer released
        # the lock) replays it successfully.
        applied = await index.sync()
        assert applied == 1
        assert await _get_status(index, e1.subject) == "open"
