"""Lifecycle integration tests for the ledger fix lane (FEAT-572 §4): claim, plan, close by evidence, release, races."""

from __future__ import annotations

import asyncio

import pytest

from parrot.knowledge.wiki.ledger.fix_planner import plan_fix_batch
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import SQLitePragmaPolicy

ACTOR = "agent:sdd-fix"


@pytest.fixture
def service(tmp_path) -> LedgerService:
    ledger_dir = tmp_path / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0))
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    return LedgerService(LedgerIndex(store, log), store, log, tmp_path)


async def _seed_group(service: LedgerService, n: int = 5) -> list[str]:
    """n minor tech_debt issues chained through shared files so they form ONE connected group."""
    ids = []
    for i in range(n):
        about = [f"sym:pkg/mod_{i}.py#f", f"sym:pkg/mod_{i + 1}.py#g"]  # mod_i ↔ mod_{i+1} chains transitively
        ids.append(await service.open_issue(title=f"Issue {i}", body="b", kind="tech_debt", about=about, discovered_from="spec:FEAT-1"))
    return ids


async def _state(service: LedgerService, issue_id: str) -> dict:
    return dict(await service._all_issues())[issue_id]


async def test_claim_group_then_unclaim_returns_all_to_ready(service):
    ids = await _seed_group(service)
    plan = plan_fix_batch(await service.ready_work(), generated_at="x")
    assert len(plan.groups) == 1 and len(plan.groups[0].issues) == 5
    for iid in ids:
        assert await service.claim(iid, ACTOR) is True
    assert await service.ready_work() == []
    for iid in ids:
        assert await service.unclaim(iid, "releasing", ACTOR) is True
    ready_ids = {row["issue_id"] for row in await service.ready_work()}
    assert ready_ids == set(ids)
    for iid in ids:
        state = await _state(service, iid)
        assert state["claimed_by"] is None


async def test_partial_close_releases_the_remainder(service):
    ids = await _seed_group(service)
    for iid in ids:
        assert await service.claim(iid, ACTOR) is True
    for iid in ids[:3]:
        assert await service.close_issue(iid, "fixed", ACTOR, resolved_by="commit:abc") is True
    for iid in ids[3:]:
        assert await service.unclaim(iid, "releasing", ACTOR) is True
    plan = plan_fix_batch(await service.ready_work(), generated_at="x")
    plan_issue_ids = {issue.issue_id for group in plan.groups for issue in group.issues}
    assert plan_issue_ids == set(ids[3:])
    for iid in ids[:3]:
        state = await _state(service, iid)
        assert state["resolved_by"] == "commit:abc"


async def test_concurrent_plan_and_claim_race(service):
    (iid,) = await _seed_group(service, n=1)
    results = await asyncio.gather(service.claim(iid, "agent:lane-a"), service.claim(iid, "agent:lane-b"))
    assert sorted(results) == [False, True]
    state = await _state(service, iid)
    assert state["claimed_by"] in ("agent:lane-a", "agent:lane-b")
    plan = plan_fix_batch(await service.ready_work(), generated_at="x")
    assert len(plan.groups) == 0


async def test_stale_plan_cannot_close_a_reclaimed_issue(service):
    (iid,) = await _seed_group(service, n=1)
    stale_plan = plan_fix_batch(await service.ready_work(), generated_at="x")  # snapshot taken by lane A
    assert await service.claim(iid, "agent:lane-b") is True  # lane B wins the claim …
    assert await service.close_issue(iid, "fixed by B", "agent:lane-b", resolved_by="commit:b") is True
    assert len(stale_plan.groups) == 1  # the snapshot lane A holds is unaffected by lane B's actions
    assert await service.claim(iid, "agent:lane-a") is False
    assert await service.close_issue(iid, "fixed by A", "agent:lane-a", resolved_by="commit:a") is False
    state = await _state(service, iid)
    assert state["closed_by"] == "agent:lane-b"
    assert state["resolved_by"] == "commit:b"


async def test_plan_reflects_ready_pool_after_release(service):
    ids = await _seed_group(service, n=3)
    assert await service.claim(ids[0], ACTOR) is True
    plan = plan_fix_batch(await service.ready_work(), generated_at="x")
    plan_issue_ids = {issue.issue_id for group in plan.groups for issue in group.issues}
    assert plan_issue_ids == set(ids[1:])
    assert await service.unclaim(ids[0], "releasing", ACTOR) is True
    plan = plan_fix_batch(await service.ready_work(), generated_at="x")
    plan_issue_ids = {issue.issue_id for group in plan.groups for issue in group.issues}
    assert plan_issue_ids == set(ids)
