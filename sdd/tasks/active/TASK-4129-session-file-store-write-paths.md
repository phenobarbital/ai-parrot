# TASK-4129: SessionFileStore — atomic writes, listing and usage reporting

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4128
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1, second half. TASK-4128 built the handle namespace and the
resolver; this task makes files actually land in the sandbox.

Two spec decisions drive the shape. **Writes are atomic** (temp file + rename for
both blob and manifest) so a crash mid-write never leaves a resolvable handle
pointing at a truncated file — spec §7. And **the aggregate quota only reports**:
crossing `SESSION_FILES_WARN_BYTES` logs a WARNING and stores the file anyway
(spec §8 Q4, AC16). Nothing here may reject an upload for an aggregate total.

---

## Scope

- Implement `put_bytes()`, `put_path()`, `list_files()` and `usage_bytes()` on
  `SessionFileStore`.
- Generate opaque handles with >= 128 bits of entropy (`secrets.token_urlsafe`).
- Sanitize the incoming filename to a basename with control characters stripped;
  derive the on-disk blob name from the handle, never from the input.
- Record advisory `mime_type` via `mimetypes.guess_type`.
- Log a WARNING when a session total crosses `SESSION_FILES_WARN_BYTES`, then store.
- Write tests for atomicity, sanitization, duplicate names and the warn threshold.

**NOT in scope**: the resolver (TASK-4128, already done) · the agent-facing toolkit
(TASK-4130) · any caller of the store (TASK-4132, TASK-4135).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/session.py` | MODIFY | Add the four write/report methods |
| `packages/ai-parrot/tests/interfaces/test_session_store_writes.py` | CREATE | Write-path tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import OUTPUT_DIR            # verified: packages/ai-parrot/src/parrot/conf.py:56
# created by TASK-4128 in this same file — already imported at module top:
#   SessionFileRecord, SessionFileError, BLOB_SUFFIX, MANIFEST_SUFFIX
import secrets, mimetypes, os, tempfile       # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/file/session.py  (created by TASK-4128)
class SessionFileRecord(BaseModel):
    file_id: str; session_id: str; filename: str
    mime_type: str; size: int; origin: Literal["upload","remote","generated"]
    created_at: datetime

class SessionFileStore:
    def __init__(self, root: Optional[Path] = None) -> None
    def session_root(self, session_id: str) -> Path
    async def resolve(self, session_id: str, file_id: str) -> tuple[SessionFileRecord, Path]
```

### Does NOT Exist
- ~~`SessionFileStore.delete` / `.purge` / any TTL sweeper~~ — files persist, cleanup is
  manual by decision (spec §1 Non-Goals). Do NOT add one
- ~~A rejecting quota~~ — `SESSION_FILES_WARN_BYTES` only warns (spec AC16). There is no
  `quota_exceeded` error code in this feature
- ~~`parrot.conf.SESSION_FILES_DIR` / `SESSION_FILES_WARN_BYTES`~~ — not in `conf.py` today;
  read them with the same `config.get` pattern `conf.py` uses, or default in this module

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/session.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_session_store_writes.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/file/session.py#SessionFileStore",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/session.py#SessionFileRecord"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Blocking filesystem work goes through `asyncio.to_thread`.
- Write blob first, then manifest — both temp-file + `os.replace`. A handle only
  becomes resolvable once its manifest lands, so a crash yields no half-file.
- On any write failure, remove the partial temp file and re-raise.

### References in Codebase
- `packages/ai-parrot/src/parrot/conf.py:56-60` — the `config.get` + default pattern

---

## Implementation Blueprint

### Steps (in order)
1. Add the handle generator and filename sanitizer as module-level helpers — *why*:
   both are pure and need their own tests independent of the filesystem.
2. Implement `put_bytes` with temp-file + `os.replace` for blob then manifest —
   *why*: ordering is what makes a partial write unresolvable rather than corrupt.
3. Implement `put_path` on top of `put_bytes` — *why*: one write path means one
   place where sanitization and atomicity can go wrong.
4. Implement `list_files` / `usage_bytes` by scanning manifests — *why*: the manifest
   is the source of truth; never infer state from blob names.
5. Add the warn-threshold check after a successful store — *why*: AC16 requires the
   file to be stored even when the threshold is crossed.

### `packages/ai-parrot/src/parrot/interfaces/file/session.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'MANIFEST_SUFFIX = ".json"' packages/ai-parrot/src/parrot/interfaces/file/session.py)
# AFTER — insert below `MANIFEST_SUFFIX = ".json"` (verified: session.py, module constants from TASK-4128)
#: Per-session total above which a WARNING is logged. Reporting only — never rejects.
SESSION_FILES_WARN_BYTES = 500 * 1024 * 1024


def _new_handle() -> str:
    """Return an opaque, URL-safe handle with >= 128 bits of entropy."""
    return secrets.token_urlsafe(24)


def _sanitize_filename(name: str) -> str:
    """Reduce *name* to a safe basename for display and for Jira."""
    # FILL IN: basename only, strip control chars, collapse whitespace, cap length,
    # fall back to "file" when nothing survives — bounded by AC: a filename of
    # "../../etc/passwd" must store as "passwd"
    raise NotImplementedError
