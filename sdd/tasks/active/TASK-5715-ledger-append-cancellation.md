# TASK-5715: Drain durable appends before releasing cancelled ledger mutations

**Feature**: FEAT-902 - Wiki and ledger SQLite hardening
**Spec**: `sdd/specs/wiki-ledger-sqlite-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5714
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Depends on TASK-5714 solely to serialize modifications of ledger/index.py after its sync changes (which transitively include TASK-5713). Uses existing LedgerLog.append and LedgerStore.ledger_transaction.

## Context

Implement spec M3 and AC5/AC6. Cancelling an asyncio waiter does not stop its append thread; the mutation must retain SQLite writer ownership until append/fsync has settled.

## Scope

- Add LedgerIndex._append_durably(event) -> tuple[str,int], using a strongly referenced task and cancellation-safe shield/drain.
- Replace only claim/close/unclaim append calls, retaining their surrounding transaction and ownership checks.
- Preserve cancellation precedence, chained append failures, rollback and later log reconciliation.
- Add process-based writer exclusion and crash-after-fsync recovery coverage.

**NOT in scope**: No automatic operation retries, new append format, fsync timeout releasing a live worker, connection reuse, or changes to unguarded open_issue semantics.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_append_cancellation.py` | CREATE | Focused validation |

## Codebase Contract (Anti-Hallucination)

Verified against base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` on 2026-11-16. Existing signatures and exact edit anchors were re-read; dependency-produced symbols are explicitly distinguished from existing ones. Recheck them after predecessor commits. If a required import or interface differs, stop and report drift instead of guessing.

### Verified Imports

```python
import asyncio
import multiprocessing
import threading
from pathlib import Path
import pytest
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.store import SQLitePragmaPolicy
```

Stdlib imports and installed pytest/aiosqlite/Pydantic were verified in the activated repository environment; no new dependency is authorized. Imports of new symbols belong to their named producer below and must be verified after it lands.

### Existing Signatures and Dependency Interfaces

- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:129,445,503,550: LedgerIndex(store,log), claim_issue(issue_id,claimed_by), close_issue(issue_id,actor,reason,resolved_by=None,force=False), unclaim_issue(issue_id,actor,reason,force=False).
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:499,546,583: three existing to_thread(log.append,event) sites, all inside ledger_transaction. Lines shift after predecessors; locate by owning method.
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:54: ledger_transaction(operation) wraps _write's rollback on BaseException.
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:21: append(event) completes os.fsync before returning (id, informational_offset).
- packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:195: from_dir(ledger_dir: Path, *, sqlite_policy=None) constructs isolated fixtures.
- packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1853: _write owns BEGIN/COMMIT/ROLLBACK and catches BaseException in the body.

### Does NOT Exist

- LedgerIndex._append_durably is new; asyncio.to_thread alone does not drain cancelled I/O.
- There is no atomic cross-resource JSONL/SQLite transaction; durable events may survive SQL rollback.
- No production connection reuse or general retry wrapper is authorized.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_append_cancellation.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.claim_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.close_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.unclaim_issue",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py#LedgerStore.ledger_transaction",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog.append",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.from_dir",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._write",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLitePragmaPolicy"
  ]
}
```

## Implementation Notes

Keep the existing SQLite + aiosqlite stack, separate wiki/ledger databases and connection-per-operation lifecycle. Preserve asynchronous I/O and existing transaction ownership; offload blocking file work. No new dependency, schema migration or persistent connection is authorized. Tests use disposable state only.

Blueprint gaps below are bounded authoring instructions, not deliverable code. Complete all marked branches and assertions; never ship stubs. A CREATE block is a whole-file starting point and a MODIFY block attaches only to the quoted owner; preserve surrounding and predecessor changes.

## Implementation Blueprint

### Steps (in order)

1. Create the helper and retain its worker task — orphaned thread work can outlive the writer lock.
2. Drain through repeated cancellation before unwinding — the waiter cannot report cleanup while append/fsync is still running.
3. Wire the three guarded mutation paths — their existing status/ownership checks must remain inside the same transaction.
4. Test a competing process during cancellation and restart after fsync-before-commit — replay is the recovery boundary.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` (MODIFY)

Verified attachment anchor at `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:306`; exact occurrence count **1** on authoring base `0eb46c010bf33b05fabc924253ced5a3d21b02fb` (recheck after dependencies land):

```text
    async def sync(self, conn: "aiosqlite.Connection | None" = None) -> int:
