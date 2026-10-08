# TASK-4144: SessionFileToolkit — remote-only backends and remote_path validation

**Feature**: FEAT-643 — Confine and bound SessionFileToolkit's remote import
**Spec**: `sdd/specs/tools-session-files-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:b2c54218dcef`

---

## Context

Ledger `issue:b2c54218dcef` (vulnerability, major), opened by the FEAT-639 code
review and still open after FEAT-639 merged.

`import_remote_file` takes **both** the backend and the path from the model, and
`SUPPORTED_BACKENDS` (`session_files.py:15`) includes `"fs"`. For `"fs"`,
`FileManagerToolkit._create_manager` builds the upstream `LocalFileManager` with
`base_path=kwargs.get("base_path", Path.cwd())` (`filemanager.py:838-848`). The
upstream sandbox blocks escapes *above* `base_path`, but `base_path` is the
server process's **current working directory** — in a deployment, the app root
with `settings/`, `env/.env` and source. So two tool calls
(`sf_import_remote_file(backend="fs", remote_path="env/.env")` then
`jira_add_attachment`) exfiltrate secrets to Jira.

Separately, TASK-4131 was amended mid-run with two acceptance criteria requiring
`remote_path` traversal validation plus a parametrised test. **Neither landed.**
Nothing rejects `..` or an absolute path before the string reaches a transport.

Spec §3 Modules 1 and 2. The byte cap (Module 3) is TASK-4145; registry wiring
(Module 4) is TASK-4146.

---

## Scope

- Split the backend set into `REMOTE_BACKENDS` / `LOCAL_BACKENDS`; drop `"temp"`
  from every set.
- Add `local_import_root` to `SessionFileToolkit.__init__`: `None` refuses `"fs"`;
  a set value must be an existing directory and binds the per-call
  `FileManagerToolkit` to it with `sandboxed=True`.
- Add `_validate_remote_path`, applied to every backend, before any transport
  work.
- Update the two existing remote-import tests that pass `backend="temp"`.
- Create the security test module with the Module 1 + Module 2 cases.

**NOT in scope**: the byte cap (TASK-4145) · registry wiring (TASK-4146) ·
`filemanager.py` (never modified by this feature or FEAT-639) ·
`SessionFileStore` · any per-session quota.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/session_files.py` | MODIFY | Backend sets, `local_import_root`, `_validate_remote_path` |
| `packages/ai-parrot/tests/tools/test_session_files_remote_import.py` | MODIFY | `backend="temp"` → `"s3"` in two tests |
| `packages/ai-parrot/tests/tools/test_session_files_security.py` | CREATE | Module 1 + Module 2 cases |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path                                                  # stdlib, already imported: session_files.py:6
from typing import Any, Dict, Optional                                    # already imported: session_files.py:9
from parrot.interfaces.file.session import SessionFileError, SessionFileStore  # verified: session_files.py:11
from parrot.tools.toolkit import AbstractToolkit                          # verified: session_files.py:12
from parrot.utils.helpers import current_context                          # verified: session_files.py:13
from parrot.tools.filemanager import FileManagerToolkit                   # verified: session_files.py:100 (function-local import — KEEP it function-local)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/session_files.py (verified 2026-10-08)
SUPPORTED_BACKENDS = frozenset({"fs", "temp", "s3", "gcs", "sharepoint", "onedrive", "gdrive"})  # line 15
class NoBoundSession(SessionFileError): code = "no_session"               # line 18
class SessionFileToolkit(AbstractToolkit):                                # line 24
    tool_prefix: str = "sf"                                              # line 27
    def __init__(self, store: Optional[SessionFileStore] = None) -> None  # line 29
    def _require_session(self) -> str                                    # line 38
    async def import_remote_file(self, backend: str, remote_path: str,
                                 filename: Optional[str] = None) -> Dict[str, Any]  # line 88

# packages/ai-parrot/src/parrot/tools/filemanager.py (verified 2026-10-08)
class FileManagerToolkit(AbstractToolkit):                                # line 724
    def __init__(self, manager_type="fs", default_output_dir=None,
                 allowed_operations=None, max_file_size=100*1024*1024,
                 auto_create_dirs=True, **manager_kwargs) -> None         # line 764
    def _create_manager(self, manager_type, **kwargs)                     # line 824
        # "fs" branch forwards base_path / sandboxed from **manager_kwargs  # line 838-848
    async def download_file(self, path, destination=None)                 # line 993

# packages/ai-parrot/src/parrot/interfaces/file/session.py (verified 2026-10-08)
class SessionFileError(Exception): code = "session_file_error"            # line 60
```

