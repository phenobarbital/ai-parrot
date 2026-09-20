"""CLI tests for the SDD work ledger (FEAT-566, Module 9).

Tests CLI registration, exit codes, command behavior, and WikiStoreBusy handling.
"""

from __future__ import annotations

import asyncio
import errno
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import ledger, wiki
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy


@pytest.fixture
def runner() -> CliRunner:
    """Click test runner."""
    return CliRunner()


@pytest.fixture
def mock_ledger_service(tmp_path: Path) -> MagicMock:
    """Mock LedgerService for CLI testing."""
    service = MagicMock(spec=LedgerService)
    service.open_issue = AsyncMock(return_value="issue:abc123")
    service.ready_work = AsyncMock(return_value=[])
    service.claim = AsyncMock(return_value=True)
    service.acknowledge = AsyncMock(return_value=True)
    service.close_issue = AsyncMock(return_value=True)
    service.get_context = AsyncMock(return_value="")
    service.merge_blockers = AsyncMock(return_value=[])
    service.export_snapshot = AsyncMock(return_value=True)
    service.compact = AsyncMock(return_value=0)
    service.audit = AsyncMock(
        return_value={
            "log_size_bytes": 1024,
            "event_counts": {"issue.opened": 5},
            "total_events": 5,
            "cursor_offset": 1024,
            "cursor_lag_events": 0,
            "broken_edges": 0,
            "sqlite": {"journal_mode": "wal", "busy_timeout_ms": 5000},
        }
    )
    service.index = MagicMock()
    service.index.sync = AsyncMock()
    service.index.rebuild = AsyncMock()
    service.store = MagicMock()
    service.store.checkpoint = AsyncMock()
    service.shared_root = tmp_path
    return service


def test_ledger_group_registered(runner: CliRunner) -> None:
    """Test that the ledger group is registered under the wiki command."""
    result = runner.invoke(wiki, ["ledger", "--help"])
    assert result.exit_code == 0
    assert "Manage the SDD work ledger" in result.output


