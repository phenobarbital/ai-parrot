# TASK-3387: `issue.unclaimed` event kind, payload model and index reducer

**Feature**: FEAT-572 — `/sdd-fix` Ledger-Driven Fix Lane
**Spec**: `sdd/specs/sdd-fix-ledger-lane.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview ("Three surgical additions") and §3 Module 2. Today a claimed issue has
no way back to the ready pool: `LedgerEventKind` is a closed Literal of 11 members, and the
only status-changing kinds after `issue.claimed` are `issue.closed` and `issue.superseded`,
both terminal. `/sdd-fix` (Module 5) must release every claimed-but-unfixed issue, so the
ledger needs a twelfth event kind that reverts `claimed → open` and clears `claimed_by`.

This is the root of the feature's dependency graph: `LedgerService.unclaim()` (TASK-3391)
constructs `LedgerEvent(kind="issue.unclaimed")`, and `kind` is typed `LedgerEventKind`
(`events.py:87`), so Pydantic rejects the event until this Literal grows. It is additive by
construction — `apply_event` already ignores kinds it does not own (`index.py:120-122`),
so replay of an old log never breaks.

---

## Scope

- Add `"issue.unclaimed"` as the 12th member of `LedgerEventKind` in `events.py`.
- Add `IssueUnclaimedPayload(unclaimed_by: str, reason: str)` in `events.py`, mirroring
  `IssueClaimedPayload`.
- Add `LedgerIndex._apply_issue_unclaimed()` in `index.py` and its `elif` in `apply_event`.
  Semantics: `claimed → open`, `claimed_by = None`, assert an `"unclaimed-by"` edge; a no-op
  on `open`, `closed`, `superseded` or a missing page.
- Extend `tests/knowledge/wiki/test_ledger_events.py` and
  `tests/knowledge/wiki/test_ledger_index.py`.

**NOT in scope**: `SEVERITY_ORDER` and `ready_work()` ordering (TASK-3388);
`LedgerService.unclaim()` / `close_issue(resolved_by=)` (TASK-3391); any CLI or MCP surface
(TASK-3392 / TASK-3393).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py` | MODIFY | 12th Literal member + `IssueUnclaimedPayload` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | `_apply_issue_unclaimed` reducer + dispatch branch |
| `tests/knowledge/wiki/test_ledger_events.py` | MODIFY | payload model + 12-member Literal tests |
| `tests/knowledge/wiki/test_ledger_index.py` | MODIFY | `TestUnclaim` — reducer state transitions |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified against `dev` on 2026-09-18. Use these exact names. If anything
> has moved, update this contract first, then implement.

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.events import (          # verified: ledger/events.py:7,35,83
    LedgerEvent, LedgerEventKind, IssueClaimedPayload, compute_issue_id,
)
from parrot.knowledge.wiki.ledger.index import LedgerIndex  # verified: ledger/index.py:85
from parrot.knowledge.wiki.ledger.log import LedgerLog      # verified: ledger/log.py
from parrot.knowledge.wiki.ledger.store import LedgerStore  # verified: ledger/store.py
from pydantic import BaseModel, Field                       # verified: ledger/events.py:5
from typing import get_args                                 # stdlib — for counting Literal members
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
LedgerEventKind = Literal[...]            # lines 7-19 — 11 members, last is "insight.superseded"
class IssueClaimedPayload(BaseModel):     # line 35
    claimed_by: str = Field(description="Agent or task claiming work, e.g. task:TASK-3205")  # 36
class LedgerEvent(BaseModel):             # line 83
    kind: LedgerEventKind                 # line 87 — Pydantic rejects any kind outside the Literal
    subject: str; actor: str; ts: str; payload: dict[str, Any]

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py
from parrot.knowledge.wiki.ledger.events import (   # lines 20-26: IssueAcknowledgedPayload,
    IssueAcknowledgedPayload, IssueClaimedPayload, IssueClosedPayload, IssueOpenedPayload, LedgerEvent)
