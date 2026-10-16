# TASK-4405: Shared-log core — `LedgerLog.append_line` + `ledger/shared_log.py` export/import

**Feature**: FEAT-694 — Shared Ledger Event Log (cross-machine sync via git hooks)
**Spec**: `sdd/specs/ledger-shared-event-log.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (1)+(2) and §3 Module 1. The ledger event log is per machine; this task
builds the pure, synchronous core that copies event lines verbatim between a machine's
`LedgerLog` and the committed logical shared log (`sorted(sdd/ledger/archive/events-*.jsonl)
+ [sdd/ledger/events.jsonl]`), deduplicated by content-addressed `event_id`, with a
SHA-256 marker fast path for import. Every later task builds on these functions.

---

## Scope

- Add `LedgerLog.append_line(line: str) -> int` to `ledger/log.py` (same O_APPEND + fsync +
  4096-byte cap as `append`).
- Create `ledger/shared_log.py` with the constants and models of spec §2 Data Models and the
  functions `is_shareable`, `read_raw_events`, `shared_log_files`, `read_shared_event_ids`,
  `digest_files`, `export_events`, `import_events`.
- Write `tests/knowledge/wiki/test_ledger_shared_log.py` (unit tests marked M1 in spec §4,
  plus `test_export_skips_ids_present_in_archive` and `test_import_reads_archives_then_current`).

**NOT in scope**: `rotate_events` (TASK-4408 adds it to this same file); any `LedgerService`
or CLI change (TASK-4406); hooks (TASK-4407); committing `sdd/ledger/events.jsonl` (TASK-4410).
Define `SharedLogRotateReport` here anyway (it is a pure model in §2 Data Models) so TASK-4408
only adds the function.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` | MODIFY | add `append_line` before `iter_events` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` | CREATE | constants, models, export/import core |
| `tests/knowledge/wiki/test_ledger_shared_log.py` | CREATE | M1 unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.events import LedgerEvent                          # verified: ledger/events.py:103
from parrot.knowledge.wiki.ledger.log import LedgerLog                              # verified: ledger/log.py:10
from parrot.knowledge.wiki.ledger.coder_suspensions import CODER_SUSPENSION_CATEGORY # verified: ledger/coder_suspensions.py:42
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py
class LedgerLog:                                                                    # line 10
    def __init__(self, path: str) -> None                                           # line 13 — self.path is a str
    def append(self, event: LedgerEvent) -> tuple[str, int]                         # line 21 — encodes, >4096 → ValueError (56),
                                                                                     #   os.open(O_APPEND|O_WRONLY|O_CREAT) (60), lseek end, one os.write, os.fsync (77)
    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]] # line 83 — skips malformed lines with WARNING (116-121)

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
class LedgerEvent(BaseModel):                                                       # line 103
    event_id: str = Field(default="")   # line 106 — computed in model_post_init (113) when empty
    kind: LedgerEventKind; subject: str; actor: str; ts: str; payload: dict[str, Any]
def compute_event_id(kind, subject, actor, ts, payload) -> str                      # line 88

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
def _read_snapshot_rows(dest: Path) -> list[dict[str, Any]]                         # line 52 — WARNING-with-line-number + skip pattern to mirror
```

