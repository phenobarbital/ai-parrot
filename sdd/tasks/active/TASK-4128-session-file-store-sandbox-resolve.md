# TASK-4128: SessionFileStore — manifest model, errors and the sandbox resolver

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 and §2 Overview decision (2). This task builds the **security
core** of the feature: the opaque-handle namespace and the only code allowed to
turn a handle into a path. Everything else in FEAT-639 depends on it.

The sandbox needs its own resolver because the obvious candidate is unsafe:
`FileManagerToolkit._resolve_output_path` (`filemanager.py:887`) returns any
absolute path unchanged and otherwise compares with a lexical `startswith`. Spec
§6 "Does NOT Exist" records this explicitly — do not reuse it.

Write paths (`put_bytes`, `put_path`, `list_files`, `usage_bytes`) are TASK-4129.

---

## Scope

- Implement `SessionFileRecord` (Pydantic v2) exactly as spec §2 Data Models fixes it.
- Implement `SessionFileError` with a stable `code` attribute, plus `UnknownHandle`,
  `OutsideSandbox` and `MissingBlob`.
- Implement `SessionFileStore.__init__`, `session_root()` and `resolve()`.
- `resolve()` canonicalizes with `Path.resolve()`, requires
  `is_relative_to(session_root)`, and refuses a symlinked blob.
- Write tests for resolution and every refusal path.

**NOT in scope**: `put_bytes` / `put_path` / `list_files` / `usage_bytes`
(TASK-4129) · the agent-facing toolkit (TASK-4130) · anything in `jiratoolkit.py`
(deferred module M3) · modifying `filemanager.py` (this feature never does).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/session.py` | CREATE | Record model, error types, store construction + resolution |
| `packages/ai-parrot/tests/interfaces/test_session_store_resolve.py` | CREATE | Resolution and sandbox-refusal tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import OUTPUT_DIR            # verified: packages/ai-parrot/src/parrot/conf.py:56
from pydantic import BaseModel, Field         # Pydantic v2 — house standard
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/conf.py:56-60
OUTPUT_DIR = Path(config.get("OUTPUT_DIR", fallback=BASE_DIR.joinpath("outputs")))
# absolute-ized at :57-58, created at :59-60 — it always exists at import time
```

### Does NOT Exist
- ~~`parrot.interfaces.file.session`~~ — this task creates it; nothing imports it yet
- ~~`SessionFileStore`, `SessionFileRecord`, `UnknownHandle`~~ — all new here
- ~~`FileManagerToolkit._resolve_output_path` as a containment check~~ — it exists
  (`packages/ai-parrot/src/parrot/tools/filemanager.py:887`) but **returns absolute
  paths unchanged**; it is NOT a sandbox boundary. Do not import or imitate it
- ~~`Path.is_relative_to` on Python < 3.9~~ — the workspace targets 3.11/3.12, it is available

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/session.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interfaces/test_session_store_resolve.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; filesystem calls that can block go through `asyncio.to_thread`.
- Pydantic v2 for the record model.
- `logging.getLogger(__name__)` at module level — this module is not a toolkit, so
  there is no `self.logger` from a base class.
- An `OutsideSandbox` refusal logs at WARNING with the session id and the handle,
  **never the resolved path** (spec §7).

### References in Codebase
- `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` — module style in this package
- `packages/ai-parrot/tests/interfaces/test_zammad.py` — test layout in this directory

---

## Implementation Blueprint

### Steps (in order)
1. Create `session.py` with the record model and error hierarchy — *why*: every later
   task imports these names; fixing them first stops the contract drifting.
2. Implement `session_root()` with session-id validation — *why*: a session id
   containing a separator would escape the root before `resolve()` ever runs.
3. Implement `resolve()` canonicalize-then-contain — *why*: lexical checks are the
   documented failure mode this feature exists to avoid.
4. Write the refusal tests before the happy path — *why*: AC6/AC7 are the criteria
   most likely to regress silently.

