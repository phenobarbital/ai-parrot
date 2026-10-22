"""Regression cases for FEAT-627 LedgerService.list_issues."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
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


async def _seed(service: LedgerService) -> dict[str, str]:
    ids = {
        "open_minor": await service.open_issue("Open minor", "b", "bug", "minor", "t:1", ["sym:a/x.py#f"]),
        "open_major": await service.open_issue("Open major", "b", "tech_debt", "major", "t:2", ["sym:b/y.py#g"]),
        "claimed": await service.open_issue("Claimed", "b", "bug", "minor", "t:3", ["sym:a/z.py#h"]),
        "closed": await service.open_issue("Closed", "b", "bug", "minor", "t:4", ["sym:a/c.py#i"]),
    }
    assert await service.claim(ids["claimed"], "agent:x")
    assert await service.close_issue(ids["closed"], "done", "agent:x")
    return ids


async def test_status_filters_and_order(service: LedgerService) -> None:
    ids = await _seed(service)
    rows = await service.list_issues()
    got = [r["issue_id"] for r in rows]
    assert set(got) == {ids["open_minor"], ids["open_major"], ids["claimed"]}
    assert got[0] == ids["open_major"]
    assert got[1:] == sorted(got[1:])
    claimed = next(r for r in rows if r["issue_id"] == ids["claimed"])
    assert claimed["claimed_by"] == "agent:x"
    closed = await service.list_issues(["closed"])
    assert [r["issue_id"] for r in closed] == [ids["closed"]]
    assert await service.list_issues([]) == []


async def test_kind_and_about_prefix_filters(service: LedgerService) -> None:
    ids = await _seed(service)
    rows = await service.list_issues(kind="tech_debt")
    assert [r["issue_id"] for r in rows] == [ids["open_major"]]
    rows = await service.list_issues(about_prefix="sym:a/")
    assert {r["issue_id"] for r in rows} == {ids["open_minor"], ids["claimed"]}
    assert await service.list_issues(about_prefix="sym:nope") == []


async def test_ready_work_unchanged(service: LedgerService) -> None:
    ids = await _seed(service)
    rows = await service.ready_work()
    assert {r["issue_id"] for r in rows} == {ids["open_minor"], ids["open_major"]}
