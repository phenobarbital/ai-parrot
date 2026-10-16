"""FEAT-694 M2 — ``wikitoolkit ledger export-log|import-log``."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from parrot.knowledge.wiki.cli import ledger
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.shared_log import ClaimConflict, SharedLogExportReport, SharedLogImportReport


def test_cli_export_log_stage_runs_git_add(tmp_path: Path, monkeypatch) -> None:
    """Export stages a created/changed shared log in the requested checkout."""
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True, text=True)
    dest = tmp_path / "sdd" / "ledger" / "events.jsonl"
    dest.parent.mkdir(parents=True)
    dest.write_text("{}\n", encoding="utf-8")
    service = MagicMock(spec=LedgerService)
    service.export_shared_log = AsyncMock(
        return_value=SharedLogExportReport(dest=dest, created=True, added=1, skipped_local_only=0, total_committed=1)
    )

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = CliRunner().invoke(ledger, ["export-log", "--repo-root", str(tmp_path), "--stage"])

    assert result.exit_code == 0, result.output
    assert f"Exported {dest} (+1 events)" in result.output
    staged = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"], check=True, capture_output=True, text=True
    )
    assert staged.stdout.strip() == "sdd/ledger/events.jsonl"


def test_cli_import_log_outputs_and_exit_codes(tmp_path: Path, monkeypatch) -> None:
    """Import prints no-op/results/conflicts and exits two when its index is busy."""
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))
    service = MagicMock(spec=LedgerService)
    service.import_shared_log = AsyncMock(
        side_effect=[
            SharedLogImportReport(
                files=[], fast_path=True, added=0, skipped_known=0, skipped_unparseable=0, synced_events=0, index_busy=False
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
                        issue_id="issue:abc", local_claimed_by="task:local", foreign_claimed_by="task:foreign", foreign_event_id="e1"
                    )
                ],
            ),
            SharedLogImportReport(
                files=[], fast_path=False, added=1, skipped_known=0, skipped_unparseable=0, synced_events=0, index_busy=True
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