```
**Why**: the handle is the blob name, so entropy here *is* the unguessability of the
sandbox. `_sanitize_filename` never influences the path — it is display metadata only.

```python
# occurrences: 1 (verified: grep -c '    async def resolve(self, session_id: str, file_id: str)' packages/ai-parrot/src/parrot/interfaces/file/session.py)
# AFTER — append these methods to `SessionFileStore`, below `async def resolve(...)`
    async def put_bytes(self, session_id: str, filename: str, data: bytes, *,
                        origin: str = "upload") -> SessionFileRecord:
        """Store *data* under a fresh handle; returns its manifest record.

        Writes blob then manifest, each via a temp file + atomic rename, so a
        partial write never yields a resolvable handle. Raises OSError on a full
        disk, after removing the partial file.
        """
        root = self.session_root(session_id)
        file_id = _new_handle()
        # FILL IN: build the record (mimetypes.guess_type on the sanitized name,
        # size=len(data), created_at=datetime.now(timezone.utc)); write blob then
        # manifest via tempfile + os.replace inside asyncio.to_thread; on failure
        # unlink the temp file and re-raise — bounded by AC: a failed write leaves
        # no resolvable handle
        # FILL IN: after success, call self._warn_if_over_threshold(session_id)
        raise NotImplementedError

    async def put_path(self, session_id: str, source: Path, *,
                       filename: Optional[str] = None,
                       origin: str = "generated") -> SessionFileRecord:
        """Copy *source* into the session root under a fresh handle."""
        # FILL IN: read source off the loop, delegate to put_bytes with
        # filename or source.name — bounded by: one write path only
        raise NotImplementedError

    async def list_files(self, session_id: str) -> list[SessionFileRecord]:
        """Every record in the session, newest first."""
        # FILL IN: scan *MANIFEST_SUFFIX in the session root, parse with
        # SessionFileRecord.model_validate_json, skip unparseable files with a
        # WARNING, sort by created_at descending
        raise NotImplementedError

    async def usage_bytes(self, session_id: str) -> int:
        """Total bytes stored for the session.

        Reporting only: crossing SESSION_FILES_WARN_BYTES logs a WARNING and the
        file is stored anyway. No upload is ever rejected for an aggregate quota.
        """
        # FILL IN: sum record.size over list_files
        raise NotImplementedError
```
**Why**: `put_path` delegating to `put_bytes` keeps sanitization and atomicity in one
place. `list_files` reads manifests, never blob names, so an orphan blob is invisible
rather than half-trusted. Do not add a delete/TTL method — persistence is a decision.

### FILL IN checklist
- [ ] `_sanitize_filename` — rules; bounded by "../../etc/passwd" -> "passwd"
- [ ] `put_bytes` — atomic ordering + failure cleanup; bounded by AC "no resolvable partial"
- [ ] `put_path`, `list_files`, `usage_bytes`; bounded by the Test Specification
- [ ] threshold WARNING helper; bounded by spec AC16 (warn, then store)

---

## Acceptance Criteria

- [ ] `put_bytes` creates both a blob and a manifest; the record round-trips through `resolve`
- [ ] A filename of `../../etc/passwd` stores as a basename; the blob name comes from the handle
- [ ] The same filename stored twice yields two distinct handles and two blobs
- [ ] A simulated write failure leaves no resolvable handle and no stray blob
- [ ] `list_files` returns newest-first and ignores an unparseable manifest
- [ ] Crossing `SESSION_FILES_WARN_BYTES` logs a WARNING **and still stores the file** (spec AC16)
- [ ] A freshly constructed `SessionFileStore` over the same root resolves an existing
      handle — the restart / cross-worker proxy (spec AC12)
- [ ] `ruff check packages/ai-parrot/src/parrot/interfaces/file/session.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_session_store_writes.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/interfaces/test_session_store_writes.py
import pytest
from parrot.interfaces.file.session import SessionFileStore


@pytest.fixture
def store(tmp_path):
    return SessionFileStore(root=tmp_path)


class TestWrites:
    async def test_put_bytes_creates_blob_and_manifest(self, store):
        rec = await store.put_bytes("s1", "report.docx", b"PK\x03\x04")
        found, path = await store.resolve("s1", rec.file_id)
        assert found.filename == "report.docx" and path.read_bytes() == b"PK\x03\x04"

    async def test_filename_is_sanitized(self, store):
        rec = await store.put_bytes("s1", "../../etc/passwd", b"x")
        assert "/" not in rec.filename

    async def test_duplicate_filenames_get_distinct_handles(self, store):
        """Same name twice -> two handles, two blobs."""
        # FILL IN

    async def test_partial_write_leaves_no_resolvable_handle(self, store, monkeypatch):
        """A failure during the manifest write must not leave a usable handle."""
        # FILL IN: monkeypatch os.replace to raise on the manifest rename

    async def test_store_survives_restart(self, store, tmp_path):
        """A new store over the same root resolves an existing handle (spec AC12)."""
        # FILL IN

    async def test_warn_threshold_logs_and_still_stores(self, store, caplog):
        """Spec AC16 — warn, never reject."""
        # FILL IN: monkeypatch SESSION_FILES_WARN_BYTES low, assert WARNING + record
```

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug jiratoolkit-docx-support --feature-id FEAT-639`)
2. Read the spec sections named in Context before writing code.
3. **Verify the Codebase Contract** — confirm every import and signature still exists;
   if anything moved, fix the contract in this file FIRST, then implement.
4. Check every `Depends-on` task is `done` in `sdd/tasks/index/jiratoolkit-docx-support.json`,
   then set this task `in-progress` and commit only that index file.
5. Implement from the blueprint; complete every `# FILL IN:`; never change a fixed signature.
6. Run the Validation Commands.
7. Commit only the files this task lists (never `git add .` / `-A`).
8. `scripts/sdd/close_task.sh TASK-4129 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
