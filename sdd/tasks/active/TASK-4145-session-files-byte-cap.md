# TASK-4145: SessionFileToolkit — per-file byte cap on both write paths

**Feature**: FEAT-643 — Confine and bound SessionFileToolkit's remote import
**Spec**: `sdd/specs/tools-session-files-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-4144
**Assigned-to**: unassigned
**Discovered-from**: `issue:b2c54218dcef`

---

## Context

Third defect of ledger `issue:b2c54218dcef`: *"store_generated_file/import have
no size cap before put_bytes"*.

`store_generated_file` encodes the whole model-authored string and
`import_remote_file` calls `destination.read_bytes()` on whatever the transport
produced, then hands the result to `SessionFileStore.put_bytes` — which only
**warns** past 500 MB per session (`session.py:27`, `_warn_if_over_threshold`)
and never refuses. One import therefore holds the file in memory twice (the
bytes plus the atomic-write buffer). Jira caps uploads at 10 MB
(`jiratoolkit.py:392`), but only *after* the store already absorbed the file.

Spec §3 Module 3.

---

## Scope

- Add `FileTooLarge(SessionFileError)` with `code = "file_too_large"`.
- Add `max_file_bytes` to `SessionFileToolkit.__init__` (default
  `DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024`), rejecting non-positive values.
- Enforce it in `store_generated_file` (on the encoded bytes) and in
  `import_remote_file` (**`stat()` the download and check before `read_bytes()`**).
- Extend the security test module with the Module 3 cases.

**NOT in scope**: backend policy / path validation (TASK-4144) · registry wiring
(TASK-4146) · any change to `SessionFileStore`, including its 500 MB warning
threshold · a cumulative per-session quota (spec §2, deferred).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/session_files.py` | MODIFY | `FileTooLarge`, `max_file_bytes`, both enforcement points |
| `packages/ai-parrot/tests/tools/test_session_files_security.py` | MODIFY | Add `TestByteCap` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio                                                            # already imported: session_files.py:5
from pathlib import Path                                                  # already imported: session_files.py:6
from parrot.interfaces.file.session import SessionFileError, SessionFileStore  # verified: session_files.py:11
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/session_files.py — AS LEFT BY TASK-4144
class NoBoundSession(SessionFileError): code = "no_session"
class SessionFileToolkit(AbstractToolkit):
    def __init__(self, store: Optional[SessionFileStore] = None,
                 local_import_root: Optional[Path | str] = None) -> None   # extended by TASK-4144
    async def store_generated_file(self, filename: str, content: str) -> Dict[str, Any]  # line 74 pre-4144
    async def import_remote_file(self, backend: str, remote_path: str,
                                 filename: Optional[str] = None) -> Dict[str, Any]

# packages/ai-parrot/src/parrot/interfaces/file/session.py (verified 2026-10-08)
class SessionFileError(Exception):                                         # line 60
    code: str = "session_file_error"                                       # line 63
    def __init__(self, message: str) -> None                               # line 65
class SessionFileStore:
    async def put_bytes(self, session_id, filename, data, *, origin="upload") -> SessionFileRecord  # line 148