```

```python
# The verified sync anchor identifies LedgerIndex's replay/mutation section.
# Preserve predecessor sync changes; insert helper before claim_issue.
async def _append_durably(self, event: LedgerEvent) -> tuple[str, int]:
    """Drain a dispatched append/fsync before propagating cancellation."""
    # FILL IN: strongly reference a task for asyncio.to_thread(self.log.append, event).
    # Shield and drain it even under repeated cancel requests (AC1/AC2).
    # Cancellation before dispatch must append nothing; do not discard pending cancel.
    # Cancel takes precedence; preserve a concurrent append failure as cause.
    # No cancel: propagate append result/error normally. Do not retry append.
    raise NotImplementedError

# In claim_issue, close_issue and unclaim_issue ONLY, replace:
#     await asyncio.to_thread(self.log.append, event)
# with:
#     await self._append_durably(event)
# Preserve subsequent _apply_from(conn, offset, last_event_id) and ownership checks.
```

Do not release the surrounding transaction while the thread can still append; later replay handles a durable event whose projection rolled back.

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_append_cancellation.py` (CREATE)

```python
"""FEAT-902 cancelled append ownership and durable recovery."""
from pathlib import Path
import asyncio
import multiprocessing
import threading
import pytest
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.store import SQLitePragmaPolicy

@pytest.fixture
def service(tmp_path: Path) -> LedgerService:
    """Construct temporary WAL/log state with a bounded peer timeout."""
    return LedgerService.from_dir(tmp_path / "ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1))

@pytest.mark.asyncio
async def test_cancel_keeps_writer_until_append_settles(service: LedgerService) -> None:
    """Repeated cancellation cannot let a peer enter during gated append/fsync."""
    # FILL IN: gate thread work, cancel mutation, assert peer exclusion, then drain.
    raise NotImplementedError

@pytest.mark.asyncio
async def test_cancel_and_append_failure_preserve_both(service: LedgerService) -> None:
    """Cancellation wins while the append error remains diagnosable."""
    # FILL IN: deterministic failure/cancel ordering and no payload in logs (AC2).
    raise NotImplementedError

def test_process_death_after_fsync_recovers(tmp_path: Path) -> None:
    """A real child dying before SQL commit leaves a replayable durable event."""
    # FILL IN: spawn child, signal after fsync, terminate before commit, replay twice.
    # Compare normalized projection with a rebuilt index; no fake in-process crash.
    raise NotImplementedError
# FILL IN: cancel-before-dispatch, normal success/error, and all three mutation routes.
```

Use controlled thread/process barriers; elapsed-time sleeps and mocked crash exceptions cannot prove writer ownership or durable recovery.

### FILL IN Checklist

- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] `packages/ai-parrot/tests/knowledge/wiki/test_ledger_append_cancellation.py` — complete its marked implementation/prose and boundary cases using Scope, Acceptance Criteria and Test Specification.
- [ ] Verify imports, types, exact attachment anchors and dependency outputs in the implementation checkout.
- [ ] Remove every unfinished scaffold from delivered files; inspect the scoped diff and run all mandatory gates.

## Acceptance Criteria

- [ ] AC1: Guarded appends finish before cancellation releases writer ownership, including repeated cancellation.
- [ ] AC2: Cancel-before-dispatch appends nothing; cancellation plus append failure preserves its cause; no retries or payload logging.
- [ ] AC3: All three mutations use the helper and preserve first claimant/owner checks and post-append replay.
- [ ] AC4: Actual child-process death after fsync/before commit converges after replay; repeated sync is idempotent.
- [ ] AC5: No worker task/thread is abandoned; successful/failed non-cancelled appends retain existing semantics.

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_append_cancellation.py -q`

## Test Specification

Coordinate asyncio events, thread events and spawned peer processes. Block the real append before/inside fsync, cancel repeatedly, verify writer exclusion before releasing the barrier, then verify replay state. Process death is not advertised as a power-loss test.

Run the task-specific commands above. The feature-wide regression contract is cached in the per-spec index and runs at its configured SDD gates; do not replace these focused checks with bare pytest or a directory scan.

## Agent Instructions

1. Start with `$sdd-start TASK-5715`; the implementation workflow provisions the feature worktree. Do not implement on dev.
2. Verify predecessors are done in `sdd/tasks/index/wiki-ledger-sqlite-hardening.json` and recheck this task's contracts.
3. Implement only the declared files, preserve other agents' changes, and complete every acceptance gate. Store execution logs under `artifacts/logs/`.
4. Use `parrot sdd task finalize` with real TaskCompletionEvidence and the exact implementation HEAD. The finalizer owns the completion note and active-to-completed move; do not hand-edit them.