class LedgerIndex:                                                                       # 85
    async def apply_event(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:  # 102
        # if/elif chain 109-119; last branch: `await self._apply_issue_superseded(event, conn)` (119)
        # comment 120-122: unknown kinds ignored — keep that contract
    async def _read_issue(self, conn, issue_id: str) -> dict[str, Any] | None:           # 123
    async def _write_issue(self, conn, issue_id: str, state: dict[str, Any], actor: str, ts: str) -> None:  # 131
    async def _apply_issue_claimed(self, event, conn) -> None:                           # 188-197
        # state None or status != "open" -> return; status="claimed"; claimed_by=payload.claimed_by;
        # _write_issue(...); store.add_edges_in(conn, [(subject, claimed_by, "claimed-by", "asserted")])
    async def _apply_issue_superseded(self, event, conn) -> None:                        # 221-228
    # section comment `    # Cursor / replay` follows at line 230 (inside a `# ----` rule)
    async def claim_issue(self, issue_id: str, claimed_by: str) -> bool:                 # 384
    async def sync(self) -> ...                                                          # used by tests: `await ledger_index.sync()`
    self.store.add_edges_in(conn, edges: list[tuple[str, str, str, str]])                # ledger/store.py

# tests/knowledge/wiki/test_ledger_index.py — helpers you MUST reuse
def _issue_id(title, discovered_from="task:TASK-3200", kind="bug") -> str          # line 22
def _opened_event(title, discovered_from=..., kind=..., severity=..., about=None, actor=...) -> LedgerEvent  # 26
@pytest.fixture ledger_index(ledger_store, ledger_log) -> LedgerIndex             # 73
async def _get_status(index: LedgerIndex, issue_id: str) -> str | None            # 77
class TestAtomicClaim: ...                                                        # 249
class TestBusyBehaviour: ...                                                      # 343  ← insert TestUnclaim ABOVE this

# tests/knowledge/wiki/test_ledger_events.py — import block lines 3-13 imports
#   LedgerEvent, IssueOpenedPayload, IssueClaimedPayload, IssueAcknowledgedPayload,
#   IssueClosedPayload, InsightRecordedPayload, compute_event_id, compute_issue_id
# last test: `def test_insight_recorded_payload():` (line 98)
```

### Does NOT Exist
- ~~`"issue.unclaimed"`~~ in `LedgerEventKind` — this task adds it (11 → 12 members).
- ~~`IssueUnclaimedPayload`~~ — this task adds it.
- ~~`LedgerIndex._apply_issue_unclaimed`~~ — this task adds it.
- ~~`LedgerService.unclaim()`~~ — TASK-3391, NOT here. Do not touch `service.py`.
- ~~`issue.superseded` as a release~~ — it sets terminal `status="superseded"`; never reuse it.
- ~~`LedgerIndex.read_issue` / `get_issue`~~ — the reader is the underscore `_read_issue`.
- ~~`ledger.db` schema change~~ — the new kind writes through existing `pages`/`edges` via `_write_issue`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_events.py", "action": "MODIFY"},
    {"path": "tests/knowledge/wiki/test_ledger_index.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEventKind",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#IssueClaimedPayload",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.apply_event",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex._apply_issue_claimed",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex._read_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex._write_issue"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The reducer is the **mirror** of `_apply_issue_claimed`: same read → guard → mutate →
  `_write_issue` → `add_edges_in` shape. Do not invent a new persistence path.
- Guard on `status != "claimed"` (not `== "open"`): `open`, `closed`, `superseded` and a
  missing page are all no-ops — AC "no-op on open, closed and superseded".
- Keep the `# task.*, spec.*, insight.* … unknown kinds are ignored` comment intact; the
  regression test `test_unknown_event_kind_still_ignored` protects that contract.
- Run tests from a worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared `.venv`
  points at the main checkout — `worktree-management.md` §4).
- `black -l 120`, `ruff check` on both source files.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:188-197` — `_apply_issue_claimed`, the pattern to mirror.
- `tests/knowledge/wiki/test_ledger_index.py:182-226` — acknowledge/closed transition tests, the test shape to mirror.

---

## Implementation Blueprint

### Steps (in order)
1. Add `"issue.unclaimed"` to the Literal — *why*: `LedgerEvent.kind` validation must accept it before any test can append one.
2. Add `IssueUnclaimedPayload` right after `IssueClaimedPayload` — *why*: the reducer validates the payload through it, exactly as `_apply_issue_claimed` does with `IssueClaimedPayload`.
3. Import the payload in `index.py`, add the `elif`, add the reducer after `_apply_issue_superseded` — *why*: dispatch and reducer live together with the other five `issue.*` reducers.
4. Write the tests, then run both files — *why*: `test_unknown_event_kind_still_ignored` proves the additive-kind contract survived.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    "issue.superseded",' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py)
# AFTER — insert below `    "issue.superseded",` (verified: events.py:12)
    "issue.unclaimed",
```
```python
# occurrences: 1 (verified: grep -cF 'claimed_by: str = Field(description="Agent or task claiming work, e.g. task:TASK-3205")' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py)
# AFTER — insert below that line (verified: events.py:36), separated by two blank lines
class IssueUnclaimedPayload(BaseModel):
    """Release a claim so the issue returns to the ready pool (FEAT-572).

    Reduces ``claimed -> open`` and clears ``claimed_by``; a no-op on any
    other status. Mirrors :class:`IssueClaimedPayload`.
    """

    unclaimed_by: str = Field(description="Actor releasing the claim, e.g. agent:sdd-fix")
    reason: str
```
**Why this shape**: the Literal member is the 12th kind the spec names; the payload mirrors
`IssueClaimedPayload` so the reducer can validate it the same way. Field names
`unclaimed_by` / `reason` are fixed by spec §3 M2 — TASK-3391 builds this payload.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    IssueOpenedPayload,' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py)
# AFTER — insert below `    IssueOpenedPayload,` in the events import block (verified: index.py:24)
    IssueUnclaimedPayload,