### Does NOT Exist
- ~~`SUPPORTED_BACKENDS` containing `"temp"` after this task~~ — `"temp"` is removed
  from **every** set; it is not merely moved to `LOCAL_BACKENDS`
- ~~any path validation in `import_remote_file`~~ — this task adds the first
- ~~a `FileTooLarge` error or any byte cap~~ — TASK-4145 creates those; do NOT
  add them here
- ~~`SessionFileToolkit` in any registry~~ — TASK-4146; do NOT touch
  `parrot/tools/__init__.py` or `parrot_tools/__init__.py` here
- ~~`FileManagerToolkit.set_base_path` / `.sandbox()`~~ — not real; the only way in
  is `**manager_kwargs` at construction
- ~~`os.path.realpath` containment on `remote_path`~~ — `remote_path` is a
  *storage-side* path, not a local one; never resolve it against the filesystem

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/session_files.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_session_files_remote_import.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_session_files_security.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/session_files.py#SessionFileToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/session_files.py#SessionFileToolkit.import_remote_file",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The backend check must still raise **before** `from parrot.tools.filemanager
  import FileManagerToolkit` runs — FEAT-639's
  `test_rejects_unknown_backend` asserts no transport is constructed, and it
  still has to pass.
- `_validate_remote_path` is a module-level function, not a method: it must be
  testable without a store or a bound session.
- Never resolve `remote_path` against the local filesystem — it addresses the
  *backend's* namespace (an S3 key, a Graph drive-relative path).
- `local_import_root` is validated at **construction** so a wiring typo fails at
  startup, not on the first model call.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the single `SUPPORTED_BACKENDS` with the three-constant split —
   *why*: the allowlist the model sees must be expressible without `"fs"`, and
   `SUPPORTED_BACKENDS` stays defined because the module's error message and the
   existing tests read it.
2. Add `_validate_remote_path` above the class — *why*: module-level keeps it
   unit-testable and makes clear it is a pure string check, not I/O.
3. Extend `__init__` with `local_import_root` and resolve/validate it once.
4. Rewrite the head of `import_remote_file`: allowed-set check → path validation
   → only then the transport import and construction — *why*: AC1 and AC6 both
   require the refusal to cost no I/O.
5. Pass `base_path`/`sandboxed` only on the `"fs"` branch — *why*: the remote
   managers do not accept those kwargs and would raise `TypeError`.

### `packages/ai-parrot/src/parrot/tools/session_files.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'SUPPORTED_BACKENDS = frozenset' packages/ai-parrot/src/parrot/tools/session_files.py)
# REPLACE the single-line SUPPORTED_BACKENDS definition (line 15) with:
#: Backends whose namespace is remote — always selectable by the model.
REMOTE_BACKENDS = frozenset({"s3", "gcs", "sharepoint", "onedrive", "gdrive"})

#: Local-filesystem backends — selectable ONLY when the operator configured a root.
#: ``"temp"`` is deliberately absent: ``import_remote_file`` builds a fresh
#: ``FileManagerToolkit`` per call, so a ``TempFileManager``'s private directory is
#: always empty and the backend can never serve a real import (FEAT-643 §3 M1).
LOCAL_BACKENDS = frozenset({"fs"})

