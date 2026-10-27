# TASK-4858: Ledger integration — strict logical-log merge, transition conflicts, scratch snapshot

**Feature**: FEAT-758 — Durable Ledger Outbox and Independent Integration into dev
**Spec**: `sdd/specs/ledger-outbox-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4857
**Assigned-to**: unassigned

---

## Context

Spec §2 "Delivery transaction" steps 3–6 and §3 Module 2. Before anything is committed to `origin/dev`, the
integrator must (a) strictly read the destination's canonical logical log (archives + current log, in
`shared_log_files()` order), (b) append the batch's missing events in captured source order, rejecting an
equal ID with different content, (c) reject incompatible issue transitions with structured evidence, and
(d) build `issues.jsonl` from an **isolated scratch** `LedgerService` replaying the merged log — never from the
machine's live SQLite view. This task implements those Git-free building blocks in `integration.py`;
TASK-4859 adds the Git transaction (`LedgerIntegrator`) to the same file.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` containing ONLY these
  module-level building blocks (TASK-4859 appends `LedgerIntegrator` below them):
  - `read_logical_log(repo_root: Path) -> list[tuple[bytes, LedgerEvent]]` — strict read of every file from
    `shared_log_files(repo_root)` via `read_strict_events`; dedupe by `event_id` keeping first occurrence;
    equal id + unequal canonical content → `StrictLedgerReadError`.
  - `MergePlan` model + `merge_batch(remote, batch) -> MergePlan` — events of the batch absent from remote, in
    batch order; exact duplicates counted as `duplicates`; identity conflicts raise `StrictLedgerReadError`.
  - `find_transition_conflicts(remote, new) -> list[LedgerDeliveryConflict]` — pure reducer over issue
    status/claimed_by/close evidence (rules below).
  - `async build_scratch_snapshot(merged: Sequence[bytes], *, scratch_dir: Path, dest: Path) -> bool` — write
    the merged raw lines to `scratch_dir/events.jsonl`, `LedgerService.from_dir(scratch_dir)`, `await
    service.index.sync()` (strict — `WikiStoreBusy` propagates), then `await service.export_snapshot(dest,
    reconcile=True)`.
- Create `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py` with the replay/conflict
  tests (TASK-4859 appends the Git tests to this file).

**Conflict rules** (spec §2 "Conflict policy", step 6) — evaluate each new event against the state produced by
remote events + earlier new events:
- `issue.claimed` on an issue claimed by a **different** `claimed_by` → conflict `"competing-claim"`; same owner → ok.
- `issue.closed` on a terminal (`closed`/`superseded`) issue whose recorded `(closed_by, reason, resolved_by)`
  differs → conflict `"conflicting-close"`; identical evidence → ok.
- `issue.unclaimed` on a terminal issue → conflict `"unclaim-terminal"`.
- any `issue.*` event other than `issue.opened` whose subject has no `issue.opened` before it →
  conflict `"missing-predecessor"`.
- Everything else follows the existing reducer and never conflicts (including repeated no-op effects).

**NOT in scope**: Git, worktrees, push/retry, receipts (TASK-4859); log rotation (spec §2 step 7: delivery
never rotates); rebuilding or syncing the live shared index (`LedgerIndex.rebuild()` is forbidden, spec §6).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` | CREATE | Merge/validate/replay building blocks |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py` | CREATE | Replay + conflict tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.events import LedgerEvent, canonical_json_dumps
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py:103,83
from parrot.knowledge.wiki.ledger.service import LedgerService
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:149
from parrot.knowledge.wiki.ledger.shared_log import shared_log_files
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py:105
from parrot.knowledge.wiki.ledger.outbox import LedgerDeliveryConflict, StrictLedgerReadError, read_strict_events
# created by TASK-4857 (packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py:105
def shared_log_files(repo_root: Path) -> list[Path]:
    """Existing archive files (sorted sdd/ledger/archive/events-*.jsonl) followed by sdd/ledger/events.jsonl."""

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
class LedgerService:
    index: LedgerIndex   # :161
    @classmethod
    def from_dir(cls, ledger_dir: Path, *, sqlite_policy: SQLitePragmaPolicy | None = None) -> "LedgerService":  # :197
        # creates ledger_dir/ledger.db and reads ledger_dir/events.jsonl
    async def export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool:  # :532
        # carries forward dest rows whose issue_id is unknown to this service (legacy snapshot-only rows)

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:263
async def sync(self, conn: "aiosqlite.Connection | None" = None) -> int:  # raises WikiStoreBusy when locked