```
```python
# occurrences: 1 (verified: grep -cF '            await self._apply_issue_superseded(event, conn)' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py)
# AFTER — insert below that line (verified: index.py:119), BEFORE the "unknown kinds are ignored" comment
        elif event.kind == "issue.unclaimed":
            await self._apply_issue_unclaimed(event, conn)
```
```python
# occurrences: 1 (verified: grep -cF '    # Cursor / replay' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py)
# BEFORE — insert above the `    # ----…` rule line that precedes `    # Cursor / replay` (verified: index.py:229-230),
#          i.e. directly after `_apply_issue_superseded`'s last line `await self._write_issue(...)`
    async def _apply_issue_unclaimed(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:
        """Revert ``claimed -> open`` and clear ``claimed_by``; any other status is a no-op.

        Reverse of :meth:`_apply_issue_claimed` (FEAT-572 Module 2): a page that is
        ``open``, ``closed``, ``superseded`` or missing is left untouched.
        """
        payload = IssueUnclaimedPayload(**event.payload)
        state = await self._read_issue(conn, event.subject)
        if state is None or state.get("status") != "claimed":
            return
        state["status"] = "open"
        state["claimed_by"] = None
        await self._write_issue(conn, event.subject, state, event.actor, event.ts)
        await self.store.add_edges_in(conn, [(event.subject, payload.unclaimed_by, "unclaimed-by", "asserted")])
```
**Why**: one `elif` keeps the dispatch chain the single place kinds are routed; the reducer
reuses `_read_issue` / `_write_issue` / `add_edges_in` so the new kind needs no schema change.

### `tests/knowledge/wiki/test_ledger_events.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def test_insight_recorded_payload():' tests/knowledge/wiki/test_ledger_events.py)
# AFTER — append below the whole `test_insight_recorded_payload` function (verified: :98)
# Also extend the import block (lines 3-13) with `IssueUnclaimedPayload, LedgerEventKind` and add `from typing import get_args`.


def test_issue_unclaimed_payload():
    payload = IssueUnclaimedPayload(unclaimed_by="agent:sdd-fix", reason="released: not fixed in this lane")
    assert payload.unclaimed_by == "agent:sdd-fix"
    assert payload.reason.startswith("released")


def test_ledger_event_kind_has_twelve_members_including_unclaimed():
    members = get_args(LedgerEventKind)
    assert len(members) == 12
    assert "issue.unclaimed" in members


def test_issue_unclaimed_event_validates():
    event = LedgerEvent(
        kind="issue.unclaimed", subject="issue:abc", actor="agent:sdd-fix",
        payload={"unclaimed_by": "agent:sdd-fix", "reason": "released"},
    )
    assert event.event_id  # computed by model_post_init
```
**Why**: proves the Literal grew and the payload validates, independent of SQLite.

### `tests/knowledge/wiki/test_ledger_index.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'class TestBusyBehaviour:' tests/knowledge/wiki/test_ledger_index.py)
# BEFORE — insert above `class TestBusyBehaviour:` (verified: :343), two blank lines on each side


def _unclaimed_event(issue_id: str, actor: str = "agent:sdd-fix") -> LedgerEvent:
    return LedgerEvent(
        kind="issue.unclaimed", subject=issue_id, actor=actor,
        payload={"unclaimed_by": actor, "reason": "released by test"},
    )


async def _read_state(index: LedgerIndex, issue_id: str) -> dict | None:
    async with index.store.ledger_transaction("test-read") as conn:
        return await index._read_issue(conn, issue_id)


class TestUnclaim:
    async def test_unclaimed_reverts_status_and_clears_claimed_by(self, ledger_index):
        e1 = _opened_event("Releasable issue")
        ledger_index.log.append(e1)
        await ledger_index.sync()
        assert await ledger_index.claim_issue(e1.subject, "task:TASK-A") is True
        # FILL IN: append _unclaimed_event(e1.subject), sync, then assert status == "open"
        #          and claimed_by is None via _read_state — bounded by AC "reverts claimed → open"

    async def test_unclaimed_on_open_issue_is_noop(self, ledger_index):
        # FILL IN: open (never claim), append unclaimed, sync; status stays "open", claimed_by None,
        #          and updated_at/asserted_by unchanged is NOT required — only state — bounded by AC "no-op on open"

    async def test_unclaimed_on_closed_issue_is_noop(self, ledger_index):
        # FILL IN: open → claim → append issue.closed (payload reason/closed_by) → sync → append unclaimed → sync;
        #          status stays "closed" — bounded by AC "no-op on closed and superseded"

    async def test_unknown_event_kind_still_ignored(self, ledger_index):
        # FILL IN: append LedgerEvent(kind="task.started", subject="task:TASK-1", actor="agent:x", payload={})
        #          then `await ledger_index.sync()` must not raise — regression on index.py:120-122
