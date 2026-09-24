# TASK-3391: `LedgerService.unclaim()`, fail-closed `close_issue(resolved_by=)`, `feature_index_status()`

**Feature**: FEAT-572 — `/sdd-fix` Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3387, TASK-3388
**Assigned-to**: unassigned

---

## Context

Spec §1 Problem 4 ("Closing an issue loses the evidence"), §3 Module 3, design research
S4/S5. `IssueClosedPayload.resolved_by` has existed since FEAT-566 and `_apply_issue_closed`
persists it, but `LedgerService.close_issue()` never passes it — every close is an
unfalsifiable assertion. Worse, `close_issue()` appends and returns `True` for **any** id
(`service.py:239-246`) while the reducer silently ignores a missing issue, so closing a
nonexistent or already-closed issue reports success and leaves a permanent no-op event.

This task adds the three service methods the CLI (TASK-3392), the MCP tool (TASK-3393) and
the lifecycle tests (TASK-3397) build on. It depends on TASK-3387 for the
`"issue.unclaimed"` Literal member (Pydantic rejects the event otherwise) and on TASK-3388
because both edit `service.py` and `test_ledger_service.py`.

---

## Scope

- `close_issue(self, issue_id, reason, actor, resolved_by: str | None = None) -> bool`:
  returns `False` **without appending** when the issue does not exist or its status is not
  `open`/`claimed` (S5); carries `resolved_by` into the payload only when given, so existing
  callers' events are byte-identical.
- `unclaim(self, issue_id, reason, actor) -> bool`: appends `issue.unclaimed` and syncs;
  returns `False` without appending unless the issue exists with status `claimed`
  (symmetry with S5 — avoids permanent no-op events).
- `feature_index_status(self, feature_ids: Collection[str]) -> dict[str, str | None]`:
  one scan of `<shared_root>/sdd/tasks/index/*.json`; maps each requested `feature_id` to
  its `completed_at`; features with no index file are **absent**; unreadable/malformed files
  are skipped.
- A private `_issue_state(issue_id)` reader used by the two guards.
- Tests in `tests/knowledge/wiki/test_ledger_service.py`.

