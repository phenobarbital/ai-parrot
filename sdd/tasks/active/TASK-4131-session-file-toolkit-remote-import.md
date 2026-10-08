# TASK-4131: SessionFileToolkit — import a remote file into the session store

**Feature**: FEAT-639 — Session file store and Jira attachments for binary documents
**Spec**: `sdd/specs/jiratoolkit-docx-support.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4130
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, and the SSRF boundary in §1 Non-Goals: **the Jira layer never
fetches a URL**. A document living in SharePoint, OneDrive, Google Drive, S3 or GCS
is brought into the session store by this explicit tool first, and only then
attached by handle.

This is also design-research finding S4: `FileManagerToolkit` binds one backend at
construction and `download_file` targets a local destination, so "remote source →
session handle" does not exist today and has to be built here.

---

## Scope

- Implement `import_remote_file(backend, remote_path, filename=None)` on
  `SessionFileToolkit`.
- Construct a `FileManagerToolkit` per call with `manager_type=backend`, download to
  a private temporary path, then hand the bytes to the store with `origin="remote"`.
- Validate `backend` against the supported set; reject anything else before any I/O.
- Remove the temporary file whether or not the import succeeds.
- Write tests with the download mocked — no network, no real backend.

**NOT in scope**: modifying `filemanager.py` (this feature never does) · credentials
or backend configuration · the Jira side (deferred module M3).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/session_files.py` | MODIFY | Add `import_remote_file` |
| `packages/ai-parrot/tests/tools/test_session_files_remote_import.py` | CREATE | Mocked-transport tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.filemanager import FileManagerToolkit   # verified: packages/ai-parrot/src/parrot/tools/filemanager.py:724
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/filemanager.py
class FileManagerToolkit(AbstractToolkit):                           # line 724
    tool_prefix: Optional[str] = "fs"                                # line 762
    def __init__(self, manager_type: ManagerType = "fs",             # line 764
                 default_output_dir: Optional[str] = None,
                 allowed_operations: Optional[Set[str]] = None,
                 max_file_size: int = 100 * 1024 * 1024,
                 auto_create_dirs: bool = True, **manager_kwargs) -> None
    async def download_file(...)                                     # line 993
# Supported manager_type values (verified: filemanager.py:746-753):
#   "fs" | "temp" | "s3" | "gcs" | "sharepoint" | "onedrive" | "gdrive"
# Drive-relative backends (verified: filemanager.py:866):
#   _DRIVE_RELATIVE_BACKENDS = frozenset({"sharepoint", "onedrive", "gdrive"})
```

### Does NOT Exist
- ~~a "remote source → session handle" operation on `FileManagerToolkit`~~ — this task
  builds it on top of `download_file`; do not expect one to exist
- ~~`FileManagerToolkit.import_to_session`~~ — not a real method
- ~~URL fetching by handle, or an http/https `backend`~~ — there is no URL backend.
  Valid values are exactly the seven `manager_type` strings above
- ~~`FileManagerToolkit._resolve_output_path` as a containment check~~ — unsafe
  (`filemanager.py:887`); containment belongs to `SessionFileStore.resolve`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/session_files.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_session_files_remote_import.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/session_files.py#SessionFileToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The temporary download destination is created with `tempfile.mkdtemp()` and removed
  in a `finally` — it must never be inside the session root.
- `aiohttp` only if HTTP is ever needed; `requests`/`httpx` are banned repo-wide.

---

## Implementation Blueprint

### Steps (in order)
1. Add a module-level tuple of supported backends — *why*: the validation must be
   testable without constructing a `FileManagerToolkit`.
2. Validate `backend` before any I/O — *why*: an unknown backend should cost nothing
   and must not surface as a backend import error.
3. Download to a temp dir, read, then `put_bytes` — *why*: the store owns the sandbox;
   a downloaded file must not be written into the session root by another component.

### `packages/ai-parrot/src/parrot/tools/session_files.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def store_generated_file(self, filename: str, content: str)' packages/ai-parrot/src/parrot/tools/session_files.py)
# AFTER — insert below `async def store_generated_file(...)` (added by TASK-4130)
    async def import_remote_file(self, backend: str, remote_path: str,
                                 filename: Optional[str] = None) -> Dict[str, Any]:
        """Import a file from remote storage into this session, returning its handle.

        backend is one of "s3", "gcs", "sharepoint", "onedrive", "gdrive", "fs", "temp".
        Returns {"file_id", "filename", "size"}. Use the file_id to attach the file.
        """
        session_id = self._require_session()
        if backend not in SUPPORTED_BACKENDS:
            raise ValueError(
                f"Unsupported backend {backend!r}; expected one of {sorted(SUPPORTED_BACKENDS)}"
            )
        # FILL IN: tempfile.mkdtemp() OUTSIDE the session root; build
        # FileManagerToolkit(manager_type=backend) and await download_file into it;
        # read the bytes; await self.store.put_bytes(session_id, filename or
        # basename(remote_path), data, origin="remote"); remove the temp dir in a
        # finally — bounded by: nothing writes into the session root but the store
        raise NotImplementedError
