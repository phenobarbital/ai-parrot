# TASK-3231: Ledger event reduction, replay cursor, and atomic claim

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3226, TASK-3228, TASK-3229, TASK-3230
**Assigned-to**: unassigned

---

## Context

Reducer half of spec §3 Module 5. It turns durable events into pages/edges and makes concurrent claims deterministic without adding a second SQLite policy.

## Scope

- Implement `LedgerIndex.apply_event`, `sync`, `rebuild`, `claim_issue`, and index-only `compact`.
- Persist offset plus last-event ID; rebuild on mismatch and advance only contiguous applied prefixes.
- Apply write-through events by `sync(conn)` to the current log tip.
- Enforce replay rules: first claim wins, duplicate opens are idempotent, acknowledgement leaves status, and compact never rewrites the log.
- Test ledger-specific busy durability and no-append busy claim behavior.

**NOT in scope**: CLI/tool UX, `LedgerService`, SQLite policy implementation, or generic writer contention tests owned by FEAT-557.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | CREATE | Reducer, cursor, rebuild, claim, compact. |
| `tests/knowledge/wiki/test_ledger_index.py` | CREATE | Replay, stale cursor, claim, durability tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.store import WikiPageRecord
```

### Existing Signatures to Use
```python
# FEAT-566 spec §2 and Module 5
class LedgerStore(SQLiteWikiStore):
    async def ledger_transaction(self, operation: str): ...
    async def read_cursor(self) -> tuple[int, str | None]: ...
```

### Does NOT Exist
- ~~`LedgerIndex`~~ — this task creates it.
- ~~a per-event direct index write outside `sync(conn)`~~ — prohibited.
- ~~event-log rewriting during compaction~~ — forbidden in v1.

## Acceptance Criteria

- [ ] Rebuild and repeated sync produce identical state.
- [ ] Cursor mismatch rebuilds; normal resume does not rescan prior events.
- [ ] Exactly one claimant succeeds; stale index is synchronized inside the claim transaction.
- [ ] Busy claim appends no `issue.claimed`; busy open remains replayable.
- [ ] `pytest tests/knowledge/wiki/test_ledger_index.py -q` passes after FEAT-557 merges.

## Test Specification

Use FEAT-557 `_peer_writer` with a short supplied policy only for ledger-specific busy behavior.
