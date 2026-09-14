# TASK-3229: Atomic append-only ledger log

**Feature**: FEAT-566 — SDD Work Ledger
**Spec**: `sdd/specs/sdd-work-ledger.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3226, TASK-3228
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. `events.jsonl` is the durable source of truth: it must survive a temporarily unavailable materialized index and cannot acquire a SQLite lock.

## Scope

- Implement `LedgerLog.append()` with `os.open(..., O_APPEND|O_WRONLY|O_CREAT)` and exactly one write per bounded serialized event.
- Enforce the 4 KiB line limit before opening/writing the file.
- Implement streaming `iter_events(from_offset=0)` with malformed/partial-tail warning and byte end offsets.
- Add multiprocess append/interleaving coverage and oversize rejection tests.

**NOT in scope**: SQLite transactions, log compaction/rotation, or workflow commands.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` | CREATE | POSIX append and iterator. |
| `tests/knowledge/wiki/test_ledger_log.py` | CREATE | Append, offset, corruption, concurrency tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.events import LedgerEvent
```

### Existing Signatures to Use
```python
# Spec §2 public contract
class LedgerLog:
    def append(self, event: LedgerEvent) -> tuple[str, int]: ...
    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]: ...
```

### Does NOT Exist
- ~~`LedgerLog`~~ — this task creates it.
- ~~a cross-process lock around events.jsonl~~ — forbidden; atomic single-write append is the v1 contract.

## Acceptance Criteria

- [ ] Oversized serialized lines are rejected without partial records.
- [ ] Valid lines replay in order with cursor-safe byte offsets.
- [ ] Eight-process append testing proves no interleaved JSON lines.
- [ ] `pytest tests/knowledge/wiki/test_ledger_log.py -q` passes.

## Test Specification

Use multiprocessing synchronization rather than timing sleeps.

