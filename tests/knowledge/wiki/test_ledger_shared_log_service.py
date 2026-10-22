"""FEAT-694 M2 — LedgerService shared-log import/export."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy


@pytest.fixture
def two_ledgers(tmp_path: Path) -> tuple[LedgerService, LedgerService, Path]:
    """Return isolated local/foreign services that share a temporary checkout."""

    def build(name: str) -> LedgerService:
        ledger_dir = tmp_path / name / ".parrot" / "ledger"
        ledger_dir.mkdir(parents=True)
        store = LedgerStore(
            ledger_dir / "ledger.db",
            wiki_name="ledger",
            sqlite_policy=SQLitePragmaPolicy(busy_timeout_ms=200),
        )
        log = LedgerLog(str(ledger_dir / "events.jsonl"))
        return LedgerService(LedgerIndex(store, log), store, log, tmp_path / name)

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    return build("local"), build("foreign"), checkout


async def test_import_keeps_cursor_valid(
    two_ledgers: tuple[LedgerService, LedgerService, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import uses incremental sync and never invokes the destructive rebuild path."""
    local, foreign, checkout = two_ledgers
    await foreign.open_issue("Foreign", "body", discovered_from="spec:FEAT-694")
    await foreign.export_shared_log(checkout)
    rebuild = AsyncMock()
    monkeypatch.setattr(local.index, "_rebuild_locked_with_cursor", rebuild)

    report = await local.import_shared_log(checkout)

    assert report.added == 1
    assert report.synced_events == 1
    assert rebuild.await_count == 0
    assert len(await local.ready_work()) == 1


async def test_import_detects_claim_conflict(two_ledgers: tuple[LedgerService, LedgerService, Path]) -> None:
    """Keep the local first claimant and surface the imported conflicting claimant."""
    local, foreign, checkout = two_ledgers
    issue_id = await local.open_issue("Shared", "body", discovered_from="spec:FEAT-694")
    assert await local.claim(issue_id, "task:local")
    await foreign.open_issue("Shared", "body", discovered_from="spec:FEAT-694")
    assert await foreign.claim(issue_id, "task:foreign")
    await foreign.export_shared_log(checkout)

    report = await local.import_shared_log(checkout)

    assert [
        (conflict.issue_id, conflict.local_claimed_by, conflict.foreign_claimed_by)
        for conflict in report.claim_conflicts
    ] == [(issue_id, "task:local", "task:foreign")]
    assert dict(await local._all_issues())[issue_id]["claimed_by"] == "task:local"


async def test_import_ignores_superseded_claim(two_ledgers: tuple[LedgerService, LedgerService, Path]) -> None:
    """A committed "A claims, A unclaims, B claims" history reports no conflict (issue:fe3480881432)."""
    local, foreign, checkout = two_ledgers
    issue_id = await local.open_issue("Shared", "body", discovered_from="spec:FEAT-694")
    await foreign.open_issue("Shared", "body", discovered_from="spec:FEAT-694")
    assert await foreign.claim(issue_id, "task:a")
    assert await foreign.unclaim(issue_id, "handing off", "task:a")
    assert await foreign.claim(issue_id, "task:b")
    await foreign.export_shared_log(checkout)
    # The local machine agrees with the live committed claimant, so nothing is in conflict.
    assert await local.claim(issue_id, "task:b")

    report = await local.import_shared_log(checkout)

    # Before the superseded-claim filter, task:a's revoked claim was reported against task:b.
    assert report.claim_conflicts == []
    assert dict(await local._all_issues())[issue_id]["claimed_by"] == "task:b"


async def test_import_index_busy_is_soft(
    two_ledgers: tuple[LedgerService, LedgerService, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A busy index leaves the durable import intact and reports a soft failure."""
    local, foreign, checkout = two_ledgers
    await foreign.open_issue("Foreign", "body", discovered_from="spec:FEAT-694")
    await foreign.export_shared_log(checkout)
    monkeypatch.setattr(local.index, "sync", AsyncMock(side_effect=WikiStoreBusy("ledger.db", "sync", 0.2)))

    report = await local.import_shared_log(checkout)

    assert report.index_busy is True
    assert report.synced_events == 0
    assert Path(local.log.path).exists()
    assert len(Path(local.log.path).read_text(encoding="utf-8").splitlines()) == 1


async def test_audit_reports_shared_log_block(two_ledgers: tuple[LedgerService, LedgerService, Path]) -> None:
    """Audit reports the committed-log drift and marker status without changing old keys."""
    local, foreign, checkout = two_ledgers
    await local.open_issue("Local", "body", discovered_from="spec:FEAT-694")
    await foreign.open_issue("Foreign", "body", discovered_from="spec:FEAT-694")
    await foreign.export_shared_log(checkout)
    local.shared_root = checkout

    audit = await local.audit()

    shared = audit["shared_log"]
    assert shared["path"] == str(checkout / "sdd" / "ledger" / "events.jsonl")
    assert shared["exists"] is True
    assert shared["local_only_events"] == 1
    assert shared["committed_unknown_events"] == 1
    assert shared["marker"] == "missing"
