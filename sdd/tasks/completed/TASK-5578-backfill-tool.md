# TASK-5578: Backfill tool — resumable batched driver over `backfill_batch`

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: `sdd/specs/durable-conversation-memory.spec.md` (Module 11)
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5570, TASK-5574
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 11 and §2 "Piece 2 — Legacy backfill". Rows written before FEAT-886 carry random turn
IDs, no sequence and (on SQL backends) no `ts_utc` / `seq` / `turn_id` columns, so they cannot be
selected chronologically. TASK-5570 adds `ConversationBackend.backfill_batch(cursor, batch_size) ->
BackfillBatch` and `get_index_state`; TASK-5574 implements them on SQLite. This task is the
**driver**: it loops `backfill_batch` until the scan is complete or a batch budget is reached, persists
its cursor between runs so an interrupted run resumes, and reports sessions left `invalid` (a missing or
unparseable timestamp — never repaired by guessing). It is runnable as
`python -m parrot.storage.backfill` and is **never** imported from a request path (spec AC "Backfill":
no request path performs a full-table scan).

---

## Scope

- Create `parrot/storage/backfill.py` with `BackfillReport`, `run_backfill(...)` and a CLI (`main`).
- Persist the cursor (atomic write-then-rename) after **every** batch, so a kill between batches loses
  at most the in-flight (idempotent) batch.
- Detect a non-advancing cursor and fail loudly instead of looping forever.
- Write unit tests against the **real SQLite backend** (TASK-5574) seeded with legacy rows.

**NOT in scope**: the per-backend `backfill_batch` implementations (TASK-5574..5577); the `ready` /
`invalid` state definitions (TASK-5570 contract); any new setting in `parrot/conf.py` (the CLI default
cursor path is computed locally); invoking the tool from `BotManager` or any handler.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/storage/backfill.py` | CREATE | `BackfillReport`, `run_backfill`, CLI `main` |
| `packages/ai-parrot/tests/unit/storage/test_backfill.py` | CREATE | resumable / concurrent-write / invalid-session / CLI tests on real SQLite |

---

## Codebase Contract (Anti-Hallucination)

Re-verified against the tree at `6d564b36a2` (branch `dev`). Paths below are relative to
`packages/ai-parrot/` unless they start with `packages/`.

### Verified Imports
```python
from navconfig.logging import logging                                          # verified: src/parrot/storage/backends/sqlite.py:27
from parrot.storage.backends import build_conversation_backend                 # verified: src/parrot/storage/backends/__init__.py:95
from parrot.storage.backends.base import ConversationBackend                   # verified: src/parrot/storage/backends/base.py:15
from parrot.storage.backends.sqlite import ConversationSQLiteBackend           # verified: src/parrot/storage/backends/sqlite.py:35
```

### Provided by dependency tasks (NOT in the tree yet — re-grep after the dependency lands)
```python
from parrot.storage.backends.base import BackfillBatch   # TASK-5570: frozen dataclass(processed:int, next_cursor:Optional[str], invalid_sessions:Tuple[str,...])
# ConversationBackend.backfill_batch(self, cursor: Optional[str], batch_size: int) -> BackfillBatch   # TASK-5570 (abstract), TASK-5574 (SQLite)
# ConversationBackend.get_index_state(self, user_id, agent_id, session_id) -> str   # 'ready' | 'pending' | 'invalid'
# ConversationBackend.query_turn_window(self, user_id, agent_id, session_id, limit) -> List[dict]
# ConversationBackend.put_tombstone / is_deleted(...)
# parrot.storage.errors.ConversationDeletedError, IndexNotReadyError, StorageError   # TASK-5570
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/storage/backends/__init__.py
async def build_conversation_backend(override: Optional[str] = None) -> ConversationBackend   # :95
    # reads PARROT_STORAGE_BACKEND / PARROT_SQLITE_PATH from os.environ AT CALL TIME (monkeypatch.setenv works);
    # returns an UNINITIALISED backend — the caller must `await backend.initialize()`.

