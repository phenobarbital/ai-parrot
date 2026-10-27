# TASK-4857: Durable ledger outbox — models, strict reader, sealed batches, receipts

**Feature**: FEAT-758 — Durable Ledger Outbox and Independent Integration into dev
**Spec**: `sdd/specs/ledger-outbox-integration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 (Overview, Data Models) and §3 Module 1. Findings must survive process exit and
feature-worktree removal before they are published to `origin/dev` (G2). The source of truth stays the
existing shared local journal (`<ledger-dir>/events.jsonl`, resolved by `LedgerService.from_root()`); this task
adds an **outbox** beside it that seals an immutable, bounded prefix of complete journal lines into a batch,
and records a receipt only after a remote verification (the receipt is written by TASK-4859's integrator, via
`acknowledge()` defined here). Every other FEAT-758 task builds on the models and the strict reader created here.

---

## Scope

- Create `parrot/knowledge/wiki/ledger/outbox.py` with:
  - Pydantic v2 models `LedgerBatch`, `LedgerDeliveryConflict`, `LedgerDeliveryReport`, `LedgerReceipt`
    (fields of the first three are fixed by spec §2 "Data Models"; `LedgerReceipt` per spec §2 last paragraph).
  - `StrictLedgerReadError(ValueError)` and `read_strict_events(path, *, end_offset=None)` — a strict JSONL
    reader that FAILS on malformed complete lines and on an `event_id` that does not match
    `compute_event_id(...)` of the event's own content, and reports (does not parse) a trailing incomplete line.
  - `LedgerOutbox(ledger_dir)` with `prepare()`, `pending()`, `acknowledge()`, `receipt_for()`, `batch_events()`
    and `status()`; storage at `<ledger_dir>/outbox/{pending/<batch-id>/{manifest.json,events.jsonl},
    receipts/<batch-id>.json, prepare.lock}`.
  - Atomic durable writes: write temp file → `fsync` → `os.replace` → `fsync` parent directory. A batch
    directory is published by renaming a fully-written temp directory into `pending/`.
  - Preparation lock: `fcntl.flock(LOCK_EX | LOCK_NB)` on `outbox/prepare.lock`; a held lock or unsupported
    locking raises `OutboxLockedError` (callers map it to the "pending" exit code 2).
- `prepare()` candidates = shareable (`is_shareable`) events in the captured prefix whose IDs are absent from
  (a) the destination baseline IDs passed in by the caller and (b) every existing un-acknowledged pending batch.
  Return `None` when there are no candidates.
- Write `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py`.

**NOT in scope**: any Git operation, fetching `origin/dev`, replay/snapshot, semantic conflict checks
(TASK-4858/4859); CLI commands (TASK-4860); deleting batches or truncating the source journal (spec §2: no
automatic deletion is introduced); changing `LedgerLog.append` or any producer API.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py` | CREATE | Models, strict reader, `LedgerOutbox` |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py` | CREATE | Unit tests (sealing, crash, identity, lock) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.events import LedgerEvent, canonical_json_dumps, compute_event_id
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py:103,83,88
from parrot.knowledge.wiki.ledger.log import LedgerLog
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:10
from parrot.knowledge.wiki.ledger.shared_log import is_shareable
# verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py:73
```
Standard library only otherwise (`asyncio`, `fcntl`, `hashlib`, `json`, `os`, `uuid`, `pathlib`, `datetime`).
Pydantic v2 (`from pydantic import BaseModel, Field`) is already a core dependency.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
def canonical_json_dumps(obj: Any) -> str:  # :83  sort_keys, separators=(",", ":")
def compute_event_id(kind: str, subject: str, actor: str, ts: str, payload: dict[str, Any]) -> str:  # :88
class LedgerEvent(BaseModel):  # :103
    event_id: str = ""          # computed in model_post_init ONLY when empty (:113) — a supplied id is NOT checked
    kind: LedgerEventKind
    subject: str
    actor: str
    ts: str
    payload: dict[str, Any]

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py
class LedgerLog:  # :10
    path: str     # :19 — the journal file path (a str, not a Path)

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py
def is_shareable(event: LedgerEvent) -> bool:  # :73 — False for local-only coder-suspension insights
```
Blocking filesystem work in async methods goes through `asyncio.to_thread` — the repository pattern
(`service.py:51` `_write_snapshot_if_changed`, `coder_feedback.py:111`).

### Does NOT Exist
- ~~`parrot.knowledge.wiki.ledger.outbox`~~ — created by this task.
- ~~`LedgerLog.read_prefix` / `LedgerLog.lock`~~ — no prefix reader or journal lock exists; do NOT add one to
  `log.py` (producers must never take the outbox lock — spec §3 M1).
- ~~`shared_log.read_raw_events` as a validator~~ — it SKIPS malformed lines (`shared_log.py:78`) and never
  re-derives `event_id`; it must not authorize delivery.
- ~~`LedgerEvent.verify()` / `LedgerEvent.content_hash`~~ — no identity check exists; implement it here.
- ~~`LedgerService.outbox`~~ — the service is not modified.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#canonical_json_dumps",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#compute_event_id",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py#is_shareable"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The batch `events.jsonl` holds the **exact raw bytes** of each selected source line (no re-serialization),
  so `event_id`s, field order and timestamps are preserved (spec §7 "Preserve raw event identity").
- `source_end_offset` = byte offset just past the last complete line (`b"\n"`-terminated) at capture time;
  bytes after it (a concurrent append in progress) are not read into the batch and stay eligible next time.
- `source_sha256` = SHA-256 of source bytes `[0, source_end_offset)`; `events_sha256` = SHA-256 of the sealed
  batch `events.jsonl` bytes. `pending()` re-hashes the sealed file and raises `StrictLedgerReadError` on a
  mismatch (a tampered/partial batch is never accepted).
- `batch_id` is `str(uuid.uuid4())`; validate any id used as a path component with
  `uuid.UUID(batch_id).version == 4` and reject symlinks (`Path.is_symlink()`) inside the outbox.
- Preparation order = manifest `prepared_at` (UTC ISO-8601, stored in the manifest next to the model fields),
  ties broken by `batch_id`.
- `pending()` excludes batches that have a receipt.
- Never delete source lines, batches, or receipts.

---

## Implementation Blueprint

### Steps (in order)
1. Write the models and exceptions block — *why*: TASK-4858/4859/4860 import these exact names.
2. Write `read_strict_events` — *why*: it is the only reader allowed to authorize delivery (spec §6 note on
   `shared_log.py:78`), and the integrator reuses it for archives and remote logs.
3. Write the atomic-write helpers and `LedgerOutbox` — *why*: G2 durability and the crash AC.
4. Write the tests, using `tmp_path` ledger directories only — *why*: no real ledger may be touched.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py` (CREATE) — part 1: models + reader
```python
"""Durable ledger outbox: sealed, immutable batches of journal events awaiting delivery (FEAT-758)."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.ledger.events import LedgerEvent, canonical_json_dumps, compute_event_id
from parrot.knowledge.wiki.ledger.shared_log import is_shareable

logger = logging.getLogger(__name__)

OUTBOX_DIRNAME = "outbox"


class LedgerBatch(BaseModel):
    """Manifest of one sealed batch (spec §2 Data Models)."""

    schema_version: Literal[1] = 1
    batch_id: str
    source_ref: str
    source_head: str
    source_end_offset: int
    source_sha256: str
    events_sha256: str
    event_ids: list[str]
    remote: str = "origin"
    branch: Literal["dev"] = "dev"
    prepared_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LedgerDeliveryConflict(BaseModel):
    """One event that cannot be delivered without review."""

    event_id: str
    subject: str
    reason: str


class LedgerDeliveryReport(BaseModel):
    """Typed outcome of one delivery attempt sequence (spec §2)."""

    status: Literal["delivered", "already_delivered", "pending", "conflict", "unsupported"]
    batch_id: str
    attempts: int
    remote_head: str | None
    commit_sha: str | None
    added: int
    remaining: int
    conflicts: list[LedgerDeliveryConflict] = Field(default_factory=list)
    error_code: str | None = None
    recovery_path: str | None = None


class LedgerReceipt(BaseModel):
    """Audit record written only after remote content verification."""

    schema_version: Literal[1] = 1
    batch_id: str
    manifest_sha256: str
    remote: str
    branch: str
    remote_head: str
    verified_digest: str
    acknowledged_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class StrictLedgerReadError(ValueError):
    """A complete line is malformed, or an event id does not match its content."""


class OutboxLockedError(RuntimeError):
    """Another preparer holds the outbox lock, or the filesystem cannot lock."""


class StrictRead(BaseModel):
    """Result of a strict read: raw lines + events up to the last complete line."""

    raw_lines: list[bytes]
    events: list[LedgerEvent]
    end_offset: int
    truncated_tail: bool

    model_config = {"arbitrary_types_allowed": True}


def verify_event_identity(event: LedgerEvent) -> None:
    """Raise when ``event.event_id`` is not the hash of its own content."""
    expected = compute_event_id(event.kind, event.subject, event.actor, event.ts, event.payload)
    if event.event_id != expected:
        raise StrictLedgerReadError(f"event {event.event_id!r} does not match its content (expected {expected})")


def read_strict_events(path: Path, *, end_offset: int | None = None) -> StrictRead:
    """Strictly parse complete JSONL lines of ``path`` up to ``end_offset`` (default: last complete line).

    Raises:
        StrictLedgerReadError: on a malformed complete line or an identity mismatch.
    """
    # FILL IN: read bytes (missing file -> empty StrictRead with end_offset=0); cut at end_offset when given,
    #   else at the last b"\n"; truncated_tail=True when non-newline bytes follow the cut. Skip blank lines.
    #   Parse each line with json.loads -> LedgerEvent(**obj); any exception -> StrictLedgerReadError naming
    #   path + 1-based line number. Call verify_event_identity on every event. Keep raw line bytes WITHOUT the
    #   trailing newline in raw_lines — bounded by spec §3 M1 ("malformed complete records fail closed").
    raise NotImplementedError
```
**Why this shape**: the model fields are fixed by spec §2 (only `prepared_at` is added, as the stable
preparation order). Strict identity re-derivation is required because `LedgerEvent.model_post_init` only fills
an empty id (`events.py:113`), so a forged or edited line would otherwise pass. `canonical_json_dumps` is
imported for `LedgerOutbox` receipts/manifests (deterministic JSON on disk).