#: Every backend this toolkit can ever address.
SUPPORTED_BACKENDS = REMOTE_BACKENDS | LOCAL_BACKENDS
```
**Why**: splitting the set is what makes "remote by default, local by opt-in"
expressible at all. `"temp"` disappears rather than moving to `LOCAL_BACKENDS` —
keeping dead surface only widens the attack area.

```python
# occurrences: 1 (verified: grep -c 'class NoBoundSession(SessionFileError):' packages/ai-parrot/src/parrot/tools/session_files.py)
# AFTER — insert below the NoBoundSession class body (verified: session_files.py:18-21)
def _validate_remote_path(remote_path: str) -> str:
    """Return *remote_path* normalized, or raise for an unsafe storage-side path.

    Applies to EVERY backend: a ``..`` segment is meaningless in an S3 key or a
    Graph drive-relative path, and a containment bypass in a local one.

    Args:
        remote_path: Storage-side path supplied by the model.

    Returns:
        The path with ``\\`` normalized to ``/``, a leading ``./`` dropped and
        empty segments collapsed.

    Raises:
        ValueError: If the path is empty, absolute, drive-qualified, UNC,
            contains a NUL byte, or contains a ``..`` segment.
    """
    # FILL IN: reject falsy/whitespace-only and "\x00" first — bounded by AC6
    # FILL IN: normalize "\\" -> "/" BEFORE any check, so a Windows-style
    #          traversal cannot slip past a POSIX-only test — bounded by spec §3 M2
    # FILL IN: reject absolute ("/"-leading), drive-qualified (e.g. "C:") and UNC
    #          ("//" leading) forms — bounded by AC6
    # FILL IN: split on "/", reject any segment == "..", drop "" and "." segments,
    #          rejoin with "/" and reject an empty result — bounded by AC6
    raise NotImplementedError
```
**Why**: normalization has to happen *before* the checks, not after — a check
that only knows `/` is trivially bypassed by `a\..\b` on a path that a backend
may later normalize itself. Returning the cleaned path (rather than the original)
means the transport never sees a form the validator did not actually inspect.

```python
# occurrences: 1 (verified: grep -c '    def __init__(self, store: Optional\[SessionFileStore\] = None) -> None:' packages/ai-parrot/src/parrot/tools/session_files.py)
# REPLACE the whole __init__ (verified: session_files.py:29-36) with:
    def __init__(
        self,
        store: Optional[SessionFileStore] = None,
        local_import_root: Optional[Path | str] = None,
    ) -> None:
        """Initialize the toolkit.

        Args:
            store: Session file store; defaults to the ``OUTPUT_DIR``-rooted store.
            local_import_root: Directory the ``"fs"`` backend is confined to. When
                ``None`` (the default) ``"fs"`` is refused outright, so no agent can
                read the server's working directory.

        Raises:
            ValueError: If *local_import_root* is set but is not an existing directory.
        """
        super().__init__()
        self.store = store or SessionFileStore()
        # FILL IN: when local_import_root is not None, resolve it to a Path and
        #          raise ValueError unless it is an existing directory; store it on
        #          self.local_import_root (None otherwise) — bounded by AC4