def test_ledger_open_command(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test ledger open command."""
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        result = runner.invoke(
            ledger,
            [
                "open",
                "--kind",
                "bug",
                "--severity",
                "critical",
                "--discovered-from",
                "spec:FEAT-566",
                "--about",
                "sym:Foo.bar",
                "--title",
                "Test issue",
                "--body",
                "Description",
            ],
        )
    assert result.exit_code == 0
    assert "Opened issue:abc123" in result.output


def test_ledger_open_busy_soft_success(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test that WikiStoreBusy during open is a soft success."""
    service = mock_ledger_service
    service.open_issue = AsyncMock(side_effect=WikiStoreBusy("ledger.db", "write", 1.5))

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(
            ledger,
            [
                "open",
                "--kind",
                "bug",
                "--discovered-from",
                "spec:FEAT-566",
                "--title",
                "Test",
                "--body",
                "Desc",
            ],
        )
    assert result.exit_code == 0
    assert "index_pending" in result.output


def test_ledger_open_read_only_shared_root_is_reported(runner: CliRunner) -> None:
    """A sandboxed shared ledger write is reported without an unhandled exception."""
    with patch(
        "parrot.knowledge.wiki.cli.LedgerService.from_root",
        side_effect=OSError(errno.EROFS, "Read-only file system"),
    ):
        result = runner.invoke(
            ledger,
            [
                "open",
                "--kind",
                "bug",
                "--discovered-from",
                "spec:FEAT-566",
                "--title",
                "Test",
                "--body",
                "Desc",
            ],
        )
    assert result.exit_code == 0
    assert "NOT filed: shared ledger is read-only" in result.output


def test_ledger_claim_busy_exit_2(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test that WikiStoreBusy during claim exits 2."""
    service = mock_ledger_service
    service.claim = AsyncMock(side_effect=WikiStoreBusy("ledger.db", "write", 1.5))

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["claim", "issue:abc123"])
    assert result.exit_code == 2


def test_ledger_acknowledge_restricts_human(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test that acknowledge rejects non-human actors."""
    service = mock_ledger_service
    service.acknowledge = AsyncMock(return_value=False)

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(
            ledger,
            ["acknowledge", "issue:abc123", "--reason", "wontfix", "--actor", "agent:cli"],
        )
    assert result.exit_code == 1
    assert "not human" in result.output


def test_ledger_acknowledge_accepts_human(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test that acknowledge accepts human actors."""
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        result = runner.invoke(
            ledger,
            ["acknowledge", "issue:abc123", "--reason", "verified", "--actor", "human:alice"],
        )
    assert result.exit_code == 0
    assert "Acknowledged" in result.output


def test_ledger_ready_lists_issues(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test ledger ready command lists unclaimed issues."""
    service = mock_ledger_service
    service.ready_work = AsyncMock(
        return_value=[
            {
                "issue_id": "issue:abc123",
                "title": "Test issue",
                "status": "open",
                "severity": "critical",
                "kind": "bug",
            }
        ]
    )

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["ready"])
    assert result.exit_code == 0
    assert "issue:abc123" in result.output
    assert "critical" in result.output


def test_ledger_close_command(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test ledger close command."""
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        result = runner.invoke(
            ledger,
            ["close", "issue:abc123", "--reason", "fixed"],
        )
    assert result.exit_code == 0
    assert "Closed" in result.output


def test_ledger_close_busy_soft_success(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test that WikiStoreBusy during close is a soft success."""
    service = mock_ledger_service
    service.close_issue = AsyncMock(side_effect=WikiStoreBusy("ledger.db", "write", 1.5))

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["close", "issue:abc123", "--reason", "fixed"])
    assert result.exit_code == 0
    assert "index_pending" in result.output


def test_ledger_context_empty(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test ledger context with no matching issues."""
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        result = runner.invoke(ledger, ["context", "sym:Foo.bar"])
    assert result.exit_code == 0
    assert "no relevant" in result.output


def test_ledger_context_with_issues(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test ledger context with matching issues."""
    service = mock_ledger_service
    service.get_context = AsyncMock(return_value="- [critical] issue:abc123 Test issue (open)")

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["context", "sym:Foo.bar"])
    assert result.exit_code == 0
    assert "issue:abc123" in result.output


def test_ledger_blockers_exit_1_when_blocking(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test that blockers exits 1 when there are blocking issues."""
    service = mock_ledger_service
    service.merge_blockers = AsyncMock(
        return_value=[
            {
                "issue_id": "issue:abc123",
                "title": "Critical bug",
                "severity": "critical",
                "discovered_from": "spec:FEAT-566",
            }
        ]
    )

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["blockers", "FEAT-566"])
    assert result.exit_code == 1
    assert "issue:abc123" in result.output


def test_ledger_blockers_exit_0_when_none(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test that blockers exits 0 when there are no blocking issues."""
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        result = runner.invoke(ledger, ["blockers", "FEAT-566"])
    assert result.exit_code == 0
    assert "No blocking issues" in result.output


def test_ledger_export_changed(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test ledger export when content changed."""
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        result = runner.invoke(ledger, ["export"])
    assert result.exit_code == 0
    assert "changed" in result.output


def test_ledger_export_unchanged(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test ledger export when content unchanged."""
    service = mock_ledger_service
    service.export_snapshot = AsyncMock(return_value=False)

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["export"])
    assert result.exit_code == 0
    assert "unchanged" in result.output


def test_ledger_sync_command(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test ledger sync command."""
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        result = runner.invoke(ledger, ["sync"])
    assert result.exit_code == 0
    assert "synced" in result.output


def test_ledger_sync_busy_exits_2(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """WikiStoreBusy during sync exits 2 (Module 2 SS2.2: sync/rebuild/ingest-sdd/compact all do)."""
    service = mock_ledger_service
    service.index.sync = AsyncMock(side_effect=WikiStoreBusy("ledger.db", "write", 1.5))

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["sync"])
    assert result.exit_code == 2
    assert "failed" in result.output


def test_ledger_rebuild_calls_checkpoint(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test that rebuild calls checkpoint after success."""
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        result = runner.invoke(ledger, ["rebuild"])
    assert result.exit_code == 0
    assert "rebuilt" in result.output
    mock_ledger_service.store.checkpoint.assert_called_once_with(truncate=True)


def test_ledger_rebuild_checkpoint_busy_nonfatal(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test that checkpoint failure during rebuild is non-fatal."""
    service = mock_ledger_service
    service.store.checkpoint = AsyncMock(side_effect=WikiStoreBusy("ledger.db", "write", 1.5))

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["rebuild"])
    assert result.exit_code == 0
    assert "rebuilt" in result.output


def test_ledger_rebuild_re_ingests_sdd_graph(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """rebuild() replays only events.jsonl; spec:/task: pages/edges from
    `ledger ingest-sdd` are NOT event-sourced, so a plain rebuild would
    silently and permanently wipe them without a re-ingest right after."""
    mock_ingester = MagicMock()
    mock_ingester.ingest_all = AsyncMock(return_value={"specs": 1, "tasks": 5, "edges": 3})

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        with patch("parrot.knowledge.wiki.ledger.sdd_ingest.SDDGraphIngest", return_value=mock_ingester) as mock_cls:
            result = runner.invoke(ledger, ["rebuild"])

    assert result.exit_code == 0
    mock_cls.assert_called_once_with(mock_ledger_service.store, mock_ledger_service.shared_root)
    mock_ingester.ingest_all.assert_awaited_once()


def test_ledger_ingest_sdd_calls_checkpoint(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test that ingest-sdd calls checkpoint after success."""
    mock_ingester = MagicMock()
    mock_ingester.ingest_all = AsyncMock(return_value={"specs": 1, "tasks": 5, "edges": 3})

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        with patch("parrot.knowledge.wiki.ledger.sdd_ingest.SDDGraphIngest", return_value=mock_ingester):
            result = runner.invoke(ledger, ["ingest-sdd"])
    assert result.exit_code == 0
    assert "ingested" in result.output
    assert "1 specs" in result.output
    assert "5 tasks" in result.output
    mock_ledger_service.store.checkpoint.assert_called_with(truncate=True)


def test_ledger_rebuild_busy_exits_2(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """WikiStoreBusy during the rebuild itself (not just its checkpoint) exits 2."""
    service = mock_ledger_service
    service.index.rebuild = AsyncMock(side_effect=WikiStoreBusy("ledger.db", "write", 1.5))

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["rebuild"])
    assert result.exit_code == 2
    assert "failed" in result.output


def test_ledger_ingest_sdd_busy_exits_2(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """WikiStoreBusy during ingest-sdd itself exits 2."""
    mock_ingester = MagicMock()
    mock_ingester.ingest_all = AsyncMock(side_effect=WikiStoreBusy("ledger.db", "write", 1.5))

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        with patch("parrot.knowledge.wiki.ledger.sdd_ingest.SDDGraphIngest", return_value=mock_ingester):
            result = runner.invoke(ledger, ["ingest-sdd"])
    assert result.exit_code == 2
    assert "failed" in result.output


def test_ledger_compact_command(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test ledger compact command."""
    service = mock_ledger_service
    service.compact = AsyncMock(return_value=5)

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["compact"])
    assert result.exit_code == 0
    assert "5 issue(s) folded" in result.output


def test_ledger_compact_busy_exits_2(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """WikiStoreBusy during compact exits 2 instead of raising an unhandled traceback."""
    service = mock_ledger_service
    service.compact = AsyncMock(side_effect=WikiStoreBusy("ledger.db", "write", 1.5))

    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["compact"])
    assert result.exit_code == 2
    assert "failed" in result.output


def test_ledger_audit_command(runner: CliRunner, mock_ledger_service: MagicMock) -> None:
    """Test ledger audit command."""
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=mock_ledger_service):
        result = runner.invoke(ledger, ["audit"])
    assert result.exit_code == 0
    assert "Log size" in result.output
    assert "Total events" in result.output
    assert "SQLite" in result.output


def _real_ledger_service(tmp_path: Path) -> LedgerService:
    """Real service on tmp_path — mirrors tests/knowledge/wiki/test_ledger_service.py::ledger_service."""
    ledger_dir = tmp_path / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    store = LedgerStore(
        ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0)
    )
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    return LedgerService(LedgerIndex(store, log), store, log, tmp_path)


def test_ledger_ready_cli_prints_severity_order(runner: CliRunner, tmp_path: Path) -> None:
    """`ledger ready` inherits ready_work()'s canonical order (S6) — no CLI change needed."""
    service = _real_ledger_service(tmp_path)
    asyncio.run(service.open_issue(title="Low first in log", body="b", severity="low", discovered_from="task:TASK-1"))
    asyncio.run(
        service.open_issue(title="Major second in log", body="b", severity="major", discovered_from="task:TASK-1")
    )
    with patch("parrot.knowledge.wiki.cli.LedgerService.from_root", return_value=service):
        result = runner.invoke(ledger, ["ready"])
    assert result.exit_code == 0
    assert result.output.index("[major]") < result.output.index("[low]")