# Event payload fields (events.py): issue.claimed -> {"claimed_by"}; issue.closed -> {"reason","closed_by",
# "resolved_by"?}; issue.unclaimed -> {"unclaimed_by","reason"}; kinds listed in LedgerEventKind (events.py:7)
# Reducer semantics mirrored from index.py:191-246: claim only applies to "open"; close applies to any known
# issue; unclaim only applies to "claimed"; superseded is terminal.
```
`export_snapshot` already calls `_sync_best_effort()` internally (service.py:556); the strict `index.sync()`
call BEFORE it is what guarantees a complete view (spec §2 step 5: "Busy sync is a delivery failure").

### Does NOT Exist
- ~~`LedgerIntegrator`~~ — added by TASK-4859, not here.
- ~~`LedgerService.from_root(scratch_dir)` as isolation~~ — `from_root` resolves the SHARED primary root
  (spec §6); always use `from_dir`.
- ~~`LedgerService.close()` / `LedgerStore.close()`~~ — no close API; let the scratch service go out of scope
  (the caller deletes `scratch_dir`).
- ~~`shared_log.read_raw_events` for validation~~ — it skips malformed lines; use `read_strict_events`.
- ~~`live_claims()` as a conflict detector~~ — it only tracks surviving claims, not owner conflicts or close
  evidence; do not reuse it for these rules.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#canonical_json_dumps",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.from_dir",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.export_snapshot",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py#LedgerIndex.sync",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py#shared_log_files"
  ]
}
```

---

## Implementation Notes

- "Canonical content" for identity comparison = `canonical_json_dumps(event.model_dump())`.
- Preserve the remote prefix order and the batch's captured order; never sort by timestamp, id or branch.
- Raw bytes are carried through unchanged: the merged log is `remote raw lines + new raw lines`, each newline
  terminated. Archives are read but `build_scratch_snapshot` receives the full logical sequence (archives
  included) so the replay sees every issue's history.
- Run blocking file reads via `asyncio.to_thread` inside async functions.

---

## Implementation Blueprint

### Steps (in order)
1. Write the merge/conflict block — *why*: pure, fast to test, and TASK-4859 calls these exact names.
2. Write `build_scratch_snapshot` — *why*: G4/AC "Snapshot state comes from remote plus batch replay".
3. Write the tests — *why*: spec §4 rows "Identity collision", "Scratch replay", "Semantic conflicts".

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` (CREATE)
```python
"""Canonical integration of sealed ledger batches into origin/dev (FEAT-758 Module 2)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.ledger.events import LedgerEvent, canonical_json_dumps
from parrot.knowledge.wiki.ledger.outbox import LedgerDeliveryConflict, StrictLedgerReadError, read_strict_events
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.shared_log import shared_log_files

logger = logging.getLogger(__name__)

TERMINAL = frozenset({"closed", "superseded"})


class MergePlan(BaseModel):
    """Events to append to the destination log, in captured order."""

    new_lines: list[bytes] = Field(default_factory=list)
    new_events: list[LedgerEvent] = Field(default_factory=list)
    duplicates: int = 0


def _canonical(event: LedgerEvent) -> str:
    return canonical_json_dumps(event.model_dump())


def read_logical_log(repo_root: Path) -> list[tuple[bytes, LedgerEvent]]:
    """Strictly read archives + current log in ``shared_log_files`` order, deduplicated by event id."""
    # FILL IN: for each path: read_strict_events(path); a truncated_tail on a COMMITTED file is malformed ->
    #   StrictLedgerReadError. Keep first occurrence per id; a later equal id must have equal _canonical()
    #   content (known archive/current duplicates are normalized) else StrictLedgerReadError — spec §2 step 3.
    raise NotImplementedError


def merge_batch(remote: Sequence[tuple[bytes, LedgerEvent]], batch: Sequence[tuple[bytes, LedgerEvent]]) -> MergePlan:
    """Return batch events absent from ``remote``; reject equal ids with different content."""
    # FILL IN: index remote by id -> canonical; for each batch event in order: same id+same content ->
    #   duplicates += 1; same id+different content -> StrictLedgerReadError; else append — spec §2 step 4.
    raise NotImplementedError


def find_transition_conflicts(
    remote: Sequence[LedgerEvent], new: Sequence[LedgerEvent]
) -> list[LedgerDeliveryConflict]:
    """Replay ``remote`` then check each ``new`` issue event against the state before it."""
    state: dict[str, dict[str, Any]] = {}
    conflicts: list[LedgerDeliveryConflict] = []
    # FILL IN: _apply(state, ev) for remote events (no checks). Then for each new event: compute conflict per
    #   the task's Conflict rules (competing-claim / conflicting-close / unclaim-terminal / missing-predecessor),
    #   append LedgerDeliveryConflict(event_id, subject, reason) when found, and _apply it regardless so later
    #   events see the same state the live reducer would — bounded by spec §2 "Conflict policy".
    return conflicts


def _apply(state: dict[str, dict[str, Any]], event: LedgerEvent) -> None:
    """Mirror the live reducer (index.py:191-246) for status / claimed_by / close evidence only."""
    # FILL IN: opened -> {"status": "open", "claimed_by": None, "close": None} (only if absent);
    #   claimed -> if status == "open": claimed + claimed_by; unclaimed -> if claimed: open, claimed_by None;
    #   closed -> if known: closed + close=(closed_by, reason, resolved_by); superseded -> if known: superseded.
    raise NotImplementedError


async def build_scratch_snapshot(merged: Sequence[bytes], *, scratch_dir: Path, dest: Path) -> bool:
    """Replay ``merged`` raw lines in an isolated ledger and export ``dest`` (reconcile=True)."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    data = b"".join(line + b"\n" for line in merged)
    await asyncio.to_thread((scratch_dir / "events.jsonl").write_bytes, data)
    service = LedgerService.from_dir(scratch_dir)
    await service.index.sync()  # strict: WikiStoreBusy propagates to the caller as a delivery failure
    changed = await service.export_snapshot(dest, reconcile=True)
    logger.debug("Scratch ledger snapshot %s (changed=%s) from %d events", dest, changed, len(merged))
    return changed