**NOT in scope**: CLI flags (TASK-3392), MCP tool (TASK-3393), the planner (TASK-3389/3390),
any change to `ready_work()` (TASK-3388) or to `index.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `_issue_state`, new `close_issue` signature + guard, `unclaim`, `feature_index_status` |
| `tests/knowledge/wiki/test_ledger_service.py` | MODIFY | `TestCloseEvidence`, `TestUnclaim`, `TestFeatureIndexStatus` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.service import LedgerService, _issue_dict   # verified: ledger/service.py:96,78
from parrot.knowledge.wiki.ledger.events import LedgerEvent                   # verified: ledger/events.py:83
from parrot.knowledge.wiki.ledger.index import _decode_issue_body             # verified: imported at service.py:26
from collections.abc import Collection                                        # stdlib
from unittest.mock import patch                                               # stdlib (test spy)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
import asyncio, json, logging; from pathlib import Path; from typing import Any          # 14-18
from parrot.knowledge.wiki.ledger.events import (IssueKind, IssueOpenedPayload, LedgerEvent, SEVERITY_ORDER, compute_issue_id)  # 20-25 (+TASK-3388)
from parrot.knowledge.wiki.ledger.index import LedgerIndex, _decode_issue_body            # 26
logger = logging.getLogger(__name__)                                                     # 36
class LedgerService:
    self.index; self.store; self.log; self.shared_root: Path                              # 108-111
    async def _sync_best_effort(self) -> None                                             # 143
    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]:                      # 150 — pattern:
        async with self.store._read() as conn:
            async with conn.execute("SELECT concept_id, body FROM pages WHERE category = 'issue'") as cur: rows = await cur.fetchall()
    async def open_issue(..., severity: str = "minor", discovered_from: str = "", about=None, actor="agent:sdd") -> str  # 166
    async def ready_work(self, kind=None) -> list[dict]                                    # 199
    async def claim(self, issue_id: str, actor: str) -> bool                               # 209
    async def acknowledge(self, issue_id: str, reason: str, actor: str) -> bool            # 213-233 — the "guard then append" shape
    async def close_issue(self, issue_id: str, reason: str, actor: str) -> bool:           # 235-245 ← REPLACE
        event = LedgerEvent(kind="issue.closed", subject=issue_id, actor=actor, payload={"reason": reason, "closed_by": actor})
        await asyncio.to_thread(self.log.append, event); await self._sync_best_effort(); return True
    async def get_context(self, file_paths: list[str], max_tokens: int = 3000) -> str      # 247
    async def merge_blockers(self, feature_id: str) -> list[dict]                          # 280 — calls asyncio.to_thread(self._feature_task_ids, ...)
    def _feature_task_ids(self, feature_id: str) -> list[str]:                             # 311-323 — the directory-scan pattern:
        index_dir = self.shared_root / "sdd" / "tasks" / "index"; if not index_dir.exists(): return []
        for index_path in index_dir.glob("*.json"):
            try: data = json.loads(index_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): continue
    async def export_snapshot(self, dest: Path) -> bool                                    # 325

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
class IssueClosedPayload(BaseModel): reason: str; closed_by: str; resolved_by: str | None = None   # 49-52
class IssueUnclaimedPayload(BaseModel): unclaimed_by: str; reason: str                             # TASK-3387
# index.py:209-219 _apply_issue_closed sets state["resolved_by"] = payload.resolved_by

# tests/knowledge/wiki/test_ledger_service.py
@pytest.fixture ledger_service(tmp_path) -> LedgerService (shared_root == tmp_path)      # 17-29
class TestAcknowledgeAndClose:  async def test_close_issue(self, ledger_service)          # 93, 118-125
class TestContextAndBlockers:  test_merge_blockers_scoped_to_requesting_feature_only writes tmp_path/sdd/tasks/index/*.json  # 150-160 — copy this setup
class TestExportSnapshot:                                                                 # 188 ← insert the new classes ABOVE this line
```

### Does NOT Exist
- ~~`LedgerService.unclaim()`~~, ~~`feature_index_status()`~~, ~~`_issue_state()`~~ — this task adds them.
- ~~`close_issue(..., resolved_by=)`~~ — parameter added here; today's payload is `{"reason", "closed_by"}` only.
- ~~`LedgerService._read_issue`~~ — that reader is on `LedgerIndex` and needs a connection; the service reads via `self.store._read()` (pattern at `_all_issues`).
- ~~`LedgerIndex.unclaim_issue()` atomic method~~ — unclaim is a plain log append + best-effort sync, like `close_issue`; the claim race is handled by `claim_issue` alone.
- ~~`feature_index_status` returning `None` for missing features~~ — missing features are ABSENT from the dict (caller distinguishes open/unknown).
- ~~`IssueClosedPayload(...).model_dump()` for the close payload~~ — build the dict by hand and add `resolved_by` only when not `None`, so pre-existing callers' events stay byte-identical.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_service.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.close_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.acknowledge",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService._all_issues",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService._feature_task_ids",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService._sync_best_effort",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#_issue_dict",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#IssueClosedPayload",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#_decode_issue_body"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Deliberate behaviour change to a FEAT-566 API** (spec §7): `close_issue` now guards.
  Callers audited: `cli.py:2740` (prints "Could not close" on `False`, exit 1 — correct),
  `tools.py:716` (returns `{"success": False}` — correct), `/sdd-task --from-issue` never
  calls close. The existing `test_close_issue` stays valid.
- Sync **before** the guard read (`await self._sync_best_effort()`), as `ready_work` does,
  so a claim appended by another writer is visible.
- `feature_index_status` scans once for all ids — `test_feature_index_status_scans_index_dir_once`
  spies on `Path.glob`.