### `packages/ai-parrot/src/parrot/interfaces/file/session.py` (CREATE)
```python
"""Per-session, sandboxed file store addressed by opaque handles."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from parrot.conf import OUTPUT_DIR  # verified: packages/ai-parrot/src/parrot/conf.py:56

logger = logging.getLogger(__name__)

#: Suffixes used inside a session root.
BLOB_SUFFIX = ".bin"
MANIFEST_SUFFIX = ".json"


class SessionFileError(Exception):
    """Base for every store refusal; `code` is the stable, matchable signal."""

    code: str = "session_file_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class UnknownHandle(SessionFileError):
    """No manifest entry for this file_id in this session."""

    code = "unknown_handle"


class OutsideSandbox(SessionFileError):
    """The handle resolved outside its session root (traversal or symlink)."""

    code = "outside_sandbox"


class MissingBlob(SessionFileError):
    """The manifest entry exists but its blob does not."""

    code = "missing_file"


class SessionFileRecord(BaseModel):
    """Manifest entry for one stored session file."""

    file_id: str = Field(description="Opaque, URL-safe handle")
    session_id: str
    filename: str = Field(description="Sanitized original name, for display and Jira")
    mime_type: str = Field(description="Advisory only — never sent to Jira")
    size: int
    origin: Literal["upload", "remote", "generated"]
    created_at: datetime


class SessionFileStore:
    """Sandboxed, manifest-backed per-session file store."""

    def __init__(self, root: Optional[Path] = None) -> None:
        """Default root is ``OUTPUT_DIR / 'sessions'``."""
        self.root = Path(root) if root is not None else Path(OUTPUT_DIR) / "sessions"

    def session_root(self, session_id: str) -> Path:
        """Canonical root for *session_id*, created on demand.

        Raises ValueError when *session_id* is empty or contains a path separator.
        """
        # FILL IN: reject empty / separator-bearing / dot-only session ids, then
        # mkdir(parents=True, exist_ok=True) and return the RESOLVED path —
        # bounded by AC6 (nothing may escape this root)
        raise NotImplementedError

    async def resolve(self, session_id: str, file_id: str) -> tuple[SessionFileRecord, Path]:
        """Resolve a handle to its record and a verified-contained blob path.

        Raises UnknownHandle / OutsideSandbox / MissingBlob. Never returns a path
        it has not proven to be inside the session root.
        """
        root = self.session_root(session_id)
        # FILL IN: read <root>/<file_id><MANIFEST_SUFFIX> off the loop via
        # asyncio.to_thread; absent -> UnknownHandle. Then resolve the blob path and
        # require blob.resolve().is_relative_to(root) AND not blob.is_symlink(),
        # else log WARNING (session_id + file_id ONLY, never the path) and raise
        # OutsideSandbox. Blob absent -> MissingBlob.
        # bounded by AC6, AC7 and spec §7 ("never a path" in the log)
        raise NotImplementedError
```
**Why this shape**: the error `code` strings are the exact `AttachmentErrorCode`
literals spec §2 fixes, so TASK-4131's Jira mapping is a pass-through rather than a
translation table. `resolve()` is the ONLY place a handle becomes a path — keep it
that way; no other method may return a path. Do not change these names: TASK-4129,
TASK-4130, TASK-4132 and TASK-4135 all import them.

### FILL IN checklist
- [ ] `session.py::SessionFileStore.session_root` — id validation rules; bounded by AC6
- [ ] `session.py::SessionFileStore.resolve` — canonicalize + contain + symlink refusal; bounded by AC6, AC7
- [ ] test bodies for each refusal path; bounded by the Test Specification below

---

## Acceptance Criteria

- [ ] `from parrot.interfaces.file.session import SessionFileStore, SessionFileRecord, UnknownHandle, OutsideSandbox, MissingBlob` works
- [ ] A handle whose manifest is absent raises `UnknownHandle` with no blob access
- [ ] A traversal handle (`../…`) raises `OutsideSandbox` (spec AC6)
- [ ] An absolute path passed as a handle raises `OutsideSandbox` — the gap in
      `_resolve_output_path` is NOT reproduced (spec AC6)
- [ ] A blob that is a symlink pointing outside the root raises `OutsideSandbox` (spec AC6)
- [ ] A valid handle of session A is not resolvable under session B (spec AC7)
- [ ] An `OutsideSandbox` log line contains the session id and handle and **no** path
- [ ] `ruff check packages/ai-parrot/src/parrot/interfaces/file/session.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_session_store_resolve.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/interfaces/test_session_store_resolve.py
import pytest
from parrot.interfaces.file.session import (
    MissingBlob, OutsideSandbox, SessionFileStore, UnknownHandle,
)


@pytest.fixture
def store(tmp_path):
    return SessionFileStore(root=tmp_path)


class TestResolve:
    async def test_unknown_handle(self, store):
        with pytest.raises(UnknownHandle):
            await store.resolve("s1", "nope")

    async def test_rejects_traversal_handle(self, store):
        with pytest.raises(OutsideSandbox):
            await store.resolve("s1", "../../etc/passwd")

    async def test_rejects_absolute_path_handle(self, store):
        with pytest.raises(OutsideSandbox):
            await store.resolve("s1", "/etc/passwd")

    async def test_rejects_symlinked_blob(self, store, tmp_path):
        """A manifest whose blob symlinks outside the root is refused."""
        # FILL IN: write a manifest + symlink the blob at /etc/passwd

    async def test_not_resolvable_across_sessions(self, store):
        """A handle valid in s1 raises under s2."""
        # FILL IN: write a manifest under s1, resolve under s2

    async def test_missing_blob(self, store):
        """Manifest present, blob deleted -> MissingBlob."""
        # FILL IN
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug jiratoolkit-docx-support --feature-id FEAT-639`)
2. Read spec §2 Overview (decision 2), §3 Module 1 and §6 before writing code.
3. Verify the Codebase Contract above; fix the contract first if anything moved.
4. Set this task `in-progress` in `sdd/tasks/index/jiratoolkit-docx-support.json`.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Run the Validation Commands.
7. Commit only the two files this task lists.
8. `scripts/sdd/close_task.sh TASK-4128 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