```
**Why this shape**: these four functions are exactly spec §2 steps 3–6 minus Git; keeping them module-level and
pure lets TASK-4859 call them once per retry against a *fresh* base. `build_scratch_snapshot` is complete —
do not change it to `from_root` or add `reconcile=False`.

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py` (CREATE)
```python
"""FEAT-758 M2 — strict merge, transition conflicts, scratch replay (Git tests appended by TASK-4859)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.integration import (
    build_scratch_snapshot,
    find_transition_conflicts,
    merge_batch,
    read_logical_log,
)
from parrot.knowledge.wiki.ledger.outbox import StrictLedgerReadError


def _ev(kind: str, subject: str, payload: dict, n: int) -> LedgerEvent:
    return LedgerEvent(kind=kind, subject=subject, actor="agent:test", ts=f"2026-10-27T00:00:{n:02d}+00:00",
                       payload=payload)


def test_merge_skips_exact_duplicates_and_keeps_order() -> None:
    # FILL IN


def test_merge_rejects_equal_id_different_content() -> None:
    # FILL IN: hand-build a raw line reusing an id with changed payload -> StrictLedgerReadError


def test_logical_log_dedups_archive_and_current(tmp_path: Path) -> None:
    # FILL IN: same event line in sdd/ledger/archive/events-2026_09.jsonl and sdd/ledger/events.jsonl -> once


@pytest.mark.parametrize("reason", ["competing-claim", "conflicting-close", "unclaim-terminal", "missing-predecessor"])
def test_transition_conflicts(reason: str) -> None:
    # FILL IN: one scenario per rule; assert event_id, subject and reason


def test_same_owner_claim_and_identical_close_are_not_conflicts() -> None:
    # FILL IN


async def test_scratch_replay_remote_closed_wins_and_legacy_rows_survive(tmp_path: Path) -> None:
    # FILL IN: remote log opens+closes issue A; dest issues.jsonl holds legacy row for issue Z (no events);
    #   merged = remote lines + a stale local re-claim of A; snapshot: A closed, Z carried forward.
```

### FILL IN checklist
- [ ] `read_logical_log` — strict, dedup, committed truncated tail is an error; bounded by spec §2 step 3
- [ ] `merge_batch` — bounded by spec §2 step 4
- [ ] `find_transition_conflicts` / `_apply` — bounded by the Conflict rules above
- [ ] All tests

---

## Acceptance Criteria

- [ ] Equal ID/different body rejected before any commit
- [ ] Local stale issue cannot override remote closed issue; legacy snapshot-only rows preserved
- [ ] Conflicting claim/close/unclaim reports event and subject
- [ ] No Git subprocess in this task's code; no use of the live shared ledger
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox_integration.py -q`

---

## Test Specification

See the test blueprint above.

---

## Agent Instructions

1. Work in the feature worktree; TASK-4857 must be `done` in `sdd/tasks/index/ledger-outbox-integration.json`.
2. Read spec §2 "Delivery transaction" and "Conflict policy".
3. Verify the Codebase Contract (including the TASK-4857 names) before coding.
4. Implement, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`, commit only the two files.
5. Close with `scripts/sdd/close_task.sh TASK-4858 ledger-outbox-integration verified`.

---

## Completion Note

*(Agent fills this in when done)*
