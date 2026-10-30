"""FEAT-758 M1 — durable ledger outbox."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.outbox import (
    LedgerOutbox,
    OutboxLockedError,
    StrictLedgerReadError,
    read_strict_events,
)

pytestmark = pytest.mark.asyncio


def _event(n: int) -> LedgerEvent:
    """Build a deterministic, shareable event for an isolated journal."""
    return LedgerEvent(
        kind="insight.recorded",
        subject=f"spec:FEAT-{n}",
        actor="agent:test",
        ts=f"2026-10-27T00:00:{n:02d}+00:00",
        payload={"fact": str(n), "title": str(n), "derived_from": "spec:FEAT-758"},
    )


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    """Create a local ledger directory for one test."""
    directory = tmp_path / ".parrot" / "ledger"
    directory.mkdir(parents=True)
    return directory


async def test_seals_only_complete_prefix(ledger_dir: Path, tmp_path: Path) -> None:
    """A trailing partial line stays pending and is reported, never sealed."""
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    first, _ = log.append(_event(1))
    second, _ = log.append(_event(2))
    with (ledger_dir / "events.jsonl").open("ab") as handle:
        handle.write(b'{"unfinished":')
    outbox = LedgerOutbox(ledger_dir)

    batch = await outbox.prepare(repo_root=tmp_path, source_ref="HEAD", source_head="abc")

    assert batch is not None
    assert batch.event_ids == [first, second]
    assert (await outbox.status())["truncated_tail"] is True


async def test_malformed_complete_line_fails_closed(ledger_dir: Path, tmp_path: Path) -> None:
    """A malformed complete journal record creates no accepted batch."""
    (ledger_dir / "events.jsonl").write_bytes(b"not-json\n")
    outbox = LedgerOutbox(ledger_dir)

    with pytest.raises(StrictLedgerReadError):
        await outbox.prepare(repo_root=tmp_path, source_ref="HEAD", source_head="abc")

    assert list((ledger_dir / "outbox" / "pending").iterdir()) == []


async def test_identity_collision_rejected(ledger_dir: Path) -> None:
    """A supplied event id for a different body is rejected by the strict reader."""
    event = _event(1)
    forged = event.model_dump()
    forged["subject"] = "spec:FEAT-forged"
    (ledger_dir / "events.jsonl").write_text(f"{json.dumps(forged)}\n", encoding="utf-8")

    with pytest.raises(StrictLedgerReadError):
        read_strict_events(ledger_dir / "events.jsonl")


async def test_later_append_goes_to_next_batch(ledger_dir: Path, tmp_path: Path) -> None:
    """A later complete append is sealed only by the next preparation."""
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    first, _ = log.append(_event(1))
    outbox = LedgerOutbox(ledger_dir)
    batch_one = await outbox.prepare(repo_root=tmp_path, source_ref="HEAD", source_head="one")
    second, _ = log.append(_event(2))
    batch_two = await outbox.prepare(repo_root=tmp_path, source_ref="HEAD", source_head="two")

    assert batch_one is not None and batch_two is not None
    assert batch_one.event_ids == [first]
    assert batch_two.event_ids == [second]
    assert [batch.batch_id for batch in await outbox.pending()] == [batch_one.batch_id, batch_two.batch_id]


async def test_known_ids_and_local_only_excluded(ledger_dir: Path, tmp_path: Path) -> None:
    """Known remote ids and coder-suspension insights are never sealed."""
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    known, _ = log.append(_event(1))
    local_only = LedgerEvent(
        kind="insight.recorded",
        subject="coder-suspension:one",
        actor="agent:test",
        ts="2026-10-27T00:00:02+00:00",
        payload={"fact": "one", "title": "one", "category": "coder_suspension", "derived_from": "task:TASK-1"},
    )
    log.append(local_only)
    outbox = LedgerOutbox(ledger_dir)

    assert await outbox.prepare(repo_root=tmp_path, source_ref="HEAD", source_head="abc", known_ids={known}) is None


async def test_crash_during_seal_leaves_no_batch(
    ledger_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed publish leaves source bytes intact and a retry seals the same events."""
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    event_id, _ = log.append(_event(1))
    source_bytes = (ledger_dir / "events.jsonl").read_bytes()
    outbox = LedgerOutbox(ledger_dir)
    real_rename = os.rename

    def fail_rename(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> None:
        raise OSError("simulated publish crash")

    monkeypatch.setattr("parrot.knowledge.wiki.ledger.outbox.os.rename", fail_rename)
    with pytest.raises(OSError, match="simulated publish crash"):
        await outbox.prepare(repo_root=tmp_path, source_ref="HEAD", source_head="abc")

    assert await outbox.pending() == []
    assert (ledger_dir / "events.jsonl").read_bytes() == source_bytes
    monkeypatch.setattr("parrot.knowledge.wiki.ledger.outbox.os.rename", real_rename)
    batch = await outbox.prepare(repo_root=tmp_path, source_ref="HEAD", source_head="abc")
    assert batch is not None
    assert batch.event_ids == [event_id]


async def test_tampered_batch_rejected_and_receipt_hides_batch(ledger_dir: Path, tmp_path: Path) -> None:
    """Tampered sealed bytes fail validation, while a receipt hides a valid batch."""
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    log.append(_event(1))
    outbox = LedgerOutbox(ledger_dir)
    tampered = await outbox.prepare(repo_root=tmp_path, source_ref="HEAD", source_head="one")
    assert tampered is not None
    (ledger_dir / "outbox" / "pending" / tampered.batch_id / "events.jsonl").write_bytes(b"tampered\n")
    with pytest.raises(StrictLedgerReadError, match="digest mismatch"):
        await outbox.pending()

    clean_dir = tmp_path / "clean" / "ledger"
    clean_dir.mkdir(parents=True)
    clean_log = LedgerLog(str(clean_dir / "events.jsonl"))
    clean_log.append(_event(2))
    clean_outbox = LedgerOutbox(clean_dir)
    batch = await clean_outbox.prepare(repo_root=tmp_path, source_ref="HEAD", source_head="two")
    assert batch is not None
    await clean_outbox.acknowledge(batch, remote_head="def", verified_digest="digest")
    assert await clean_outbox.pending() == []
    receipt = await clean_outbox.receipt_for(batch.batch_id)
    assert receipt is not None
    assert receipt.remote_head == "def"


async def test_second_preparer_is_locked_out(ledger_dir: Path, tmp_path: Path) -> None:
    """The non-blocking preparation lock rejects another preparer."""
    LedgerLog(str(ledger_dir / "events.jsonl")).append(_event(1))
    outbox = LedgerOutbox(ledger_dir)
    outbox.root.mkdir()
    with outbox.lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        with pytest.raises(OutboxLockedError):
            await outbox.prepare(repo_root=tmp_path, source_ref="HEAD", source_head="abc")