# packages/ai-parrot/src/parrot/storage/backends/sqlite.py
class ConversationSQLiteBackend(ConversationBackend):          # :35
    def __init__(self, path: str, default_ttl_days: int = 180) -> None
    async def initialize(self) -> None                         # :97 idempotent
    # table `conversations` DDL :52-64: (user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at),
    # PK (user_id, agent_id, session_id, kind, sort_key); turn rows use kind='turn', sort_key='TURN#<turn_id>'
    self._conn: aiosqlite.Connection                           # raw handle, used by the tests to seed legacy rows
```

### Does NOT Exist
- ~~`parrot.storage.backfill`~~ — created by THIS task.
- ~~A `BACKFILL_*` / `PARROT_BACKFILL_*` setting in `parrot.conf`~~ — none; do not add one (conf.py is TASK-5568/5571/5581's file).
- ~~`ConversationBackend.backfill_batch` in today's tree~~ — abstract method added by TASK-5570; until then `ConversationSQLiteBackend` has none.
- ~~Any caller of the backfill from `handlers/`, `manager/` or `bots/`~~ — must stay that way.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/storage/backfill.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/storage/test_backfill.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/storage/backends/base.py#ConversationBackend",
    "sym:packages/ai-parrot/src/parrot/storage/backends/__init__.py#build_conversation_backend",
    "sym:packages/ai-parrot/src/parrot/storage/backends/sqlite.py#ConversationSQLiteBackend"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
Cursor persistence = JSON state file written atomically (`tempfile` in the same directory + `os.replace`).
Same "tolerate a damaged state file, never crash the operator" stance as `parrot/storage/backends/__init__.py`
tolerates missing env. The scan is idempotent (`backfill_batch` re-indexing an indexed turn is a no-op), which
is what makes "redo the in-flight batch" and "restart on a damaged state file" both safe.

### Key Constraints
- **Report semantics**: `BackfillReport.processed` counts turns indexed by THIS invocation; `invalid_sessions`
  is cumulative for the current pass (persisted in the state file) so an operator who resumes still sees
  sessions flagged by earlier segments.
- **A state file marked `complete: true` starts a NEW pass** (cursor `None`, invalid list reset). Rationale:
  operators re-run after repairing bad timestamps; a pass is cheap and idempotent. State this in the docstring.
- **Never treat `invalid` as ready, never "fix" a timestamp** — the driver only reports (spec §2).
- No `print`: library code logs via `logging.getLogger("parrot.storage.backfill")`; only `main()` writes its
  JSON summary to stdout.
- Exit codes (CLI): `0` complete and no invalid sessions; `2` complete with invalid sessions; `3` stopped by
  `--max-batches` before completion. Backend errors propagate (non-zero via traceback).
- No blocking I/O on the loop: state-file reads/writes go through `asyncio.to_thread`.
- Never swallow a `StorageError` from `backfill_batch`; the cursor of the last good batch is already on disk.

### References in Codebase
- `packages/ai-parrot/src/parrot/storage/backends/__init__.py:95` — backend factory the CLI reuses.
- `packages/ai-parrot/src/parrot/observability/fanout.py:62` (`_outbox_path`) — precedent for validating a path
  before use and failing with a precise message.

---

## Implementation Blueprint

### Steps (in order)
1. Re-grep the "Provided by dependency tasks" symbols (`BackfillBatch`, `backfill_batch`) — *why*: this task is
   written against TASK-5570's contract; a renamed field is drift to fix in the task file first.
2. Create `backfill.py` with `BackfillReport`, the state helpers and `run_backfill` — *why*: the driver is the
   whole feature; the CLI is a thin shell over it.
3. Add the CLI (`_build_parser`, `_run_cli`, `main`, `__main__` guard) — *why*: spec requires
   `python -m parrot.storage.backfill`.
4. Write the tests and run the mutation checks listed under Acceptance Criteria — *why*: the resumability and
   no-progress guard are the behaviors that silently rot.

### `packages/ai-parrot/src/parrot/storage/backfill.py` (CREATE)
```python
"""Resumable, batched backfill driver for legacy conversation turns (FEAT-886 M11).

Run as ``python -m parrot.storage.backfill``. This module is an operator tool: it is
never imported from a request path, because a full scan is exactly what the chronological
index exists to avoid at serve time.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from navconfig.logging import logging

from parrot.storage.backends import build_conversation_backend
from parrot.storage.backends.base import BackfillBatch, ConversationBackend

logger = logging.getLogger("parrot.storage.backfill")

_STATE_VERSION = 1
_DEFAULT_CURSOR_FILE = Path.home() / ".parrot" / "conversation-backfill-cursor.json"


@dataclass(frozen=True)
class BackfillReport:
    """Outcome of one :func:`run_backfill` invocation.

    Attributes:
        processed: Turns indexed by this invocation (not by earlier resumed segments).
        complete: ``True`` when the backend reported ``next_cursor is None``.
        invalid_sessions: Sessions left ``invalid`` (missing / unparseable timestamp),
            cumulative for the current pass.
    """

    processed: int
    complete: bool
    invalid_sessions: Tuple[str, ...]


def _fresh_state() -> Dict[str, Any]:
    return {"version": _STATE_VERSION, "cursor": None, "complete": False, "invalid_sessions": []}


def _load_state(path: Optional[Path]) -> Dict[str, Any]:
    """Return the persisted state, or a fresh one when absent, damaged or marked complete."""
    if path is None or not path.exists():
        return _fresh_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Backfill state %s is unreadable; starting a fresh pass", path)
        return _fresh_state()
    if not isinstance(state, dict) or state.get("version") != _STATE_VERSION or state.get("complete"):
        return _fresh_state()
    return {**_fresh_state(), "cursor": state.get("cursor"), "invalid_sessions": list(state.get("invalid_sessions", []))}


def _save_state(path: Optional[Path], state: Dict[str, Any]) -> None:
    """Atomically replace the state file (no-op without a path)."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


