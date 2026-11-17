"""FEAT-694 M2 — ``wikitoolkit ledger export-log|import-log``."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from click.testing import CliRunner

from parrot.knowledge.wiki.cli import ledger
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.shared_log import ClaimConflict, SharedLogExportReport, SharedLogImportReport


def test_cli_export_log_stage_is_rejected_without_writes(tmp_path: Path, monkeypatch) -> None:
    """An old hook's staged export exits before any ledger write or git staging."""
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True, text=True)
    service_factory = Mock(side_effect=AssertionError("LedgerService must not be constructed"))

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", service_factory):
        result = CliRunner().invoke(ledger, ["export-log", "--repo-root", str(tmp_path), "--stage", "--quiet"])

    assert result.exit_code == 4, result.output
    assert "export-log --stage is obsolete" in result.output
    assert not (tmp_path / "sdd" / "ledger" / "events.jsonl").exists()
    staged = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"], check=True, capture_output=True, text=True
    )
    assert staged.stdout == ""


def test_cli_import_log_outputs_and_exit_codes(tmp_path: Path, monkeypatch) -> None:
    """Import prints no-op/results/conflicts and exits two when its index is busy."""
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))
    service = MagicMock(spec=LedgerService)
    service.import_shared_log = AsyncMock(
        side_effect=[
            SharedLogImportReport(
                files=[],
                fast_path=True,
                added=0,
                skipped_known=0,
                skipped_unparseable=0,
                synced_events=0,
                index_busy=False,
            ),
            SharedLogImportReport(
                files=[],
                fast_path=False,
                added=2,
                skipped_known=3,
                skipped_unparseable=0,
                synced_events=2,
                index_busy=False,
                claim_conflicts=[
                    ClaimConflict(
                        issue_id="issue:abc",
                        local_claimed_by="task:local",
                        foreign_claimed_by="task:foreign",
                        foreign_event_id="e1",
                    )
                ],
            ),
            SharedLogImportReport(
                files=[],
                fast_path=False,
                added=1,
                skipped_known=0,
                skipped_unparseable=0,
                synced_events=0,
                index_busy=True,
            ),
        ]
    )

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        runner = CliRunner()
        current = runner.invoke(ledger, ["import-log", "--repo-root", str(tmp_path)])
        imported = runner.invoke(ledger, ["import-log", "--repo-root", str(tmp_path)])
        busy = runner.invoke(ledger, ["import-log", "--repo-root", str(tmp_path)])

    assert current.exit_code == 0
    assert "(up to date)" in current.output
    assert imported.exit_code == 0
    assert "Imported +2 events (3 known)" in imported.output
    assert "claim conflict on issue:abc: local task:local vs committed task:foreign (e1)" in imported.output
    assert busy.exit_code == 2


def _audit_payload(claim_conflicts: int, shared_path: Path) -> dict:
    """Return a complete `ledger audit` payload with the requested conflict count."""
    return {
        "log_size_bytes": 2048,
        "event_counts": {"issue.opened": 2},
        "total_events": 2,
        "cursor_offset": 2,
        "cursor_lag_events": 0,
        "broken_edges": 0,
        "shared_log": {
            "path": str(shared_path),
            "exists": True,
            "local_only_events": 0,
            "committed_unknown_events": 0,
            "marker": "ok",
            "claim_conflicts": claim_conflicts,
        },
        "sqlite": {"journal_mode": "wal", "busy_timeout_ms": 5000},
    }


def test_cli_audit_prints_claim_conflicts(tmp_path: Path, monkeypatch) -> None:
    """`ledger audit` prints the conflict count when non-zero and omits the line at zero."""
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))
    shared_path = tmp_path / "sdd" / "ledger" / "events.jsonl"
    shared_path.parent.mkdir(parents=True)
    shared_path.write_text("{}\n", encoding="utf-8")

    def run(claim_conflicts: int) -> str:
        service = MagicMock(spec=LedgerService)
        service.shared_root = tmp_path
        service.audit = AsyncMock(return_value=_audit_payload(claim_conflicts, shared_path))
        with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
            result = CliRunner().invoke(ledger, ["audit"])
        assert result.exit_code == 0, result.output
        return result.output

    conflicted = run(2)
    assert "claim conflicts: 2" in conflicted
    # the pre-existing shared-log line is untouched
    assert "marker: ok" in conflicted

    clean = run(0)
    assert "claim conflicts" not in clean
    assert "marker: ok" in clean