- Log append stays off-thread: `await asyncio.to_thread(self.log.append, event)`.
- FEAT-569's TASK-3354 (`LedgerService.from_dir()`) also edits `service.py`; if it lands
  first, re-verify anchors — the methods here are independent of it.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:213-233` — `acknowledge`: guard-then-append shape to copy.
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:311-323` — `_feature_task_ids`: directory scan tolerance to copy.

---

## Implementation Blueprint

### Steps (in order)
1. Add `Collection` import and the `_issue_state` helper — *why*: both guards need a targeted read; `_all_issues()` would scan every page per close.
2. Replace `close_issue` — *why*: S5 guard + S4 evidence; payload built by hand so `resolved_by=None` callers are unchanged.
3. Add `unclaim` after `close_issue` — *why*: same shape, guarded on `claimed`.
4. Add `feature_index_status` + sync helper after `_feature_task_ids` — *why*: sibling scan, one glob.
5. Add the three test classes above `TestExportSnapshot`; run the file.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'from typing import Any' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py)
# AFTER — insert ABOVE `from typing import Any` (verified: service.py:18):
from collections.abc import Collection
```
```python
# occurrences: 1 (verified: grep -cF 'async def close_issue(self, issue_id: str, reason: str, actor: str) -> bool:' …/service.py)
# REPLACE the whole close_issue method (verified: service.py:235-245) with the two methods below:
    async def _issue_state(self, issue_id: str) -> dict[str, Any] | None:
        """Read one issue's decoded state (``None`` when no page exists); reads via ``store._read()`` like ``_all_issues``."""
        async with self.store._read() as conn:
            async with conn.execute("SELECT body FROM pages WHERE concept_id = ?", (issue_id,)) as cur:
                row = await cur.fetchone()
        return _decode_issue_body(row[0]) if row else None

    async def close_issue(self, issue_id: str, reason: str, actor: str, resolved_by: str | None = None) -> bool:
        """Close an issue, recording the resolver and the evidence reference (FEAT-572 S4/S5).

        ``resolved_by`` is e.g. ``commit:<sha>`` (fast lane) or ``task:TASK-<NNN>`` (SDD lane)
        and is carried into ``IssueClosedPayload.resolved_by``. Returns ``False`` WITHOUT
        appending when the issue does not exist or its status is not ``open``/``claimed`` —
        a double close is detectable instead of silent.
        """
        await self._sync_best_effort()
        state = await self._issue_state(issue_id)
        if state is None or state.get("status") not in ("open", "claimed"):
            logger.warning("Refusing issue.closed for %s: missing or status=%r", issue_id, state and state.get("status"))
            return False
        payload: dict[str, Any] = {"reason": reason, "closed_by": actor}
        if resolved_by is not None:
            payload["resolved_by"] = resolved_by
        event = LedgerEvent(kind="issue.closed", subject=issue_id, actor=actor, payload=payload)
        await asyncio.to_thread(self.log.append, event)
        await self._sync_best_effort()
        return True

    async def unclaim(self, issue_id: str, reason: str, actor: str) -> bool:
        """Append ``issue.unclaimed``, returning a claimed issue to the ready pool (FEAT-572 M3).

        Returns ``False`` without appending unless the issue exists with status ``claimed``.
        """
        await self._sync_best_effort()
        state = await self._issue_state(issue_id)
        if state is None or state.get("status") != "claimed":
            return False
        event = LedgerEvent(
            kind="issue.unclaimed", subject=issue_id, actor=actor, payload={"unclaimed_by": actor, "reason": reason}
        )
        await asyncio.to_thread(self.log.append, event)
        await self._sync_best_effort()
        return True