SESSION_FILES_WARN_BYTES = 500 * 1024 * 1024                               # line 27 — a WARNING, not a limit

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py (verified 2026-10-08)
DEFAULT_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024                            # line 392 — rationale for the 25 MB default
```

### Does NOT Exist
- ~~any existing size limit between the model and `put_bytes`~~ — only the store's
  500 MB *warning*, which never raises
- ~~`SessionFileStore.max_bytes` / a store-level cap~~ — not real, and out of scope:
  the cap is a **toolkit** policy
- ~~`FileTooLarge`~~ — this task creates it
- ~~`FileManagerToolkit.max_file_size` protecting this path~~ — it guards
  `create_file`/`upload_file` only (`filemanager.py:852-863`), never `download_file`
- ~~a per-session cumulative quota~~ — spec §2 defers it; do not add one

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/session_files.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_session_files_security.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/session_files.py#SessionFileToolkit.store_generated_file",
    "sym:packages/ai-parrot/src/parrot/tools/session_files.py#SessionFileToolkit.import_remote_file",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/session.py#SessionFileError"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Ordering is the point of Module 3**: in `import_remote_file` the size check
  reads `destination.stat().st_size` and must run **before** `read_bytes()`.
  A cap applied after reading the file into memory does not bound memory at all.
- The `finally: rmtree(temp_dir)` already present must still remove the temporary
  directory when the cap rejects the import.
- `FileTooLarge` subclasses `SessionFileError`, so callers that already catch the
  store's refusals keep working and the refusal is matchable by `code`.
- `stat` is blocking — call it through `asyncio.to_thread`, like every other
  filesystem call in this module.

---

## Implementation Blueprint

### Steps (in order)
1. Add `DEFAULT_MAX_FILE_BYTES` next to the backend constants — *why*: a module
   constant is assertable in tests without constructing a toolkit.
2. Add `FileTooLarge` beside `NoBoundSession` — *why*: both are this module's
   `SessionFileError` subclasses and belong together.
3. Validate `max_file_bytes` in `__init__` — *why*: a zero cap would refuse every
   file, which is a misconfiguration, not a policy.
4. Guard `store_generated_file` after encoding — *why*: the encoded length, not
   `len(content)`, is what is stored (UTF-8 multibyte).
5. Guard `import_remote_file` on `stat().st_size` before `read_bytes()` — *why*:
   see Key Constraints; this ordering is the whole value of the module.

### `packages/ai-parrot/src/parrot/tools/session_files.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '^SUPPORTED_BACKENDS = REMOTE_BACKENDS | LOCAL_BACKENDS' packages/ai-parrot/src/parrot/tools/session_files.py — AFTER TASK-4144)
# AFTER — insert below the SUPPORTED_BACKENDS definition TASK-4144 leaves behind
#: Largest single session file accepted by this toolkit, in bytes.
#: Above Jira's 10 MB default attachment limit (jiratoolkit.py:392) so a legitimate
#: document is never blocked, far below FileManagerToolkit's 100 MB.
DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
```
**Why**: 25 MB is chosen against the two real limits either side of this code —
it cannot block a Jira-legal attachment, and it cannot let a 100 MB download
through.

```python
# occurrences: 1 (verified: grep -c '    code = "no_session"' packages/ai-parrot/src/parrot/tools/session_files.py)
# AFTER — insert below the NoBoundSession class body
class FileTooLarge(SessionFileError):
    """The file exceeds the toolkit's per-file byte cap."""

    code = "file_too_large"
```
**Why**: a `SessionFileError` subclass keeps the refusal inside the store's existing
error taxonomy, so a caller catching `SessionFileError` already handles it and
`code` stays the stable, matchable signal.

```python
# occurrences: 1 (verified: grep -c '        local_import_root: Optional\[Path | str\] = None,' packages/ai-parrot/src/parrot/tools/session_files.py — AFTER TASK-4144)
# MODIFY the __init__ TASK-4144 leaves behind: add the parameter, its docstring
# lines, and the validation. Keep local_import_root handling exactly as it is.
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
...
            max_file_bytes: Largest single file this toolkit will store, in bytes.

        Raises:
            ValueError: If *local_import_root* is not an existing directory, or
                *max_file_bytes* is not positive.
...
        # FILL IN: raise ValueError when max_file_bytes <= 0; assign
        #          self.max_file_bytes — bounded by AC9
```
**Why**: a non-positive cap refuses every file, which is a wiring mistake rather
than a policy choice — failing at construction keeps it out of the request path.

```python
# occurrences: 1 (verified: grep -c '        record = await self.store.put_bytes(session_id, filename, content.encode("utf-8"), origin="generated")' packages/ai-parrot/src/parrot/tools/session_files.py)
# REPLACE that single line in store_generated_file with:
        data = content.encode("utf-8")
        self._check_size(len(data), filename)
        record = await self.store.put_bytes(session_id, filename, data, origin="generated")
```
**Why**: encode once and measure the encoded length — `len(content)` counts
characters, and a UTF-8 document can be several times that in bytes.

```python
# occurrences: 1 (verified: grep -c '            data = await asyncio.to_thread(destination.read_bytes)' packages/ai-parrot/src/parrot/tools/session_files.py)
# BEFORE — insert immediately above that line, inside the existing try:
            downloaded = await asyncio.to_thread(destination.stat)
            self._check_size(downloaded.st_size, filename or Path(remote_path).name)
```
**Why**: this is the ordering Module 3 exists for — an oversized import is refused
on a cheap `stat`, so the bytes never enter the process. The enclosing `finally`
still removes the temporary directory, so the rejected download leaves nothing behind.

```python
# occurrences: 1 (verified: grep -c '    def _require_session(self) -> str:' packages/ai-parrot/src/parrot/tools/session_files.py)
# AFTER — insert the helper below _require_session's body, above list_session_files
    def _check_size(self, size: int, filename: str) -> None:
        """Refuse *size* when it exceeds the configured per-file cap.

        Args:
            size: Byte count about to be stored.
            filename: Name used in the refusal message.

        Raises:
            FileTooLarge: If *size* exceeds ``self.max_file_bytes``.
        """
        # FILL IN: raise FileTooLarge naming size, the cap and filename — bounded
        #          by AC7/AC8; the check is `>`, so exactly max_file_bytes passes (AC
        #          "test_import_at_cap_succeeds")