```
**Why**: constructing the transport per call is deliberate — `FileManagerToolkit`
fixes its backend at construction (`filemanager.py:764`), so a cached instance could
only ever serve one backend. The temp directory must sit outside the session root so a
failed import cannot leave an unmanifested blob where `list_files` would miss it.

```python
# occurrences: 1 (verified: grep -c '    tool_prefix: str = "sf"' packages/ai-parrot/src/parrot/tools/session_files.py)
# BEFORE — add above the class, next to the module imports
SUPPORTED_BACKENDS = frozenset(
    {"fs", "temp", "s3", "gcs", "sharepoint", "onedrive", "gdrive"}
)  # verified: packages/ai-parrot/src/parrot/tools/filemanager.py:746-753
```
**Why**: the tuple mirrors `FileManagerToolkit`'s documented `manager_type` values; it
is duplicated rather than imported because `filemanager.py` exposes them as a type
annotation, not a runtime constant.

### FILL IN checklist
- [ ] `import_remote_file` body — temp dir, download, put_bytes, cleanup; bounded by
      "nothing writes into the session root but the store"

---

## Acceptance Criteria

- [ ] `sf_import_remote_file` appears in `get_tools()`
- [ ] An unsupported backend raises `ValueError` before any `FileManagerToolkit` is built
- [ ] A mocked download produces a handle that `SessionFileStore.resolve` accepts
- [ ] The imported record has `origin == "remote"`
- [ ] The temporary directory is removed on both success and failure
- [ ] No URL/HTTP fetch path exists in the diff (spec §1 Non-Goals, SSRF boundary)
- [ ] `remote_path` is validated against path-traversal (`..`, absolute paths outside the backend root) before being forwarded to `FileManagerToolkit.download_file` — issue:b2c54218dcef
- [ ] A `remote_path` containing `..` or an absolute path raises `ValueError`
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/session_files.py` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_session_files_remote_import.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_session_files_remote_import.py
import pytest
from parrot.interfaces.file.session import SessionFileStore
from parrot.tools.session_files import SessionFileToolkit


@pytest.fixture
def toolkit(tmp_path):
    return SessionFileToolkit(store=SessionFileStore(root=tmp_path))


class TestRemoteImport:
    async def test_rejects_unknown_backend(self, toolkit, bind):
        with pytest.raises(ValueError, match="Unsupported backend"):
            await toolkit.import_remote_file("http", "https://example.com/x.docx")

    async def test_import_returns_resolvable_handle(self, toolkit, bind, monkeypatch):
        """A mocked download becomes a handle the store can resolve."""
        # FILL IN: monkeypatch FileManagerToolkit.download_file to write bytes to the
        # requested destination, then assert resolve() succeeds and origin == "remote"

    async def test_temp_dir_removed_on_failure(self, toolkit, bind, monkeypatch):
        """A download that raises still cleans up."""
        # FILL IN

    @pytest.mark.parametrize("bad_path", [
        "../../../etc/passwd", "/etc/passwd", "foo/../../bar",
    ])
    async def test_rejects_path_traversal(self, toolkit, bind, bad_path):
        """remote_path with traversal or absolute paths is rejected (issue:b2c54218dcef)."""
        with pytest.raises(ValueError):
            await toolkit.import_remote_file("s3", bad_path)
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
8. `scripts/sdd/close_task.sh TASK-4131 jiratoolkit-docx-support verified`

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:
**Deviations from spec**: none | describe if any