### `outbox.py` (CREATE) — part 2: atomic helpers + `LedgerOutbox`
```python
def _fsync_dir(path: Path) -> None:
    """Flush a directory entry so a rename survives a crash."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_bytes(dest: Path, data: bytes) -> None:
    """Write ``dest`` via temp file + fsync + os.replace + parent fsync."""
    # FILL IN: tmp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp"); write+flush+os.fsync;
    #   os.replace(tmp, dest); _fsync_dir(dest.parent); remove tmp on any exception — bounded by spec §2.
    raise NotImplementedError


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_batch_id(batch_id: str) -> str:
    """Return ``batch_id`` when it is a UUID4 string, else raise ``ValueError``."""
    # FILL IN: uuid.UUID(batch_id); require .version == 4 and str(parsed) == batch_id.
    raise NotImplementedError


class LedgerOutbox:
    """Own durable pending batches beside one resolved local event journal."""

    def __init__(self, ledger_dir: Path) -> None:
        """Bind an existing local ledger directory without selecting another checkout."""
        self.ledger_dir = Path(ledger_dir).resolve()
        self.source_path = self.ledger_dir / "events.jsonl"
        self.root = self.ledger_dir / OUTBOX_DIRNAME
        self.pending_dir = self.root / "pending"
        self.receipts_dir = self.root / "receipts"
        self.lock_path = self.root / "prepare.lock"
        self.logger = logging.getLogger(__name__)

    async def prepare(
        self, *, repo_root: Path, source_ref: str, source_head: str, known_ids: set[str] | None = None
    ) -> LedgerBatch | None:
        """Seal complete shareable events absent from the fetched dev baseline; return None if empty.

        ``known_ids`` is the destination's logical event-id set supplied by the caller (the integrator reads
        it from fetched ``origin/dev``); this module performs no Git work.
        """
        return await asyncio.to_thread(self._prepare_sync, repo_root, source_ref, source_head, known_ids or set())

    def _prepare_sync(
        self, repo_root: Path, source_ref: str, source_head: str, known_ids: set[str]
    ) -> LedgerBatch | None:
        # FILL IN: mkdir pending/receipts; open lock file, fcntl.flock(LOCK_EX|LOCK_NB) — BlockingIOError or
        #   OSError(ENOLCK/EOPNOTSUPP) -> OutboxLockedError. Under the lock: read_strict_events(source_path);
        #   exclude ids in known_ids and in every un-acknowledged pending batch; keep is_shareable() events
        #   in source order. Empty -> None. Else build temp dir pending/.tmp-<uuid>/ with events.jsonl (raw lines
        #   + b"\n" each) and manifest.json (canonical_json_dumps(batch.model_dump())), fsync both files and the
        #   dir, os.rename to pending/<batch_id>, _fsync_dir(pending_dir). Log batch id + count. `repo_root` is
        #   only validated to exist (provenance lives in source_ref/source_head) — bounded by spec §2 step 1.
        raise NotImplementedError

    async def pending(self) -> list[LedgerBatch]:
        """Return validated unacknowledged batches in preparation order."""
        # FILL IN: via asyncio.to_thread; skip dot-prefixed temp dirs; reject symlinks; validate ids; parse
        #   manifest -> LedgerBatch; re-hash events.jsonl == events_sha256 else StrictLedgerReadError; drop ones
        #   with receipts; sort by (prepared_at, batch_id).
        raise NotImplementedError

    async def batch_events(self, batch: LedgerBatch) -> StrictRead:
        """Strictly read a sealed batch's events (identity-checked, hash-checked)."""
        # FILL IN: read_strict_events(pending_dir/<id>/events.jsonl); event ids must equal batch.event_ids
        #   in order, else StrictLedgerReadError.
        raise NotImplementedError

    async def acknowledge(self, batch: LedgerBatch, *, remote_head: str, verified_digest: str) -> None:
        """Persist a receipt only for the exact remotely verified batch."""
        # FILL IN: manifest_sha256 = _sha256(manifest.json bytes on disk); build LedgerReceipt(remote=batch.remote,
        #   branch=batch.branch, ...); _atomic_write_bytes(receipts/<id>.json, canonical JSON). Idempotent:
        #   rewriting an existing receipt for the same batch is allowed (atomic replace).
        raise NotImplementedError

    async def receipt_for(self, batch_id: str) -> LedgerReceipt | None:
        """Return the receipt for ``batch_id`` or ``None``."""
        # FILL IN: validate id; read + LedgerReceipt.model_validate_json; missing -> None.
        raise NotImplementedError

    async def status(self, known_ids: set[str] | None = None) -> dict[str, int | bool]:
        """Read-only counts: sealed pending batches/events, unsealed shareable events, truncated tail."""
        # FILL IN: no lock, no writes; unsealed = shareable source events not in known_ids nor in any
        #   pending batch. Keys: pending_batches, pending_events, unsealed_events, truncated_tail.
        raise NotImplementedError
```
**Why this shape**: the spec fixes `__init__`, `prepare`, `pending`, `acknowledge`; `known_ids` is added as a
keyword because M1 must stay Git-free while candidates are "absent from the observed origin/dev logical log"
(spec §2) — the integrator supplies that set. Do NOT take the lock in `status()`/`pending()`: producers and
readers never block on preparation.

