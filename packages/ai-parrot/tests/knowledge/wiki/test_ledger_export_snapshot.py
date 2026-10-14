"""FEAT-671: ``LedgerService.export_snapshot`` reconciles against the committed snapshot."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy

SERVICE_LOGGER = "parrot.knowledge.wiki.ledger.service"
ROW_KEYS = (
    "about",
    "acknowledged",
    "claimed_by",
    "closed_by",
    "closed_reason",
    "discovered_from",
    "issue_id",
    "kind",
    "resolved_by",
    "severity",
    "status",
    "title",
)


@pytest.fixture
def service(tmp_path: Path) -> LedgerService:
    """A LedgerService over an isolated temporary ledger root."""
    ledger_dir = tmp_path / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    store = LedgerStore(
        ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0)
    )
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    return LedgerService(LedgerIndex(store, log), store, log, tmp_path)


def _foreign_row(issue_id: str, status: str = "open") -> dict[str, Any]:
    """A canonical 12-key snapshot row for an issue this ledger never recorded."""
    row: dict[str, Any] = dict.fromkeys(ROW_KEYS)
    row.update(about=[], acknowledged=False, discovered_from="spec:FEAT-000", issue_id=issue_id)
    row.update(kind="bug", severity="minor", status=status, title=f"foreign {issue_id}")
    return row


def _write_rows(dest: Path, rows: list[dict[str, Any]]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _read_rows(dest: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines() if line]


async def _open_local(service: LedgerService, title: str = "local issue") -> str:
    return await service.open_issue(title, "body", "bug", "minor", "spec:FEAT-671", ["sym:a/b.py#f"])


async def test_export_carries_forward_rows_unknown_to_local_ledger(service: LedgerService, tmp_path: Path) -> None:
    dest = tmp_path / "sdd" / "ledger" / "issues.jsonl"
    foreign = [_foreign_row("issue:aaa"), _foreign_row("issue:zzz", "closed")]
    _write_rows(dest, foreign)
    local_id = await _open_local(service)

    assert await service.export_snapshot(dest) is True

    rows = _read_rows(dest)
    assert [row["issue_id"] for row in rows] == sorted({"issue:aaa", "issue:zzz", local_id})
    by_id = {row["issue_id"]: row for row in rows}
    assert by_id["issue:aaa"] == foreign[0]
    assert by_id["issue:zzz"] == foreign[1]
    assert by_id[local_id]["status"] == "open"


async def test_export_local_state_wins_for_known_issue(service: LedgerService, tmp_path: Path) -> None:
    dest = tmp_path / "issues.jsonl"
    local_id = await _open_local(service)
    assert await service.close_issue(local_id, "fixed upstream", "agent:test")
    _write_rows(dest, [_foreign_row(local_id)])  # stale "open" row for an issue this ledger knows

    assert await service.export_snapshot(dest) is True

    rows = _read_rows(dest)
    assert [row["issue_id"] for row in rows] == [local_id]
    assert rows[0]["status"] == "closed"
    assert rows[0]["closed_reason"] == "fixed upstream"


async def test_export_drops_locally_compacted_issue(service: LedgerService, tmp_path: Path) -> None:
    dest = tmp_path / "issues.jsonl"
    local_id = await _open_local(service)
    assert await service.close_issue(local_id, "done", "agent:test")
    assert await service.compact(older_than_days=0) == 1
    _write_rows(dest, [_foreign_row(local_id, "closed"), _foreign_row("issue:bbb")])

    assert await service.export_snapshot(dest) is True

    assert [row["issue_id"] for row in _read_rows(dest)] == ["issue:bbb"]


async def test_export_no_reconcile_rebuilds_from_local_only(service: LedgerService, tmp_path: Path) -> None:
    dest = tmp_path / "issues.jsonl"
    _write_rows(dest, [_foreign_row("issue:aaa"), _foreign_row("issue:zzz", "closed")])
    local_id = await _open_local(service)

    assert await service.export_snapshot(dest, reconcile=False) is True

    assert [row["issue_id"] for row in _read_rows(dest)] == [local_id]


async def test_export_deterministic_and_idempotent(service: LedgerService, tmp_path: Path) -> None:
    dest = tmp_path / "issues.jsonl"
    _write_rows(dest, [_foreign_row("issue:aaa")])
    await _open_local(service)

    assert await service.export_snapshot(dest) is True
    first = dest.read_bytes()
    assert await service.export_snapshot(dest) is False
    assert dest.read_bytes() == first


async def test_export_missing_dest_creates_file(service: LedgerService, tmp_path: Path) -> None:
    dest = tmp_path / "missing" / "parent" / "issues.jsonl"
    local_id = await _open_local(service)

    assert await service.export_snapshot(dest) is True

    assert dest.exists()
    assert [row["issue_id"] for row in _read_rows(dest)] == [local_id]


async def test_export_skips_malformed_snapshot_lines(
    service: LedgerService, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    dest = tmp_path / "issues.jsonl"
    good_a, good_b = _foreign_row("issue:aaa"), _foreign_row("issue:zzz")
    dest.write_text(
        json.dumps(good_a, sort_keys=True)
        + "\nnot json\n"
        + json.dumps({"title": "no id"})
        + "\n"
        + json.dumps(good_b, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING, logger=SERVICE_LOGGER):
        assert await service.export_snapshot(dest) is True

    assert _read_rows(dest) == [good_a, good_b]
    warnings = [
        rec.getMessage() for rec in caplog.records if rec.name == SERVICE_LOGGER and rec.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert "[2, 3]" in warnings[0]


def test_cli_export_no_reconcile_flag(service: LedgerService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`ledger export` keeps unknown rows by default and drops them with --no-reconcile."""
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))
    monkeypatch.setattr(LedgerService, "from_root", classmethod(lambda cls, root=None: service))
    dest = tmp_path / "snap" / "issues.jsonl"
    _write_rows(dest, [_foreign_row("issue:aaa")])
    runner = CliRunner()

    result = runner.invoke(wiki, ["ledger", "export", "--dest", str(dest)])
    assert result.exit_code == 0, result.output
    assert f"Exported {dest} (unchanged)" in result.output  # the foreign row is carried forward byte-for-byte
    assert [row["issue_id"] for row in _read_rows(dest)] == ["issue:aaa"]

    result = runner.invoke(wiki, ["ledger", "export", "--dest", str(dest), "--no-reconcile"])
    assert result.exit_code == 0, result.output
    assert f"Exported {dest} (changed)" in result.output
    assert _read_rows(dest) == []