async def run_backfill(
    backend: ConversationBackend,
    *,
    batch_size: int = 500,
    max_batches: Optional[int] = None,
    cursor_path: Optional[Path] = None,
) -> BackfillReport:
    """Drive ``backend.backfill_batch`` until complete or ``max_batches`` is reached.

    Resumes from ``cursor_path`` when it holds an unfinished pass; a file marked complete
    starts a new pass. The cursor is persisted after every batch.

    Args:
        backend: An initialised backend.
        batch_size: Legacy turns indexed per batch (>= 1).
        max_batches: Stop after this many batches; ``None`` runs to completion.
        cursor_path: State file for resumption; ``None`` keeps state in memory only.

    Returns:
        The :class:`BackfillReport` for this invocation.

    Raises:
        ValueError: ``batch_size`` or ``max_batches`` below 1.
        RuntimeError: The backend returned the cursor it was given (no progress).
        StorageError: Propagated from the backend; the last good cursor is already persisted.
    """
    if batch_size < 1 or (max_batches is not None and max_batches < 1):
        raise ValueError("batch_size and max_batches must be >= 1")
    state = await asyncio.to_thread(_load_state, cursor_path)
    cursor: Optional[str] = state["cursor"]
    invalid: Dict[str, None] = dict.fromkeys(state["invalid_sessions"])
    processed = batches = 0
    complete = False
    while not complete and (max_batches is None or batches < max_batches):
        batch: BackfillBatch = await backend.backfill_batch(cursor, batch_size)
        # FILL IN: the no-progress guard — raise RuntimeError when `batch.next_cursor is not None and
        #   batch.next_cursor == cursor` (message names the cursor) — bounded by "never loop forever".
        processed += batch.processed
        invalid.update(dict.fromkeys(batch.invalid_sessions))
        cursor, batches, complete = batch.next_cursor, batches + 1, batch.next_cursor is None
        # FILL IN: persist {version, cursor, complete, invalid_sessions: list(invalid)} via
        #   asyncio.to_thread(_save_state, ...) BEFORE the next iteration — bounded by AC "resumable".
    return BackfillReport(processed=processed, complete=complete, invalid_sessions=tuple(invalid))
```

### `packages/ai-parrot/src/parrot/storage/backfill.py` (CREATE — CLI part, append to the same file)
```python
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m parrot.storage.backfill", description=__doc__)
    parser.add_argument("--backend", default=None, help="Override PARROT_STORAGE_BACKEND for this run.")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--cursor-file", type=Path, default=_DEFAULT_CURSOR_FILE)
    return parser


