"""FEAT-694 M5 -- committed-log rotation and claim pre-import."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from parrot.knowledge.wiki.cli import ledger
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.shared_log import (
    ARCHIVE_REL_DIR,
    MARKER_FILENAME,
    SHARED_LOG_REL_PATH,
    SharedLogRotateReport,
    digest_files,
    rotate_events,
    shared_log_files,
)


NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)
OLD = "2026-08-01T00:00:00+00:00"
RECENT = "2026-10-15T00:00:00+00:00"


def _event(kind: str, subject: str, timestamp: str, payload: dict | None = None) -> bytes:
    """Build one stable JSONL event line."""
    event = LedgerEvent(kind=kind, subject=subject, actor="task:4408", ts=timestamp, payload=payload or {})
    return (event.model_dump_json() + "\n").encode("utf-8")


def _write_current(root: Path, *lines: bytes) -> Path:
    """Write lines to the committed shared log under a temporary checkout."""
    current = root / SHARED_LOG_REL_PATH
    current.parent.mkdir(parents=True)
    current.write_bytes(b"".join(lines))
    return current


def test_rotate_moves_only_terminal_and_old(tmp_path: Path) -> None:
    """Only old lines for a finally terminal issue (and non-issues) are archived."""
    terminal_open = _event("issue.opened", "issue:terminal", OLD, {"title": "old", "body": "b", "discovered_from": "x"})
    terminal_close = _event("issue.closed", "issue:terminal", OLD, {"reason": "done", "closed_by": "task:4408"})
    active_open = _event("issue.opened", "issue:active", OLD, {"title": "active", "body": "b", "discovered_from": "x"})
    recent_task = _event("task.closed", "task:TASK-1", RECENT)
    old_task = _event("task.closed", "task:TASK-2", OLD)
    current = _write_current(tmp_path, terminal_open, terminal_close, active_open, recent_task, old_task)

    report = rotate_events(tmp_path, now=NOW)

    archive = tmp_path / ARCHIVE_REL_DIR / "events-2026-08.jsonl"
    assert report.moved == 3
    assert report.kept == 2
    assert report.archives_touched == [archive]
    assert archive.read_bytes() == terminal_open + terminal_close + old_task
    assert current.read_bytes() == active_open + recent_task


def test_rotate_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    """A fixed clock yields stable archives and a subsequent rotation is a no-op."""
    current = _write_current(tmp_path, _event("task.closed", "task:TASK-1", OLD))

    first = rotate_events(tmp_path, now=NOW)
    archive = tmp_path / ARCHIVE_REL_DIR / "events-2026-08.jsonl"
    first_archive = archive.read_bytes()
    second = rotate_events(tmp_path, now=NOW)

    assert first.moved == 1
    assert second.moved == 0
    assert archive.read_bytes() == first_archive


def test_marker_invalidated_by_rotation(tmp_path: Path) -> None:
    """Changing the logical file set makes the pre-rotation import marker stale."""
    current = _write_current(tmp_path, _event("task.closed", "task:TASK-1", OLD))
    marker = tmp_path / ".parrot" / "ledger" / MARKER_FILENAME
    marker.parent.mkdir(parents=True)
    marker.write_text(digest_files([current]), encoding="utf-8")

    report = rotate_events(tmp_path, now=NOW)

    assert report.moved == 1
    assert marker.read_text(encoding="utf-8") != digest_files(shared_log_files(tmp_path))


def test_rotate_keeps_unparseable_lines(tmp_path: Path) -> None:
    """Malformed bytes remain in the current log while eligible lines are moved."""
    malformed = b"{not json}\n"
    current = _write_current(tmp_path, malformed, _event("task.closed", "task:TASK-1", OLD))

    report = rotate_events(tmp_path, now=NOW)

    assert report.moved == 1
    assert report.kept == 1
    assert current.read_bytes() == malformed


def test_claim_imports_first_and_unreadable_checkout_does_not_block(tmp_path: Path, caplog) -> None:
    """Claims import first, while a broken committed checkout only produces a warning."""
    current = _write_current(tmp_path, _event("task.closed", "task:TASK-1", RECENT))
    index = MagicMock()
    index.claim_issue = AsyncMock(return_value=True)
    log = MagicMock()
    log.path = str(tmp_path / ".parrot" / "ledger" / "events.jsonl")
    service = LedgerService(index, MagicMock(), log, tmp_path)
    service.import_shared_log = AsyncMock()

    assert asyncio.run(service.claim("issue:test", "task:4408")) is True
    service.import_shared_log.assert_awaited_once()

    service.import_shared_log = AsyncMock(side_effect=OSError("unreadable checkout"))
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(service.claim("issue:test", "task:4408")) is True
    assert current.exists()
    assert "Shared ledger log import before claim failed" in caplog.text
    assert index.claim_issue.await_count == 2


def test_cli_rotate_log_stage_adds_archive(tmp_path: Path, monkeypatch) -> None:
    """The CLI stages the rewritten current log and every archive touched by rotation."""
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True, text=True)
    current = _write_current(tmp_path, _event("task.closed", "task:TASK-1", OLD))
    archive = tmp_path / ARCHIVE_REL_DIR / "events-2026-08.jsonl"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(_event("task.closed", "task:TASK-1", OLD))
    service = MagicMock(spec=LedgerService)
    service.rotate_shared_log = AsyncMock(
        return_value=SharedLogRotateReport(
            current=current,
            moved=1,
            kept=0,
            archives_touched=[archive],
            cutoff="2026-09-16T00:00:00+00:00",
        )
    )

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = CliRunner().invoke(
            ledger, ["rotate-log", "--repo-root", str(tmp_path), "--now", NOW.isoformat(), "--stage"]
        )

    assert result.exit_code == 0, result.output
    assert "Rotated 1 events into 1 archive file(s)" in result.output
    staged = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"], check=True, capture_output=True, text=True
    )
    assert staged.stdout.splitlines() == ["sdd/ledger/archive/events-2026-08.jsonl", "sdd/ledger/events.jsonl"]
