# TASK-3397: Fix-lane lifecycle integration tests (claim → plan → close/unclaim, races, stale plans)

**Feature**: FEAT-572 — `/sdd-fix` Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3390, TASK-3391
**Assigned-to**: unassigned

---

## Context

Spec §4 Integration Tests, design research S3/S5/S8/S9. Unit tests pin each piece; these
tests pin the **lifecycle invariants the twins rely on** across planner + service + index
together: a group schedules work but every issue releases individually (S8); a stale plan
cannot close an issue another actor claimed (S3); exactly one concurrent claimant wins; a
partial fix closes only the evidenced issues and releases the rest.

Written as a NEW module rather than extending `test_ledger_index.py`'s `TestAtomicClaim`
(spec wording) so this task has no file overlap with TASK-3387; the race test mirrors
`test_exactly_one_concurrent_claimant_succeeds` but drives it through `LedgerService` and
the planner.

---

## Scope

- CREATE `tests/knowledge/wiki/test_ledger_fix_lifecycle.py` with a local real-service
  fixture and five async tests:
  `test_claim_group_then_unclaim_returns_all_to_ready`,
  `test_partial_close_releases_the_remainder`,
  `test_concurrent_plan_and_claim_race`,
  `test_stale_plan_cannot_close_a_reclaimed_issue`,
  `test_plan_reflects_ready_pool_after_release`.

**NOT in scope**: CLI (mocked or otherwise — covered by TASK-3392); twins; any source change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/knowledge/wiki/test_ledger_fix_lifecycle.py` | CREATE | lifecycle integration tests over a real `LedgerService` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.fix_planner import plan_fix_batch, FixPlan   # TASK-3389/3390
from parrot.knowledge.wiki.ledger.index import LedgerIndex                     # verified: ledger/index.py:85
from parrot.knowledge.wiki.ledger.log import LedgerLog                         # verified: ledger/log.py
from parrot.knowledge.wiki.ledger.service import LedgerService                 # verified: ledger/service.py:96
from parrot.knowledge.wiki.ledger.store import LedgerStore                     # verified: ledger/store.py
from parrot.knowledge.wiki.store import SQLitePragmaPolicy                     # verified: tests/knowledge/wiki/test_ledger_service.py:14
import asyncio; import pytest
```

### Existing Signatures to Use
```python
# LedgerService (service.py + TASK-3391)
async def open_issue(self, title, body, kind="bug", severity="minor", discovered_from="", about=None, actor="agent:sdd") -> str  # 166
async def ready_work(self, kind=None) -> list[dict]           # 199 — severity-sorted (TASK-3388)
async def claim(self, issue_id: str, actor: str) -> bool      # 209 — atomic; False when not open
async def close_issue(self, issue_id, reason, actor, resolved_by=None) -> bool   # TASK-3391 — False unless open/claimed
async def unclaim(self, issue_id, reason, actor) -> bool      # TASK-3391 — False unless claimed
async def _all_issues(self) -> list[tuple[str, dict]]         # 150 — read state incl. "resolved_by", "claimed_by"
# planner (TASK-3390)
def plan_fix_batch(rows, *, kind=None, severity=None, lane_override=None, parent_index_status=None, generated_at=None) -> FixPlan
# FixPlan.groups[i].issues[j].issue_id ; .files ; .lane

# tests/knowledge/wiki/test_ledger_service.py:17-29 — the fixture to COPY locally (do not import across test modules):
ledger_dir = tmp_path / ".parrot" / "ledger"; ledger_dir.mkdir(parents=True)
store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0))
log = LedgerLog(str(ledger_dir / "events.jsonl")); index = LedgerIndex(store, log); LedgerService(index, store, log, tmp_path)
# tests/knowledge/wiki/test_ledger_index.py:274-288 — race pattern: asyncio.gather(claim(..A), claim(..B)); sorted(results) == [False, True]
# pyproject.toml:235 testpaths = ["tests"]; async tests run without markers in this tree (see test_ledger_service.py)
```

### Does NOT Exist
- ~~a `/sdd-fix` Python runner to invoke~~ — the lane is a markdown procedure; these tests exercise the primitives it composes.
- ~~`LedgerService.close_group()` / bulk close~~ — S8: every issue closes individually.
- ~~`plan_fix_batch` claiming anything~~ — planning is a pure snapshot; claims happen through `service.claim`.
- ~~`tests/knowledge/wiki/conftest.py` ledger fixtures~~ — define the fixture locally.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "tests/knowledge/wiki/test_ledger_fix_lifecycle.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.claim",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.ready_work",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py#plan_fix_batch"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Use `about=["sym:pkg/a.py#f", ...]` so `files_for` yields files and the issues group.
- "Stale plan" = a `FixPlan` built from `ready_work()` output *before* another actor claims
  and closes; afterwards, the stale lane's `claim` returns `False` and its `close_issue`
  returns `False` — nothing changes state (S3).
- Partial close: close 3 of 5 with `resolved_by="commit:abc"`, `unclaim` the other 2, then a
  fresh `plan_fix_batch(await ready_work())` contains exactly those 2.
- Real SQLite in `tmp_path`; keep `busy_timeout_s=1.0`.

