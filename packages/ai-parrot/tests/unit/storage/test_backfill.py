"""FEAT-886 M11 — backfill driver on the real SQLite backend."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parrot.storage.backends.base import BackfillBatch
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.backfill import BackfillReport, main, run_backfill

T0 = datetime(2026, 11, 1, 10, tzinfo=timezone.utc)


def _seed(path: str, session: str, rows: list[dict]) -> None:
    raw = sqlite3.connect(path)
    for row in rows:
        raw.execute(
            "INSERT INTO conversations (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at)"
            " VALUES ('u','a',?,'turn',?,?,1.0,NULL)", (session, f"TURN#{row['turn_id']}", json.dumps(row)))
    raw.commit()
    raw.close()


def _legacy(i: int, ts: str | None = None) -> dict:
    row = {"turn_id": f"l{i:03d}", "user_message": "q", "assistant_response": "a"}
    row["timestamp"] = ts or T0.replace(second=i % 60).isoformat()
    return row


@pytest.fixture
async def backend(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "bf.db"))
    await b.initialize()
    yield b
    await b.close()


async def test_resumable_backfill_completes_and_is_idempotent(backend, tmp_path):
    _seed(str(tmp_path / "bf.db"), "s1", [_legacy(i) for i in range(7)])
    cursor_file = tmp_path / "cursor.json"
    first = await run_backfill(backend, batch_size=3, max_batches=1, cursor_path=cursor_file)
    assert first.processed == 3 and first.complete is False
    assert json.loads(cursor_file.read_text())["cursor"] is not None
    second = await run_backfill(backend, batch_size=3, cursor_path=cursor_file)
    assert second.complete is True and first.processed + second.processed == 7
    assert await backend.get_index_state("u", "a", "s1") == "ready"
    third = await run_backfill(backend, batch_size=3, cursor_path=cursor_file)  # complete file starts a new pass
    assert third == BackfillReport(processed=0, complete=True, invalid_sessions=())


async def test_invalid_session_is_reported_and_never_ready(backend, tmp_path):
    _seed(str(tmp_path / "bf.db"), "bad", [_legacy(1), _legacy(2, ts="garbage")])
    report = await run_backfill(backend, batch_size=10)
    assert report.complete and report.invalid_sessions == ("u/a/bad",)
    assert await backend.get_index_state("u", "a", "bad") == "invalid"


async def test_new_writes_during_backfill_are_untouched(backend, tmp_path):
    _seed(str(tmp_path / "bf.db"), "s1", [_legacy(i) for i in range(4)])
    await backend.put_turn("u", "a", "live", "n1", {"timestamp": T0.isoformat(), "sequence": 1,
                                                      "user_message": "q", "assistant_response": "a"})
    report = await run_backfill(backend, batch_size=2)
    assert report.processed == 4
    assert [t["turn_id"] for t in await backend.query_turn_window("u", "a", "live", 5)] == ["n1"]


async def test_tombstoned_session_is_skipped(backend, tmp_path):
    _seed(str(tmp_path / "bf.db"), "dead", [_legacy(1)])
    await backend.put_tombstone("u", "a", "dead")
    assert (await run_backfill(backend, batch_size=5)).processed == 0


async def test_no_progress_cursor_fails_loudly(tmp_path):
    class Stuck:
        async def backfill_batch(self, cursor, batch_size):
            return BackfillBatch(0, "same", ())

    with pytest.raises(RuntimeError, match="no progress"):
        await run_backfill(Stuck(), batch_size=1)  # 1st call -> "same"; the 2nd gets it back -> guard trips


async def test_damaged_state_file_starts_a_fresh_pass(backend, tmp_path):
    cursor_file = tmp_path / "cursor.json"
    cursor_file.write_text("{not json")
    _seed(str(tmp_path / "bf.db"), "s1", [_legacy(1)])
    assert (await run_backfill(backend, cursor_path=cursor_file)).processed == 1


async def test_argument_validation(backend):
    with pytest.raises(ValueError):
        await run_backfill(backend, batch_size=0)
    with pytest.raises(ValueError):
        await run_backfill(backend, max_batches=0)


def test_cli_exit_codes_and_summary(tmp_path, monkeypatch, capsys):
    db = str(tmp_path / "cli.db")
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("PARROT_SQLITE_PATH", db)
    seed = ConversationSQLiteBackend(path=db)
    import asyncio

    asyncio.run(seed.initialize())
    asyncio.run(seed.close())
    _seed(db, "ok", [_legacy(1)])
    cursor = tmp_path / "c.json"
    assert main(["--cursor-file", str(cursor)]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["complete"] is True
    _seed(db, "bad", [_legacy(2, ts="garbage")])
    assert main(["--cursor-file", str(cursor)]) == 2
    _seed(db, "more", [_legacy(i) for i in range(10, 16)])
    assert main(["--cursor-file", str(cursor), "--batch-size", "2", "--max-batches", "1"]) == 3