### `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py` (CREATE)
```python
"""FEAT-758 M1 — durable ledger outbox."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.outbox import (
    LedgerOutbox,
    OutboxLockedError,
    StrictLedgerReadError,
    read_strict_events,
)


def _event(n: int) -> LedgerEvent:
    return LedgerEvent(kind="insight.recorded", subject=f"spec:FEAT-{n}", actor="agent:test",
                       ts=f"2026-10-27T00:00:{n:02d}+00:00", payload={"fact": str(n), "title": str(n),
                       "derived_from": "spec:FEAT-758"})


@pytest.fixture
def ledger_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".parrot" / "ledger"
    d.mkdir(parents=True)
    return d


async def test_seals_only_complete_prefix(ledger_dir: Path, tmp_path: Path) -> None:
    """A trailing partial line stays pending and is reported, never sealed."""
    # FILL IN: append 2 events via LedgerLog, then write a partial line without "\n"; prepare() seals 2 ids;
    #   status()["truncated_tail"] is True.


async def test_malformed_complete_line_fails_closed(ledger_dir: Path, tmp_path: Path) -> None:
    # FILL IN: complete garbage line -> StrictLedgerReadError from prepare(); no pending/ batch dir created.


async def test_identity_collision_rejected(ledger_dir: Path) -> None:
    # FILL IN: write a line whose event_id belongs to different content -> read_strict_events raises.


async def test_later_append_goes_to_next_batch(ledger_dir: Path, tmp_path: Path) -> None:
    # FILL IN: prepare (batch A), append event, prepare (batch B holds only the new id); pending() order A, B.


async def test_known_ids_and_local_only_excluded(ledger_dir: Path, tmp_path: Path) -> None:
    # FILL IN: known_ids filters; a coder-suspension insight (is_shareable False) is never sealed.


async def test_crash_during_seal_leaves_no_batch(ledger_dir: Path, tmp_path: Path, monkeypatch) -> None:
    # FILL IN: monkeypatch os.rename (in outbox module) to raise; prepare raises; pending() == []; source
    #   journal bytes unchanged; a retry after removing the patch seals the same ids.


async def test_tampered_batch_rejected_and_receipt_hides_batch(ledger_dir: Path, tmp_path: Path) -> None:
    # FILL IN: edit sealed events.jsonl -> pending() raises; fresh batch + acknowledge() -> pending() == [] and
    #   receipt_for() returns the receipt.


async def test_second_preparer_is_locked_out(ledger_dir: Path, tmp_path: Path) -> None:
    # FILL IN: hold fcntl.flock on outbox/prepare.lock from the test; prepare() raises OutboxLockedError.
```
**Why**: one test per M1 row of spec §4 (complete-prefix sealing, crash during seal/receipt, identity collision)
plus the lock and filter rules. pytest-asyncio auto mode is assumed by sibling tests in this directory; if a
test is not collected as async, add `pytestmark = pytest.mark.asyncio`.