```
```python
# occurrences: 1 (verified: grep -cF '    async def export_snapshot(self, dest: Path) -> bool:' …/service.py)
# BEFORE — insert ABOVE `    async def export_snapshot(...)` (verified: service.py:325), i.e. right after _feature_task_ids:
    def _feature_index_status_sync(self, wanted: set[str]) -> dict[str, str | None]:
        """Blocking half of :meth:`feature_index_status` — one ``glob`` over the index directory."""
        index_dir = self.shared_root / "sdd" / "tasks" / "index"
        result: dict[str, str | None] = {}
        if not wanted or not index_dir.exists():
            return result
        for index_path in index_dir.glob("*.json"):
            # FILL IN: json.loads with the same (OSError, json.JSONDecodeError) tolerance as _feature_task_ids;
            #          if data.get("feature_id") in wanted: result[fid] = data.get("completed_at") — bounded by TestFeatureIndexStatus
        return result

    async def feature_index_status(self, feature_ids: Collection[str]) -> dict[str, str | None]:
        """Map each ``FEAT-<NNN>`` to its per-spec index ``completed_at`` (``None`` = still open).

        A feature with no index file is ABSENT from the result — the caller distinguishes
        "open" (present, ``None``) from "unknown" (absent). Scans the directory once.
        """
        return await asyncio.to_thread(self._feature_index_status_sync, set(feature_ids))
```
**Why this shape**: `acknowledge` already models "guard, then append, then best-effort sync"
— both new methods copy it. The hand-built close payload is what keeps
`test_close_issue_without_resolved_by_unchanged` honest at the event level. The sync/async
split mirrors `_feature_task_ids` / `merge_blockers`.

### `tests/knowledge/wiki/test_ledger_service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'class TestExportSnapshot:' tests/knowledge/wiki/test_ledger_service.py)
# BEFORE — insert ABOVE `class TestExportSnapshot:` (verified: :188). Add `from unittest.mock import patch` and `from pathlib import Path` at top.


async def _state_of(service: LedgerService, issue_id: str) -> dict:
    return dict(await service._all_issues())[issue_id]


class TestCloseEvidence:
    async def test_close_issue_persists_resolved_by(self, ledger_service):
        issue_id = await ledger_service.open_issue(title="Evidence", body="b", discovered_from="task:TASK-1")
        assert await ledger_service.close_issue(issue_id, "fixed", "agent:sdd-fix", resolved_by="commit:abc123") is True
        assert (await _state_of(ledger_service, issue_id))["resolved_by"] == "commit:abc123"

    async def test_close_issue_without_resolved_by_unchanged(self, ledger_service):
        # FILL IN: close without resolved_by → True, state["resolved_by"] is None, and the appended event payload
        #          (last line of ledger_service.log.path) has exactly the keys {"reason", "closed_by"}
    async def test_close_issue_rejects_unknown_issue(self, ledger_service):
        # FILL IN: close("issue:nope", ...) is False and events.jsonl did not grow (compare line counts) — S5
    async def test_close_issue_rejects_already_closed(self, ledger_service):
        # FILL IN: open → close → close again is False; log grew by exactly 2 events total (opened, closed) — S5


class TestUnclaim:
    async def test_unclaim_appends_event_and_syncs(self, ledger_service):
        issue_id = await ledger_service.open_issue(title="Claim me", body="b", discovered_from="task:TASK-1")
        assert await ledger_service.claim(issue_id, "agent:sdd-fix") is True
        assert await ledger_service.ready_work() == []
        assert await ledger_service.unclaim(issue_id, "not fixed", "agent:sdd-fix") is True
        assert [r["issue_id"] for r in await ledger_service.ready_work()] == [issue_id]

    async def test_unclaim_on_open_issue_returns_false_without_appending(self, ledger_service):
        # FILL IN: open (no claim) → unclaim is False; log line count unchanged


class TestFeatureIndexStatus:
    def _write_index(self, tmp_path, name, feature_id, completed_at):
        index_dir = tmp_path / "sdd" / "tasks" / "index"
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / f"{name}.json").write_text(json.dumps({"feature_id": feature_id, "completed_at": completed_at, "tasks": []}), encoding="utf-8")

    async def test_feature_index_status_scans_index_dir_once(self, ledger_service, tmp_path):
        self._write_index(tmp_path, "a", "FEAT-1", None); self._write_index(tmp_path, "b", "FEAT-2", "2026-09-15T00:00:00Z")
        (tmp_path / "sdd" / "tasks" / "index" / "broken.json").write_text("{not json", encoding="utf-8")
        with patch.object(Path, "glob", autospec=True, side_effect=Path.glob) as spy:
            status = await ledger_service.feature_index_status(["FEAT-1", "FEAT-2", "FEAT-3"])
        assert spy.call_count == 1
        # FILL IN: assert status == {"FEAT-1": None, "FEAT-2": "2026-09-15T00:00:00Z"}
    async def test_feature_index_status_omits_features_without_index(self, ledger_service, tmp_path):
        # FILL IN: only FEAT-1 written; result for ["FEAT-1", "FEAT-9"] has no "FEAT-9" key (absent ≠ None)