```
**Why**: one helper means both write paths cannot drift apart, and the boundary
(`>` not `>=`) is stated once where a reader will find it.

### `packages/ai-parrot/tests/tools/test_session_files_security.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c '^class TestRemotePathValidation:' packages/ai-parrot/tests/tools/test_session_files_security.py — AFTER TASK-4144)
# AFTER — append below TestRemotePathValidation; extend the module's existing
# imports with FileTooLarge and DEFAULT_MAX_FILE_BYTES from parrot.tools.session_files
class TestByteCap:
    """Module 3 — neither write path may exceed the per-file cap."""

    def test_rejects_non_positive_cap(self, tmp_path):
        """AC9 — a zero or negative cap is a wiring error, caught at construction."""
        # FILL IN — bounded by AC9

    async def test_generated_file_over_cap(self, tmp_path, bind):
        """AC7 — oversized generated text is refused and nothing is stored."""
        # FILL IN: build a toolkit with a small max_file_bytes, expect FileTooLarge,
        #          then assert list_session_files() returns no files — bounded by AC7

    async def test_import_over_cap_not_read_into_memory(self, tmp_path, bind, monkeypatch):
        """AC8 — the cap is enforced on stat(), before the bytes are read."""
        # FILL IN: mock the transport to write an oversized destination; monkeypatch
        #          Path.read_bytes to fail the test if called; assert FileTooLarge,
        #          an empty store, and that the temp dir was removed — bounded by AC8

    async def test_import_at_cap_succeeds(self, tmp_path, bind, monkeypatch):
        """The boundary is inclusive: exactly max_file_bytes is stored."""
        # FILL IN — bounded by the `>` comparison in _check_size

    def test_default_cap_exceeds_jira_limit(self):
        """The default leaves Jira-legal attachments (10 MB) comfortably inside."""
        assert DEFAULT_MAX_FILE_BYTES > 10 * 1024 * 1024
```
**Why**: patching `read_bytes` to raise is the only assertion that actually proves
the *ordering*; a test that merely checks `FileTooLarge` would pass just as well
with the check placed after the read, which is the bug being fixed.

### FILL IN checklist
- [ ] `__init__` `max_file_bytes` validation; bounded by AC9
- [ ] `_check_size` body (`>` comparison, message naming size/cap/filename)
- [ ] the four `FILL IN` test bodies in `TestByteCap`

---

## Acceptance Criteria

- [ ] AC7 — `store_generated_file` over the cap raises `FileTooLarge` and
      `list_session_files()` stays empty
- [ ] AC8 — an oversized `import_remote_file` raises `FileTooLarge`, never calls
      `read_bytes` on the download, stores nothing, and still removes the temp dir
- [ ] AC9 — `SessionFileToolkit(max_file_bytes=0)` (or negative) raises `ValueError`
- [ ] A file of exactly `max_file_bytes` is accepted
- [ ] `FileTooLarge` is a `SessionFileError` with `code == "file_too_large"`
- [ ] TASK-4144's tests and `test_session_files_toolkit.py` still pass
- [ ] `ruff check` clean on both modified files

---

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/test_session_files_security.py -q`
- `pytest packages/ai-parrot/tests/tools/test_session_files_toolkit.py -q`
- `pytest packages/ai-parrot/tests/tools/test_session_files_remote_import.py -q`

---

## Test Specification

See the `TestByteCap` block above. The ordering assertion
(`test_import_over_cap_not_read_into_memory`) is the load-bearing test — without
it the cap could be enforced after the read and every other test would still pass.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`.
2. Confirm TASK-4144 is `done` in
   `sdd/tasks/index/tools-session-files-fixes.json` before starting: this task's
   anchors are the ones TASK-4144 leaves behind.
3. Read spec §3 Module 3 and §5 AC7-AC9.
4. **Verify the Codebase Contract** — re-grep every anchor; if one moved, fix this
   task file FIRST.
5. Set this task `in-progress` in the per-spec index and commit only that index file.
6. Implement from the blueprint; complete every `FILL IN`.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
8. Commit only the two files this task lists.
9. `scripts/sdd/close_task.sh TASK-4145 tools-session-files-fixes verified`

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