### Does NOT Exist
- ~~`LedgerLog.append_line()`~~ / ~~`LedgerLog.append_raw()`~~ — you are adding `append_line`; nothing else.
- ~~`parrot.knowledge.wiki.ledger.shared_log`~~ — you create it.
- ~~`LedgerEvent.machine_id`~~ — events carry no machine identity; dedup is by `event_id` only.
- ~~`fcntl` locking in the ledger~~ — appends are lock-free; do not add a lock.
- ~~`ORIG_HEAD`~~ — must not be referenced anywhere (AC9).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py", "action": "CREATE"},
    {"path": "tests/knowledge/wiki/test_ledger_shared_log.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py#LedgerLog",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py#LedgerEvent",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_suspensions.py#CODER_SUSPENSION_CATEGORY"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Raw-line verbatim copy**: export and import move the original line text; never
  re-serialize via `model_dump_json()` — so the same event is byte-identical on every machine
  and `merge=union` collapses identical lines.
- All functions here are **synchronous** (blocking file I/O); the service wraps them in
  `asyncio.to_thread` (TASK-4406).
- `export_events` never rewrites, reorders or removes a line of the destination — it only
  opens it in append mode.
- `import_events` writes the marker **last**, atomically (`tmp` + `os.replace`), so a crash
  mid-import re-runs the (idempotent) import instead of skipping it.
- Logging via `logger = logging.getLogger(__name__)`; no `print`.

### References in Codebase
- `ledger/log.py:21-81` — the write path `append_line` must reuse (factor a private
  `_write_encoded(encoded: bytes) -> int` helper shared by both if you like — keep `append`'s
  behaviour and return value unchanged).
- `ledger/service.py:52` — WARNING + skip pattern for unparseable lines.

---

## Implementation Blueprint

### Steps (in order)
1. Add `append_line` to `LedgerLog` above `iter_events` — *why*: import must append foreign
   lines with their exact bytes so `event_id` matches on every machine.
2. Create `shared_log.py` with constants + models verbatim from spec §2 — *why*: TASK-4406/4408
   import these names; signatures are fixed by the spec skeleton.
3. Implement the read helpers, then `export_events`, then `import_events` — *why*: export and
   import both depend on `read_raw_events` / `shared_log_files`.
4. Write the tests; run the Validation Commands.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:' log.py)
# BEFORE — insert above `    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:` (verified: ledger/log.py:83)
    def append_line(self, line: str) -> int:
        """Append one already-serialized event line verbatim.

        Adds the trailing newline when missing. Same guarantees as :meth:`append`:
        a single ``os.write`` under ``O_APPEND``, ``os.fsync`` before close, and a
        ``ValueError`` when the encoded line exceeds 4096 bytes. Used by the shared-log
        import so a foreign line keeps its exact bytes (and therefore its ``event_id``).

        Args:
            line: One JSON event line, with or without its trailing newline.

        Returns:
            The start byte offset (informational — see the caveat on :meth:`append`).

        Raises:
            ValueError: If the encoded line exceeds 4 KiB (4096 bytes).
        """
        # FILL IN: encode `line if line.endswith("\n") else line + "\n"`, enforce the 4096 cap,
        # then the exact open/lseek/write/fsync/close sequence of append() (log.py:60-79) —
        # bounded by: never a second write call, never a lock.
```
**Why**: spec §3 M1 skeleton; reusing the append path keeps the lock-free atomic-append
guarantee (spec §7 "Concurrent local append during import").

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` (CREATE)
```python
"""Shared ledger event log: append-only export/import between a machine's log and git (FEAT-694)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.ledger.coder_suspensions import CODER_SUSPENSION_CATEGORY
from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog

logger = logging.getLogger(__name__)

SHARED_LOG_REL_PATH: Path = Path("sdd/ledger/events.jsonl")
ARCHIVE_REL_DIR: Path = Path("sdd/ledger/archive")
ARCHIVE_FILENAME_FMT: str = "events-{yyyy_mm}.jsonl"
MARKER_FILENAME: str = "shared_log.marker"
ROTATION_DAYS_DEFAULT: int = 30
TERMINAL_ISSUE_STATUSES: frozenset[str] = frozenset({"closed", "superseded"})
LOCAL_ONLY_INSIGHT_CATEGORIES: frozenset[str] = frozenset({CODER_SUSPENSION_CATEGORY})


# FILL IN: SharedLogRotateReport, ClaimConflict, SharedLogExportReport, SharedLogImportReport —
# copy field-for-field from spec §2 "Data Models" (names, types, defaults, docstrings).


def is_shareable(event: LedgerEvent) -> bool:
    """Return False only for local-only ``insight.*`` categories (seat suspension state)."""
    return not (
        event.kind.startswith("insight.") and event.payload.get("category") in LOCAL_ONLY_INSIGHT_CATEGORIES
    )


def read_raw_events(path: Path) -> list[tuple[str, LedgerEvent]]:
    """Return ``(raw_line_without_newline, event)`` for every parseable line, in file order."""
    # FILL IN: [] when missing; json.loads + LedgerEvent(**obj) per non-blank line; on failure
    # logger.warning("%s:%d unparseable ledger line skipped", path, lineno) — mirrors service.py:52


def shared_log_files(repo_root: Path) -> list[Path]:
    """``sorted(archive/events-*.jsonl) + [events.jsonl]`` under ``repo_root``, existing only."""
    # FILL IN: bounded by spec §2 "logical shared log" definition


def read_shared_event_ids(files: list[Path]) -> set[str]:
    """Union of ``event_id`` over every parseable line of ``files``."""
    # FILL IN


def digest_files(files: list[Path]) -> str:
    """SHA-256 hex over ``f"{rel_path}\\0{sha256(bytes)}\\n"`` per file in order; ``""`` when empty."""
    # FILL IN: rel_path must be stable across machines — use the path relative to the repo root
    # (e.g. `f.relative_to(f.parents[2])` is fragile; prefer passing names like
    # `sdd/ledger/archive/events-2026-08.jsonl` — derive from the last 3-4 parts) — bounded by AC9


def export_events(local: LedgerLog, repo_root: Path) -> SharedLogExportReport:
    """Append shareable local events unknown to the logical shared log, verbatim, local order."""
    # FILL IN: known = read_shared_event_ids(shared_log_files(repo_root)); iterate
    # read_raw_events(Path(local.path)); skip not is_shareable (count skipped_local_only) and
    # known ids; mkdir parents; open dest in "a" mode, write each raw + "\n"; also add the id to
    # `known` so a duplicate line in the local log is exported once — bounded by AC1, AC5, AC17


def import_events(
    local: LedgerLog, repo_root: Path, marker: Path, *, force: bool = False
) -> tuple[SharedLogImportReport, list[LedgerEvent]]:
    """Append committed events unknown locally (archives first, then current) via ``append_line``."""
    # FILL IN: files = shared_log_files(repo_root); digest = digest_files(files);
    # fast path when not force and marker exists and its text == digest (do not read `local`);
    # else known = {e.event_id for e, _ in local.iter_events()}; for each file, each line:
    # unparseable → skipped_unparseable; known → skipped_known; else local.append_line(raw),
    # known.add(id), collect `issue.claimed` events; finally write digest to marker atomically
    # (marker.with_suffix(".tmp") + os.replace) — bounded by AC2, AC9, G3 (append-only)
```
**Why this shape**: names/signatures are fixed by spec §3 M1; `read_raw_events` counts
unparseable lines itself, so for `skipped_unparseable` either count lines inside
`import_events` directly or extend the helper privately — do not change its public return type.

### `tests/knowledge/wiki/test_ledger_shared_log.py` (CREATE)
```python
"""FEAT-694 M1 — shared ledger event log core."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.ledger.events import LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger import shared_log as sl


def _event(kind: str, subject: str, actor: str = "agent:a", **payload) -> LedgerEvent:
    return LedgerEvent(kind=kind, subject=subject, actor=actor, payload=payload)

# FILL IN: test_append_line_verbatim_and_fsync, test_is_shareable_filters_suspension_only,
# test_export_creates_then_appends_only, test_export_never_rewrites_dest,
# test_import_appends_unknown_in_src_order, test_import_marker_fast_path_and_force,
# test_import_skips_unparseable_line (caplog), test_export_skips_ids_present_in_archive,
# test_import_reads_archives_then_current (log-level only: assert local order) — spec §4 rows.
```

### FILL IN checklist
- [ ] `log.py::LedgerLog.append_line` — same atomic write path; bounded by 4096 cap
- [ ] `shared_log.py` four models — verbatim from spec §2
- [ ] `read_raw_events` / `shared_log_files` / `read_shared_event_ids` / `digest_files`
- [ ] `export_events` — append-only, archive-aware dedup; AC1/AC5/AC17
- [ ] `import_events` — marker fast path, marker written last atomically; AC2/AC9
- [ ] tests — the nine spec §4 rows above

---

## Acceptance Criteria

- [ ] `append_line` writes exact bytes + newline; >4096 bytes raises `ValueError`.
- [ ] Export is append-only, verbatim, local order, archive-aware, filters `coder_suspension` (AC1, AC5, AC17).
- [ ] Import appends only unknown events, archives first, never rewrites the local log (AC2).
- [ ] Marker fast path uses SHA-256 under the given marker path; no `ORIG_HEAD` (AC9).
- [ ] `ruff check` clean on the touched files.

## Validation Commands

- `pytest tests/knowledge/wiki/test_ledger_shared_log.py -q`
- `pytest tests/knowledge/wiki/test_ledger_log.py -q`

---

## Test Specification

See spec §4 rows tagged M1 and M1/M5 (export/import halves). Use `tmp_path` only; no git needed.

---

## Agent Instructions

Standard SDD flow (see `sdd/templates/task.md` § Agent Instructions): work in
`.claude/worktrees/feat-FEAT-694-ledger-shared-event-log`, verify the contract, implement from
the blueprint, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`, commit only
the listed files, close with `scripts/sdd/close_task.sh TASK-4405 ledger-shared-event-log verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