```
**Why**: the `_state_of` helper reads through the public `_issue_dict` projection, which is
how the CLI and MCP surfaces will see `resolved_by`. Counting log lines is the only honest
"appends nothing" assertion.

### FILL IN checklist
- [ ] `service.py::_feature_index_status_sync` — loop body; bounded by `TestFeatureIndexStatus`
- [ ] `test_ledger_service.py` — 6 test bodies marked FILL IN

---

## Acceptance Criteria

- [ ] `close_issue(..., resolved_by="commit:<sha>")` persists `resolved_by`, readable via `_issue_dict`.
- [ ] `close_issue` without `resolved_by` appends a payload with exactly `{"reason", "closed_by"}` — existing callers unchanged.
- [ ] `close_issue` returns `False` and appends nothing for an unknown issue or one not `open`/`claimed`; double close detectable (S5).
- [ ] `unclaim` appends `issue.unclaimed` and the issue reappears in `ready_work()`; returns `False` unless status is `claimed`.
- [ ] `feature_index_status` scans `sdd/tasks/index/` once per call; malformed files skipped; features without an index are absent.
- [ ] Existing `test_close_issue` still passes.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_ledger_service.py -v`
- [ ] `ruff check` and `black --check -l 120` clean on `service.py`.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_service.py -q`
- `pytest tests/knowledge/wiki/test_cli_ledger.py::test_ledger_close_command -q`

---

## Test Specification

```python
class TestCloseEvidence:       # 4 tests
class TestUnclaim:             # 2 tests
class TestFeatureIndexStatus:  # 2 tests
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 3 skeletons, §7 "`close_issue` is currently unconditional", "Unknown parent ≠ open parent").
2. **Check dependencies** — TASK-3387 and TASK-3388 completed.
3. **Verify the Codebase Contract** — anchors must still occur exactly once; `"issue.unclaimed"` must be in the Literal.
4. **Update status** in `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"in-progress"`.
5. **Implement** from the blueprint; signatures are fixed by spec §2.
6. **Verify** the Validation Commands (`PYTHONPATH=packages/ai-parrot/src` in a worktree).
7. **Move this file** to `sdd/tasks/completed/TASK-3391-service-unclaim-close-evidence-index-status.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (native sonnet coder, attempt_uid bbd1f920da354dc69e896b8b31055d88)
**Date**: 2026-09-19
**Notes**: `close_issue(resolved_by=)` now fail-closed (guards on open/claimed status via a shared
`_issue_state()` helper before appending); new `unclaim()` guarded on `status == claimed`; new
`feature_index_status()` does a single glob scan of `sdd/tasks/index/*.json`, skips malformed
files, omits features with no index file from the result. Added `TestCloseEvidence`(4) +
`TestUnclaim`(2) + `TestFeatureIndexStatus`(2) tests, all using the tmp_path-scoped
`ledger_service` fixture (isolated per-test log) rather than the live, shared
`sdd/ledger/issues.jsonl` snapshot — sidesteps the count-based flakiness flagged for
TASK-3389/TASK-3390.
Validation: `pytest tests/knowledge/wiki/test_ledger_service.py tests/knowledge/wiki/test_cli_ledger.py -q` → 53 passed. `ruff check` clean; `black` applied by the merge-time engine formatter.
Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 203.3s · Tokens: n/a (native, no usage telemetry)

**Deviations from spec**: none