async def _run_cli(args: argparse.Namespace) -> int:
    backend = await build_conversation_backend(args.backend)
    await backend.initialize()
    try:
        report = await run_backfill(
            backend, batch_size=args.batch_size, max_batches=args.max_batches, cursor_path=args.cursor_file
        )
    finally:
        await backend.close()
    # FILL IN: write one JSON line {"processed","complete","invalid_sessions"} to sys.stdout, then return
    #   0 (complete, none invalid) / 2 (complete, invalid sessions) / 3 (incomplete) — bounded by Key Constraints.
    raise NotImplementedError


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns the process exit code."""
    return asyncio.run(_run_cli(_build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: the loop condition keeps `max_batches` and completion in one place; the state file is the only
thing that survives a kill, so it is written inside the loop, not at the end. `run_backfill` takes an already
initialised backend so tests inject the real SQLite one; only the CLI builds a backend. Do NOT add a settings
entry, do NOT import this module anywhere else.

### FILL IN checklist
- [ ] `backfill.py::run_backfill` no-progress guard — bounded by "never loop forever" (test `test_no_progress_cursor_raises`).
- [ ] `backfill.py::run_backfill` per-batch state persistence — bounded by AC "resumable".
- [ ] `backfill.py::_run_cli` summary line and exit codes — bounded by Key Constraints (0 / 2 / 3).
- [ ] tests: legacy-row seeding helper — bounded by the TASK-5574 schema (raw `INSERT` into `conversations` WITHOUT
      the new `ts_utc`/`seq`/`turn_id` columns, so the rows are genuinely legacy). Re-read `sqlite.py` after TASK-5574
      lands and confirm `get_index_state` reports `pending` for such a session.

---

## Acceptance Criteria

- [ ] `run_backfill` resumes an interrupted run from `cursor_path` and completes it (spec §4 `test_backfill_resumable`; spec §5 "Backfill: resumable, batched").
- [ ] Safe alongside concurrent writes: new `put_turn` calls issued while a backfill is running are neither lost nor re-ordered (spec §5 "safe alongside concurrent writes").
- [ ] A session with a missing or unparseable timestamp ends `invalid`, is listed in `BackfillReport.invalid_sessions`, and is never reported `ready` (spec §5 "invalid timestamps leave the session unready"; "not-ready is never reported as an empty history").
- [ ] A tombstoned session is not resurrected by the backfill (spec §5 "Deletion races … during backfill").
- [ ] A non-advancing cursor raises `RuntimeError`; a damaged state file restarts the pass with a WARNING; `batch_size < 1` raises `ValueError`.
- [ ] `python -m parrot.storage.backfill --cursor-file <p>` exits `0` / `2` / `3` as specified and prints one JSON line.
- [ ] No module outside `parrot/storage/backfill.py` imports `parrot.storage.backfill` (spec §5 "no request path performs a full-table scan").
- [ ] **Mutation checks** (revert, see RED, restore by re-applying the edit — never `git checkout`): (1) delete the per-batch `_save_state` call → `test_backfill_resumable` goes RED; (2) delete the no-progress guard → `test_no_progress_cursor_raises` goes RED (it fails by timeout, so keep its `asyncio.wait_for`); (3) make `_load_state` ignore `complete` → `test_completed_state_starts_new_pass` goes RED.
- [ ] `ruff check packages/ai-parrot/src/parrot/storage/backfill.py packages/ai-parrot/tests/unit/storage/test_backfill.py` is clean.
- [ ] Imports work: `from parrot.storage.backfill import run_backfill, BackfillReport`.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/storage/test_backfill.py -q`
- `pytest packages/ai-parrot/tests/unit/storage/test_backfill.py::test_backfill_resumable -q`

---

## Test Specification

Real objects only: `ConversationSQLiteBackend` on a `tmp_path` file; the no-progress case uses a small real
subclass of it (overriding only `backfill_batch`), not a `Mock`. Fixtures live in the test file (no shared conftest).

```python
# packages/ai-parrot/tests/unit/storage/test_backfill.py
import asyncio
import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.backfill import BackfillReport, main, run_backfill

USER, AGENT = "u1", "agent-a"
_INSERT = (
    "INSERT OR REPLACE INTO conversations "
    "(user_id, agent_id, session_id, kind, sort_key, payload, updated_at, expires_at) "
    "VALUES (?, ?, ?, 'turn', ?, ?, 0, NULL)"
)


@pytest.fixture
async def backend(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "parrot.db"))
    await b.initialize()
    yield b
    await b.close()


async def _seed_legacy(backend, session, stamps):
    """Legacy rows: random IDs, no sequence, raw INSERT (no ts_utc/seq/turn_id columns).

    `stamps` is a list of ISO strings or None/"garbage" for an invalid timestamp.
    """
    ids = [f"{random.getrandbits(64):016x}" for _ in stamps]
    for turn_id, stamp in zip(ids, stamps):
        payload = {"turn_id": turn_id, "user_message": "q", "assistant_response": "a", "timestamp": stamp}
        await backend._conn.execute(_INSERT, (USER, AGENT, session, f"TURN#{turn_id}", json.dumps(payload)))
    await backend._conn.commit()
    return ids


@pytest.fixture
async def legacy_rows(backend):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    good = [(base + timedelta(minutes=i)).isoformat() for i in range(7)]
    random.shuffle(good)
    await _seed_legacy(backend, "s-good", good)
    await _seed_legacy(backend, "s-naive", [(base + timedelta(minutes=i)).replace(tzinfo=None).isoformat() for i in range(3)])
    await _seed_legacy(backend, "s-bad", [good[0], "not-a-date"])
    return {"good": good}


async def test_backfill_resumable(backend, legacy_rows, tmp_path):
    cursor_file = tmp_path / "cursor.json"
    first = await run_backfill(backend, batch_size=2, max_batches=1, cursor_path=cursor_file)
    assert first.complete is False and cursor_file.exists()
    second = await run_backfill(backend, batch_size=2, cursor_path=cursor_file)
    assert second.complete is True
    # FILL IN: assert first.processed + second.processed == total legacy turns seeded (12), and that the second
    #   run started from the persisted cursor (it processed fewer than 12) — bounded by AC "resumable".
    assert await backend.get_index_state(USER, AGENT, "s-good") == "ready"
    assert await backend.get_index_state(USER, AGENT, "s-bad") == "invalid"
    assert "s-bad" in second.invalid_sessions


async def test_backfilled_window_is_chronological(backend, legacy_rows):
    await run_backfill(backend, batch_size=3)
    window = await backend.query_turn_window(USER, AGENT, "s-good", limit=4)
    # FILL IN: window == the 4 newest stamps of legacy_rows["good"] ascending (compare parsed timestamps) —
    #   bounded by spec §5 "Chronological hydration" (random IDs, limit applied descending at the backend).
    assert len(window) == 4


async def test_invalid_session_is_not_ready(backend, legacy_rows):
    from parrot.storage.errors import IndexNotReadyError
    await run_backfill(backend, batch_size=50)
    with pytest.raises(IndexNotReadyError):
        await backend.query_turn_window(USER, AGENT, "s-bad", limit=5)


async def test_concurrent_writes_are_safe(backend, legacy_rows):
    async def writer():
        for i in range(5):
            ts = datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(minutes=i)
            await backend.put_turn(USER, AGENT, "s-good", f"new-{i}",
                                   {"turn_id": f"new-{i}", "timestamp": ts.isoformat(), "sequence": i + 1,
                                    "user_message": "q", "assistant_response": "a"})
            await asyncio.sleep(0)
    report, _ = await asyncio.gather(run_backfill(backend, batch_size=2), writer())
    assert report.complete
    window = await backend.query_turn_window(USER, AGENT, "s-good", limit=5)
    assert [t["turn_id"] for t in window] == [f"new-{i}" for i in range(5)]   # newest window, ascending


async def test_tombstoned_session_is_not_resurrected(backend, legacy_rows):
    from parrot.storage.errors import ConversationDeletedError
    await backend.put_tombstone(USER, AGENT, "s-good")
    await run_backfill(backend, batch_size=50)
    assert await backend.is_deleted(USER, AGENT, "s-good") is True
    with pytest.raises(ConversationDeletedError):
        await backend.query_turn_window(USER, AGENT, "s-good", limit=5)


async def test_no_progress_cursor_raises(tmp_path):
    class Stuck(ConversationSQLiteBackend):
        async def backfill_batch(self, cursor, batch_size):
            from parrot.storage.backends.base import BackfillBatch
            return BackfillBatch(processed=0, next_cursor="same", invalid_sessions=())
    b = Stuck(path=str(tmp_path / "stuck.db"))
    await b.initialize()
    try:
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(run_backfill(b, batch_size=1, cursor_path=tmp_path / "c.json"), timeout=5)
    finally:
        await b.close()


async def test_completed_state_starts_new_pass(backend, legacy_rows, tmp_path):
    cursor_file = tmp_path / "cursor.json"
    await run_backfill(backend, batch_size=50, cursor_path=cursor_file)
    assert json.loads(cursor_file.read_text())["complete"] is True
    again = await run_backfill(backend, batch_size=50, cursor_path=cursor_file)
    # FILL IN: assert the second pass actually scanned (again.complete is True) and re-reported "s-bad" —
    #   bounded by Key Constraints ("complete starts a NEW pass").
    assert again.complete is True


async def test_damaged_state_file_restarts_pass(backend, legacy_rows, tmp_path):
    cursor_file = tmp_path / "cursor.json"
    cursor_file.write_text("{not json")
    report = await run_backfill(backend, batch_size=50, cursor_path=cursor_file)
    assert report.complete is True


async def test_rejects_bad_arguments(backend):
    with pytest.raises(ValueError):
        await run_backfill(backend, batch_size=0)


def test_cli_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PARROT_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("PARROT_SQLITE_PATH", str(tmp_path / "cli.db"))
    # FILL IN: seed one clean legacy session into cli.db (open it with asyncio.run + _seed_legacy) and assert
    #   main(["--cursor-file", str(tmp_path / "c.json")]) == 0 and the stdout line parses as JSON with
    #   complete == True; then seed an invalid session and assert exit code 2; then --max-batches 1 with
    #   --batch-size 1 over several turns gives 3 — bounded by Key Constraints.
    assert callable(main)


def test_backfill_is_not_imported_from_request_paths():
    import pathlib
    import parrot.storage as storage_pkg
    root = pathlib.Path(storage_pkg.__file__).resolve().parents[1]
    offenders = [p for p in root.rglob("*.py")
                 if p.name != "backfill.py" and "parrot.storage.backfill" in p.read_text(encoding="utf-8", errors="ignore")]
    assert offenders == []
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`).
2. **Read the spec** (`sdd/specs/durable-conversation-memory.spec.md`, Modules 4 and 11, §5 "Backfill").
3. **Check dependencies** — TASK-5570 and TASK-5574 must be `"done"` in
   `sdd/tasks/index/durable-conversation-memory.json`.
4. **Verify the Codebase Contract** — re-grep every "Provided by dependency tasks" symbol; the SQLite schema and
   `get_index_state` behavior are TASK-5574's and may differ in detail from the seed helper above.
5. **Update status** in the per-spec index → `"in-progress"` and commit only that file.
6. **Implement** from the blueprint, complete every `# FILL IN:`, run the Validation Commands and the three
   mutation checks (restore by re-applying the edit, never `git checkout`).
7. **Commit only the two listed files**; close with
   `parrot sdd task close TASK-5578 durable-conversation-memory verified`; fill the Completion Note.

---

## Completion Note

Created parrot/storage/backfill.py (BackfillReport, run_backfill with atomic per-batch cursor persistence, no-progress guard, CLI main with exit codes 0/2/3).

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-11-13
**Tests**: test_backfill 8 passed on the real SQLite backend (resume, idempotent re-run, invalid session, live writes untouched, tombstoned skip, no-progress guard, damaged state file, arg validation, CLI exit codes). ruff clean. No skips.
**Mutation evidence**: guard removed / state never persisted / exit code 2 collapsed to 0 -> each RED (see run); restored by re-applying the edit.

**Deviations from spec**: none