```
**Why**: the fixture, `_opened_event` and `claim_issue` already exist; the four tests map
one-to-one onto the four AC bullets for Module 2.

### FILL IN checklist
- [ ] `test_ledger_index.py::TestUnclaim::test_unclaimed_reverts_status_and_clears_claimed_by` — append/sync/assert body; bounded by AC "`claimed → open`, `claimed_by is None`"
- [ ] `test_ledger_index.py::TestUnclaim::test_unclaimed_on_open_issue_is_noop` — bounded by AC "no-op on open"
- [ ] `test_ledger_index.py::TestUnclaim::test_unclaimed_on_closed_issue_is_noop` — bounded by AC "no-op on closed/superseded"
- [ ] `test_ledger_index.py::TestUnclaim::test_unknown_event_kind_still_ignored` — bounded by `index.py:120-122` contract
- [ ] `test_ledger_events.py` import block — add `IssueUnclaimedPayload`, `LedgerEventKind`, `get_args`

---

## Acceptance Criteria

- [ ] `LedgerEventKind` has 12 members and `"issue.unclaimed"` is one of them.
- [ ] `IssueUnclaimedPayload(unclaimed_by, reason)` exists in `events.py`.
- [ ] `issue.unclaimed` reverts `claimed → open` and clears `claimed_by`; it is a no-op on `open`, `closed`, `superseded` and on a missing page.
- [ ] An `"unclaimed-by"` asserted edge is written on a successful release.
- [ ] An unknown kind is still ignored by `apply_event` (no exception on `sync()`).
- [ ] `service.py`, `cli.py`, `tools.py` untouched.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_ledger_events.py tests/knowledge/wiki/test_ledger_index.py -v`
- [ ] `ruff check` and `black --check -l 120` clean on `events.py` and `index.py`.

---

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_events.py -q`
- `pytest tests/knowledge/wiki/test_ledger_index.py -q`

---

## Test Specification

```python
# tests/knowledge/wiki/test_ledger_index.py (excerpt of what must pass)
class TestUnclaim:
    async def test_unclaimed_reverts_status_and_clears_claimed_by(self, ledger_index): ...
    async def test_unclaimed_on_open_issue_is_noop(self, ledger_index): ...
    async def test_unclaimed_on_closed_issue_is_noop(self, ledger_index): ...
    async def test_unknown_event_kind_still_ignored(self, ledger_index): ...

# tests/knowledge/wiki/test_ledger_events.py
def test_issue_unclaimed_payload(): ...
def test_ledger_event_kind_has_twelve_members_including_unclaimed(): ...
def test_issue_unclaimed_event_validates(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above (§2 Overview, §3 Module 2, §7 gotchas).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — grep every anchor line; the occurrence counts above must still be 1.
4. **Update status** in `sdd/tasks/index/sdd-fix-ledger-lane.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `FILL IN`; never change a name the blueprint fixes.
6. **Verify** the Validation Commands pass (`PYTHONPATH=packages/ai-parrot/src` inside a worktree).
7. **Move this file** to `sdd/tasks/completed/TASK-3387-unclaimed-event-kind-and-reducer.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-worker (native sonnet coder, attempt_uid b815080bcdfa4a5891eaa2ae4a682b99)
**Date**: 2026-09-19
**Notes**: Added the 12th `LedgerEventKind` member `issue.unclaimed`, `IssueUnclaimedPayload`
(events.py) and `LedgerIndex._apply_issue_unclaimed` (index.py) mirroring `_apply_issue_claimed`
(claimed→open, `claimed_by=None`, asserts an `unclaimed-by` edge; no-op on open/closed/superseded
or missing page). Filled in the blueprint's TestUnclaim + events tests verbatim.
Validation: `pytest tests/knowledge/wiki/test_ledger_events.py tests/knowledge/wiki/test_ledger_index.py -q` → 31 passed.
`ruff check` + `black --check` clean. Merged via `coder_merge` → merged, engine lint autofix (black) applied, no residual findings.
Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 191.2s · Tokens: n/a (native, no usage telemetry)

**Deviations from spec**: none
