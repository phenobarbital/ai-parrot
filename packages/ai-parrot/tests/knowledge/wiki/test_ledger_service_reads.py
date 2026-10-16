"""FEAT-689 M1 — LedgerService single-issue reads and severity filter."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService, normalize_issue_id
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy


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


def test_normalize_issue_id() -> None:
    """Bare hex gets the prefix; prefixed ids and whitespace are handled."""
    assert normalize_issue_id("abc123") == "issue:abc123"
    assert normalize_issue_id("issue:abc123") == "issue:abc123"
    assert normalize_issue_id("  abc123 \n") == "issue:abc123"


async def test_get_issue_includes_body(service: LedgerService) -> None:
    """get_issue returns every _issue_dict key plus body; bare hex id resolves."""
    issue_id = await service.open_issue("T", "the body", "bug", "major", "t:1", ["sym:a.py#f"])

    prefixed = await service.get_issue(issue_id)
    bare = await service.get_issue(issue_id.removeprefix("issue:"))

    assert prefixed is not None
    assert bare is not None
    assert prefixed["body"] == "the body"
    assert bare["body"] == "the body"
    assert set(prefixed) == {
        "issue_id",
        "title",
        "status",
        "kind",
        "severity",
        "acknowledged",
        "discovered_from",
        "about",
        "claimed_by",
        "closed_by",
        "closed_reason",
        "resolved_by",
        "body",
    }


async def test_get_issue_unknown_returns_none(service: LedgerService) -> None:
    """Unknown id returns None."""
    assert await service.get_issue("issue:000000000000") is None


async def test_issue_history_order_and_filter(service: LedgerService) -> None:
    """Open, claim, close history stays ordered and excludes other issues."""
    issue_id = await service.open_issue("First", "body", "bug", "major", "t:1", ["sym:a.py#f"])
    await service.open_issue("Second", "body", "bug", "minor", "t:2", ["sym:b.py#f"])
    assert await service.claim(issue_id, "agent:test")
    assert await service.close_issue(issue_id, "done", "agent:test")

    history = await service.issue_history(issue_id.removeprefix("issue:"))

    assert [event["kind"] for event in history] == ["issue.opened", "issue.claimed", "issue.closed"]
    assert all(set(event) == {"event_id", "kind", "actor", "ts", "payload"} for event in history)
    assert await service.issue_history("issue:000000000000") == []


async def test_list_issues_severity_filter(service: LedgerService) -> None:
    """severity="major" keeps only major issues; omitted keeps all."""
    major = await service.open_issue("Major", "body", "bug", "major", "t:1", ["sym:a.py#f"])
    minor = await service.open_issue("Minor", "body", "bug", "minor", "t:2", ["sym:b.py#f"])

    assert [row["issue_id"] for row in await service.list_issues(severity="major")] == [major]
    assert {row["issue_id"] for row in await service.list_issues()} == {major, minor}