```
**Why**: validating at construction turns a deployment typo into a startup error
instead of a runtime surprise on the first model call, and `self.local_import_root`
is the single flag the backend check below reads.

```python
# occurrences: 1 (verified: grep -c '    async def import_remote_file(' packages/ai-parrot/src/parrot/tools/session_files.py)
# REPLACE lines 88-106 (signature through the `await manager.download_file(...)`
# call); everything from `data = await asyncio.to_thread(...)` onward is unchanged.
    async def import_remote_file(
        self, backend: str, remote_path: str, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Import a file from remote storage into this session, returning its handle.

        backend is one of "s3", "gcs", "sharepoint", "onedrive", "gdrive".
        remote_path is a relative path inside that backend — absolute paths and
        ".." segments are refused.
        Returns {"file_id", "filename", "size"}. Use the file_id to attach the file.
        """
        session_id = self._require_session()
        allowed = REMOTE_BACKENDS if self.local_import_root is None else SUPPORTED_BACKENDS
        if backend not in allowed:
            raise ValueError(f"Unsupported backend {backend!r}; expected one of {sorted(allowed)}")
        safe_path = _validate_remote_path(remote_path)

        from parrot.tools.filemanager import FileManagerToolkit

        temp_dir = Path(await asyncio.to_thread(tempfile.mkdtemp))
        destination = temp_dir / Path(safe_path).name
        try:
            # FILL IN: build the transport — for "fs" pass
            #          base_path=str(self.local_import_root), sandboxed=True; for every
            #          other backend pass manager_type only, because the remote managers
            #          reject those kwargs — bounded by AC3/AC5
            await manager.download_file(safe_path, str(destination))
```
**Why**: the allowed set is computed per call from `self.local_import_root`, so the
default instance literally cannot name `"fs"` and the `ValueError` message never
advertises it. `safe_path` — not `remote_path` — is what reaches both the transport
and the fallback filename, so the unvalidated string is used nowhere.

### `packages/ai-parrot/tests/tools/test_session_files_remote_import.py` (MODIFY)

```python
# occurrences: 2 (verified: grep -c 'import_remote_file("temp", "reports/brief.docx")' packages/ai-parrot/tests/tools/test_session_files_remote_import.py)
# Both occurrences change the same way — "temp" is no longer a backend:
        result = await toolkit.import_remote_file("s3", "reports/brief.docx")
...
            await toolkit.import_remote_file("s3", "reports/brief.docx")
```
**Why**: FEAT-639's tests chose `"temp"` precisely because it needed no credentials;
`"s3"` is equally credential-free here because the transport is mocked at the
`FileManagerToolkit` boundary in both tests.

### `packages/ai-parrot/tests/tools/test_session_files_security.py` (CREATE)

```python
"""Backend-policy and path-validation guards for SessionFileToolkit (FEAT-643)."""

import importlib
from pathlib import Path

import pytest

from parrot.interfaces.file.session import SessionFileStore
from parrot.tools.session_files import SessionFileToolkit, _validate_remote_path
from parrot.utils.helpers import RequestContext, _current_ctx


@pytest.fixture
def bind():
    """Bind a RequestContext for the duration of a test."""

    def _bind(session_id):
        _current_ctx.set(RequestContext(session_id=session_id))

    yield _bind
    _current_ctx.set(None)


@pytest.fixture
def exploding_transport(monkeypatch):
    """Patch FileManagerToolkit so constructing one fails the test."""

    def _fail(*args, **kwargs):
        raise AssertionError("FileManagerToolkit must not be constructed")

    monkeypatch.setattr(importlib.import_module("parrot.tools.filemanager"), "FileManagerToolkit", _fail)


class TestBackendPolicy:
    """Module 1 — remote by default, local only by operator opt-in."""

    async def test_fs_refused_by_default(self, tmp_path, bind, exploding_transport):
        """AC1 — a default toolkit refuses "fs" without building a transport."""
        # FILL IN: construct SessionFileToolkit(store=SessionFileStore(root=tmp_path)),
        #          bind a session, assert ValueError mentioning "Unsupported backend"
        #          and that "fs" is absent from the message — bounded by AC1

    @pytest.mark.parametrize("root", [None, "configured"])
    async def test_temp_is_never_supported(self, tmp_path, bind, exploding_transport, root):
        """AC2 — "temp" is in no backend set, under either configuration."""
        # FILL IN — bounded by AC2

    async def test_local_root_binds_base_path(self, tmp_path, bind, monkeypatch):
        """AC3 — with a root configured, "fs" builds a transport bound to it."""
        # FILL IN: mock FileManagerToolkit to capture kwargs and write the
        #          destination; assert base_path == str(root) and sandboxed is True
        #          — bounded by AC3

    def test_local_root_must_be_a_directory(self, tmp_path):
        """AC4 — a missing or non-directory root fails at construction."""
        # FILL IN — bounded by AC4

    async def test_remote_backend_still_works(self, tmp_path, bind, monkeypatch):
        """AC5 — every remote backend imports unchanged with a valid path."""
        # FILL IN — bounded by AC5


class TestRemotePathValidation:
    """Module 2 — the path check runs for every backend, before any I/O."""

    @pytest.mark.parametrize(
        "bad_path",
        ["", "   ", "a\x00b", "/etc/passwd", "C:\\secrets.txt", "\\\\host\\share\\x",
         "../../../etc/passwd", "foo/../../bar", "foo\\..\\bar", ".."],
    )
    def test_rejects_bad_remote_path(self, bad_path):
        """AC6 — the pure validator refuses every unsafe form."""
        # FILL IN: assert pytest.raises(ValueError) — bounded by AC6, spec §3 M2 table

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("./a/b.docx", "a/b.docx"), ("a//b.docx", "a/b.docx"), ("a\\b.docx", "a/b.docx")],
    )
    def test_accepts_normalized_relative_path(self, raw, expected):
        """A safe path comes back normalized to forward slashes."""
        assert _validate_remote_path(raw) == expected

    async def test_bad_path_builds_no_transport(self, tmp_path, bind, exploding_transport):
        """AC6 — the refusal happens before the transport is imported."""
        # FILL IN — bounded by AC6
```
**Why**: `exploding_transport` is the only way to assert "no I/O happened" without
reaching for a filesystem assertion — if the code constructs a transport at all,
the test fails loudly rather than silently passing on a mocked download.

### FILL IN checklist
- [ ] `_validate_remote_path` body — normalize, then reject; bounded by AC6
- [ ] `__init__` `local_import_root` resolution + directory check; bounded by AC4
- [ ] `import_remote_file` transport construction branch; bounded by AC3/AC5
- [ ] every test body marked `FILL IN` above

---

## Acceptance Criteria

- [ ] AC1 — `import_remote_file(backend="fs", ...)` on a default-constructed toolkit
      raises `ValueError` and constructs no `FileManagerToolkit`
- [ ] AC2 — `backend="temp"` raises `ValueError` under every configuration
- [ ] AC3 — with `local_import_root=<dir>`, `"fs"` is accepted and the transport is
      constructed with `base_path=<dir>` and `sandboxed=True`
- [ ] AC4 — `SessionFileToolkit(local_import_root=<missing or non-dir>)` raises
      `ValueError` at construction
- [ ] AC5 — every remote backend still imports unchanged with a valid relative path
- [ ] AC6 — empty, absolute, drive-qualified, UNC, NUL-bearing or `..`-bearing
      `remote_path` raises `ValueError` before any transport is constructed
- [ ] The pre-existing `test_session_files_remote_import.py` and
      `test_session_files_toolkit.py` modules pass
- [ ] `ruff check` clean on both modified source/test files

---

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/test_session_files_security.py -q`
- `pytest packages/ai-parrot/tests/tools/test_session_files_remote_import.py -q`
- `pytest packages/ai-parrot/tests/tools/test_session_files_toolkit.py -q`

---

## Test Specification

See the CREATE block above — `TestBackendPolicy` (AC1-AC5) and
`TestRemotePathValidation` (AC6). No network and no real backend: the transport
is mocked at the `FileManagerToolkit` boundary exactly as FEAT-639's tests do.

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug tools-session-files-fixes --feature-id FEAT-643`).
2. Read spec §3 Modules 1-2 and §5 AC1-AC6 before writing code.
3. **Verify the Codebase Contract** — re-grep every anchor; if one moved, fix this
   task file FIRST, then implement.
4. Set this task `in-progress` in
   `sdd/tasks/index/tools-session-files-fixes.json` and commit only that index file.
5. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature.
6. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
7. Commit only the three files this task lists (never `git add .` / `-A`).
8. `scripts/sdd/close_task.sh TASK-4144 tools-session-files-fixes verified`

---

## Completion Note

**Completed by**: Claude Opus 5 (/sdd-fix lane, session 7222f028)
**Date**: 2026-10-08
**Notes**: Implemented as blueprinted. `_validate_remote_path` also rejects a
path that normalizes to nothing (`"./"`), which the blueprint's "reject an empty
result" clause implied but the AC table did not list. The transport now receives
the *normalized* path, so `test_transport_receives_the_normalized_path` was added
beyond the listed cases. The two FEAT-639 tests that used `backend="temp"` moved
to `"s3"`; both still mock the transport, so neither needs credentials.
38 tests pass (`test_session_files_security.py` +
`test_session_files_remote_import.py` + `test_session_files_toolkit.py`);
`ruff check` clean.
**Deviations from spec**: none