### References in Codebase
- `tests/knowledge/wiki/test_ledger_index.py:249-341` — `TestAtomicClaim`.
- `tests/sdd/test_ledger_lifecycle_acceptance.py` — the FEAT-566 lifecycle acceptance style.

---

## Implementation Blueprint

### Steps (in order)
1. Create the module with the local fixture and a `_seed_group` helper — *why*: every test needs a multi-issue connected group.
2. Write the five tests — *why*: each is a named row in spec §4 Integration Tests (plus one release-visibility test).

### `tests/knowledge/wiki/test_ledger_fix_lifecycle.py` (CREATE)
```python
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
    # FILL IN: unclaim every id → all 5 back in ready_work(); claimed_by is None for each — bounded by spec §4 row 2


async def test_partial_close_releases_the_remainder(service):
    # FILL IN: seed 5; claim all; close ids[:3] with resolved_by="commit:abc" (True each); unclaim ids[3:] (True each);
    #          fresh plan over ready_work() has exactly ids[3:]; closed ones carry resolved_by == "commit:abc" — S8


async def test_concurrent_plan_and_claim_race(service):
    (iid,) = await _seed_group(service, n=1)
    results = await asyncio.gather(service.claim(iid, "agent:lane-a"), service.claim(iid, "agent:lane-b"))
    assert sorted(results) == [False, True]
    # FILL IN: the winner's actor is recorded in claimed_by; a plan built now has zero groups


async def test_stale_plan_cannot_close_a_reclaimed_issue(service):
    (iid,) = await _seed_group(service, n=1)
    stale_plan = plan_fix_batch(await service.ready_work(), generated_at="x")   # snapshot taken by lane A
    assert await service.claim(iid, "agent:lane-b") is True                      # lane B wins the claim …
    assert await service.close_issue(iid, "fixed by B", "agent:lane-b", resolved_by="commit:b") is True
    # FILL IN: lane A, holding stale_plan, gets claim(iid) False AND close_issue(iid, ...) False; state unchanged
    #          (closed_by == "agent:lane-b", resolved_by == "commit:b") — S3 / S5


async def test_plan_reflects_ready_pool_after_release(service):
    # FILL IN: seed 3; claim 1; plan has 2 issues; unclaim it; plan has 3 — the plan is a snapshot of ready_work()
```
**Why**: the chained `about` makes transitivity part of every test; asserting on
`plan_fix_batch(await ready_work())` after each step is how the twins actually observe the
ledger, so these tests model the lane's real control loop.

### FILL IN checklist
- [ ] 5 test bodies marked FILL IN — bounded by spec §4 Integration Tests rows and S3/S5/S8

---

## Acceptance Criteria

- [ ] A full claim/release cycle over a 5-issue group returns all five to `ready_work()`.
- [ ] Partial close (3 of 5, with `resolved_by`) plus release of the other 2 leaves exactly those 2 in the next plan.
- [ ] Exactly one of two concurrent claimants wins.
- [ ] A stale plan's holder cannot claim or close an issue another actor closed (S3); the closer's evidence is preserved.
- [ ] `pytest tests/knowledge/wiki/test_ledger_fix_lifecycle.py -v` green.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_fix_lifecycle.py -q`

---

## Test Specification

```python
async def test_claim_group_then_unclaim_returns_all_to_ready(service): ...
async def test_partial_close_releases_the_remainder(service): ...
async def test_concurrent_plan_and_claim_race(service): ...
async def test_stale_plan_cannot_close_a_reclaimed_issue(service): ...
async def test_plan_reflects_ready_pool_after_release(service): ...
```

---

## Agent Instructions

1. **Read the spec** (§2 Overview — "The plan is a snapshot; the claim is authoritative", "A group schedules work; every issue … individually"; §4 Integration Tests).
2. **Check dependencies** — TASK-3390 and TASK-3391 completed.
3. **Verify the Codebase Contract** — `unclaim`, `close_issue(resolved_by=)`, `plan_fix_batch` importable.
4. **Update status** in `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"in-progress"`.
5. **Implement** the module.
6. **Verify** the Validation Command (`PYTHONPATH=packages/ai-parrot/src` in a worktree).
7. **Move this file** to `sdd/tasks/completed/TASK-3397-fix-lane-lifecycle-integration-tests.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator, sequential-loop fallback — `parrot-sdd-coder`
roster was empty, `fallback_reason: suspension_history_unavailable`)
**Date**: 2026-09-19
**Notes**: Created `test_ledger_fix_lifecycle.py` with a local real-`LedgerService` fixture
(SQLite in `tmp_path`) and the five lifecycle tests exactly per blueprint: full claim/unclaim
cycle over a 5-issue chained group; partial close (3 of 5, `resolved_by`) + release of the
other 2, verified against a fresh `plan_fix_batch(ready_work())`; concurrent claim race
(`asyncio.gather`, exactly one winner); stale-plan-cannot-close-a-reclaimed-issue (S3); plan
reflects the ready pool after release. All five passed on first implementation, no debugging
needed.

Validation: `pytest tests/knowledge/wiki/test_ledger_fix_lifecycle.py -v` → 5 passed. `ruff check --select E9,F63,F7,F82` clean.

**Deviations from spec**: none