### FILL IN checklist
- [ ] `read_strict_events` — complete-line cut, truncation flag, identity check; bounded by spec §3 M1
- [ ] `_atomic_write_bytes` / `_validate_batch_id` — durability + path safety; bounded by spec §2
- [ ] `LedgerOutbox._prepare_sync` — lock, candidate filter, temp-dir seal + rename; bounded by spec §2 step 1
- [ ] `pending` / `batch_events` / `acknowledge` / `receipt_for` / `status` — bounded by AC "Sealed batches are
      immutable, bounded, validated"
- [ ] All 8 tests

---

## Acceptance Criteria

- [ ] Concurrent later append remains pending; malformed complete record fails (spec §4 M1 row 1)
- [ ] Crash during seal or receipt leaves the source retained, no partial batch accepted, no false receipt
- [ ] Equal ID with different body is rejected
- [ ] No import of `subprocess` / Git in `outbox.py`; no change to `log.py` or `service.py`
- [ ] `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py -q`

---

## Test Specification

See the test blueprint above; the eight named tests are the minimum.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug ledger-outbox-integration --feature-id FEAT-758`).
2. Read spec §2 and §3 Module 1.
3. Verify the Codebase Contract; update it first if anything moved.
4. Set `in-progress` in `sdd/tasks/index/ledger-outbox-integration.json`, commit only that file.
5. Implement from the blueprint, completing every `# FILL IN:`; never change a fixed signature.
6. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
7. Commit only the two listed files; close with `scripts/sdd/close_task.sh TASK-4857 ledger-outbox-integration verified`.

---

## Completion Note

*(Agent fills this in when done)*
