"""Tests for opening an SDD ledger without a checkout root."""

from parrot.knowledge.wiki.ledger.service import LedgerService


async def test_from_dir_roundtrip_without_git(tmp_path):
    """Create and use a ledger directory that has no git metadata."""
    ledger_dir = tmp_path / "srv" / ".parrot" / "ledger"

    svc = LedgerService.from_dir(ledger_dir)

    assert svc.shared_root == (tmp_path / "srv").resolve()
    issue_id = await svc.open_issue(
        title="t",
        body="b",
        kind="bug",
        severity="minor",
        discovered_from="spec:FEAT-569",
        about=[],
        actor="human:test",
    )
    assert any(issue["issue_id"] == issue_id for issue in await svc.ready_work())
    assert await svc.claim(issue_id, "agent:test") is True
    assert await svc.close_issue(issue_id, "done", "agent:test") is True
    assert (ledger_dir / "ledger.db").exists()
    assert (ledger_dir / "events.jsonl").exists()


async def test_merge_blockers_empty_without_index(tmp_path):
    """Return no blockers when the derived root has no SDD task index."""
    svc = LedgerService.from_dir(tmp_path / ".parrot" / "ledger")

    assert await svc.merge_blockers("FEAT-999") == []
