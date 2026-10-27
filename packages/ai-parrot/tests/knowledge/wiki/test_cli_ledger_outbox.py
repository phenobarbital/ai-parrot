"""FEAT-758 M3 — ``wikitoolkit ledger outbox`` CLI exit codes and source resolution."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import ledger
from parrot.knowledge.wiki.ledger.outbox import LedgerBatch, LedgerDeliveryReport, OutboxLockedError


@pytest.fixture(autouse=True)
def _local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep commands local unless a test explicitly supplies a remote sentinel."""
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, None))


def _batch() -> LedgerBatch:
    """Return one valid immutable batch suitable for CLI report tests."""
    return LedgerBatch(
        batch_id="123e4567-e89b-42d3-a456-426614174000",
        source_ref="feature/test",
        source_head="a" * 40,
        source_end_offset=0,
        source_sha256="a" * 64,
        events_sha256="b" * 64,
        event_ids=[],
    )


@pytest.mark.parametrize(
    ("status", "code"),
    [("delivered", 0), ("already_delivered", 0), ("pending", 2), ("conflict", 3), ("unsupported", 4)],
)
def test_integrate_maps_status_to_exit_code(tmp_path: Path, status: str, code: int) -> None:
    """Typed integrator statuses preserve their documented process codes."""
    batch = _batch()
    outbox = MagicMock()
    outbox.pending = AsyncMock(return_value=[batch])
    report = LedgerDeliveryReport(
        status=status,
        batch_id=batch.batch_id,
        attempts=1,
        remote_head=None,
        commit_sha=None,
        added=0,
        remaining=0,
    )
    integrator = MagicMock()
    integrator.integrate = AsyncMock(return_value=report)
    with (
        patch("parrot.knowledge.wiki.cli.LedgerOutbox", return_value=outbox),
        patch("parrot.knowledge.wiki.cli.LedgerIntegrator", return_value=integrator),
    ):
        result = CliRunner().invoke(ledger, ["outbox", "integrate", "--repo-root", str(tmp_path), "--ledger-dir", str(tmp_path)])
    assert result.exit_code == code, result.output


def test_integrate_json_is_structured(tmp_path: Path) -> None:
    """Integration JSON is an array of serialized delivery reports."""
    batch = _batch()
    outbox = MagicMock()
    outbox.pending = AsyncMock(return_value=[batch])
    report = LedgerDeliveryReport(
        status="delivered", batch_id=batch.batch_id, attempts=1, remote_head="a" * 40, commit_sha="b" * 40, added=1, remaining=0
    )
    integrator = MagicMock()
    integrator.integrate = AsyncMock(return_value=report)
    with (
        patch("parrot.knowledge.wiki.cli.LedgerOutbox", return_value=outbox),
        patch("parrot.knowledge.wiki.cli.LedgerIntegrator", return_value=integrator),
    ):
        result = CliRunner().invoke(
            ledger, ["outbox", "integrate", "--repo-root", str(tmp_path), "--ledger-dir", str(tmp_path), "--json"]
        )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [report.model_dump(mode="json")]


def test_remote_only_mode_is_unsupported_without_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured remote cannot silently fall back to a local outbox."""
    monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none", lambda path_=None: (None, None, object()))
    with patch("parrot.knowledge.wiki.cli.LedgerOutbox", side_effect=AssertionError("must not construct outbox")):
        result = CliRunner().invoke(ledger, ["outbox", "prepare", "--repo-root", str(tmp_path)])
    assert result.exit_code == 4, result.output
    assert not (tmp_path / "outbox").exists()


def test_prepare_lock_busy_exits_2(tmp_path: Path) -> None:
    """A contended preparation lock maps to the retryable exit code."""
    outbox = MagicMock()
    outbox.prepare = AsyncMock(side_effect=OutboxLockedError("busy"))
    integrator = MagicMock()
    integrator.remote_event_ids = AsyncMock(return_value=set())
    git_result = MagicMock(stdout="HEAD\n")
    with (
        patch("parrot.knowledge.wiki.cli.LedgerOutbox", return_value=outbox),
        patch("parrot.knowledge.wiki.cli.LedgerIntegrator", return_value=integrator),
        patch("parrot.knowledge.wiki.cli.subprocess.run", return_value=git_result),
    ):
        result = CliRunner().invoke(
            ledger, ["outbox", "prepare", "--repo-root", str(tmp_path), "--ledger-dir", str(tmp_path)]
        )
    assert result.exit_code == 2, result.output


def test_status_never_acknowledges(tmp_path: Path) -> None:
    """Status only reads batches and leaves receipt storage untouched."""
    batch = _batch()
    outbox = MagicMock()
    outbox.status = AsyncMock(return_value={"pending_batches": 1, "pending_events": 0, "unsealed_events": 0, "truncated_tail": False})
    outbox.pending = AsyncMock(return_value=[batch])
    integrator = MagicMock()
    integrator.remote_event_ids = AsyncMock(return_value=set())
    integrator.check_feature_diff = AsyncMock(return_value=[])
    with (
        patch("parrot.knowledge.wiki.cli.LedgerOutbox", return_value=outbox),
        patch("parrot.knowledge.wiki.cli.LedgerIntegrator", return_value=integrator),
    ):
        result = CliRunner().invoke(ledger, ["outbox", "status", "--repo-root", str(tmp_path), "--ledger-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "outbox" / "receipts").exists()
    assert not hasattr(outbox, "acknowledge") or not outbox.acknowledge.called


def test_status_reports_contamination_exit_4(tmp_path: Path) -> None:
    """Canonical paths changed by a feature are reported without being changed."""
    outbox = MagicMock()
    outbox.status = AsyncMock(return_value={"pending_batches": 0, "pending_events": 0, "unsealed_events": 0, "truncated_tail": False})
    outbox.pending = AsyncMock(return_value=[])
    integrator = MagicMock()
    integrator.remote_event_ids = AsyncMock(return_value=set())
    integrator.check_feature_diff = AsyncMock(return_value=["sdd/ledger/events.jsonl"])
    with (
        patch("parrot.knowledge.wiki.cli.LedgerOutbox", return_value=outbox),
        patch("parrot.knowledge.wiki.cli.LedgerIntegrator", return_value=integrator),
    ):
        result = CliRunner().invoke(ledger, ["outbox", "status", "--repo-root", str(tmp_path), "--ledger-dir", str(tmp_path)])
    assert result.exit_code == 4, result.output
    assert "sdd/ledger/events.jsonl" in result.output
