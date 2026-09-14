# TASK-3231: Ledger event reduction, replay cursor, and atomic claim

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: done
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

- [x] Rebuild and repeated sync produce identical state.
- [x] Cursor mismatch rebuilds; normal resume does not rescan prior events.
- [x] Exactly one claimant succeeds; stale index is synchronized inside the claim transaction.
- [x] Busy claim appends no `issue.claimed`; busy open remains replayable.
- [x] `pytest tests/knowledge/wiki/test_ledger_index.py -q` passes after FEAT-557 merges.

## Test Specification

Use FEAT-557 `_peer_writer` with a short supplied policy only for ledger-specific busy behavior.

### Completion Note

Implemented as specified. The issue page's `body` column carries a
single JSON state header (`<!--ledger-state {...}-->`) followed by a
human-readable rendering — one encode/decode pair used by every read and
write path, so status can never desync between the creation path and
update paths (this is the bug a discarded first attempt hit: it wrote
JSON metadata on `issue.opened` but read back a plain `"status: "` text
line on every other path, so a freshly-opened issue always read back as
`"unknown"` and `claim_issue` failed immediately after open).

Cursor design: `(offset, last_event_id)` persists the **start** byte
offset of the last applied event's own line. On resume, `sync()`
re-reads that exact line and checks its `event_id` still matches before
continuing past it (never reapplying it) — a mismatch triggers a full
`rebuild()`. `claim_issue` runs `sync(conn) -> status check -> log.append
-> apply_event(conn) -> cursor advance` inside one
`store.ledger_transaction("ledger.claim")`; a `WikiStoreBusy` raised
while acquiring that transaction propagates before the log is ever
appended to.

14 tests pass (`pytest tests/knowledge/wiki/test_ledger_index.py -q`,
2 marked `@pytest.mark.slow` reusing FEAT-557's `_peer_writer` via a
proper multiprocessing subprocess), plus the 20 pre-existing
`test_ledger_events.py`/`test_ledger_log.py`/`test_ledger_store.py`
tests re-verified green. `ruff check` and `black --check` clean.

An automated first attempt at this task (qwen/nova seat) left the
worktree dirty with a materially broken reducer (status storage format
mismatch described above, plus wrong edge-tuple argument order —
`(src, rel, dst, actor, ts)` instead of the real
`_insert_edges_conn` shape `(src, dst, rel, provenance)` — and an
out-of-scope `tests/debug_ledger.py` scratch file). That attempt and its
sub-worktree were discarded rather than patched; this is a from-scratch
implementation informed by, but not derived from, that draft.

Seat: sonnet (sdd-worker fallback, attempt 3 after two dev-loop nova
attempts each hit `SubWorktreeMergeError` due to stale leftover
sub-worktrees, then one completed-but-dirty/incorrect nova attempt) ·
Backend: none (direct implementation in the feature worktree) ·
Attempts: 1 (this implementation).
