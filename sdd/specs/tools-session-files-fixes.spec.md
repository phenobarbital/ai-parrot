---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools]
tags: [security, session-files, sandbox, toolkit, ledger-fix]
---

# Feature Specification: Confine and bound SessionFileToolkit's remote import

**Feature ID**: FEAT-643
**Date**: 2026-10-08
**Author**: Jesus
**Status**: approved
**Target version**: 1.2.0

**Discovered from**: `issue:b2c54218dcef` (vulnerability, major) — opened against
`spec:FEAT-639` by the FEAT-639 code review and left open when FEAT-639 merged.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-639 (merged, PR #1606) shipped `SessionFileToolkit`
(`packages/ai-parrot/src/parrot/tools/session_files.py`). Its
`import_remote_file(backend, remote_path, filename=None)` tool is LLM-callable and
takes **both** the backend and the path from the model. Three defects follow.

**1. The `fs` backend turns an attachment tool into a local-file reader.**
`SUPPORTED_BACKENDS` (`session_files.py:15`) includes `"fs"` and `"temp"`.
For `"fs"`, `FileManagerToolkit._create_manager` builds the upstream
`LocalFileManager` with `base_path=kwargs.get("base_path", Path.cwd())`
(`filemanager.py:838-848`). The upstream sandbox check
(`navigator/utils/file/local.py:74-104`) does block escapes *above* `base_path` —
but `base_path` is **the server process's current working directory**. In a
deployment that is the application root: `settings/`, `env/.env`, source,
credentials. So a prompt-injected or merely over-helpful model can call

```
sf_import_remote_file(backend="fs", remote_path="env/.env")
```

and then `jira_add_attachment(file_ids=[...])` — exfiltration to an external
system, in two tool calls, with no operator opt-in anywhere. This directly
contradicts FEAT-639 §1 Non-Goals, whose whole point was that the Jira layer
never reaches outside the session sandbox.

The `"temp"` backend is not an exfiltration path (its `TempFileManager` is
sandboxed to a dedicated directory created per instance, and
`import_remote_file` builds a *fresh* `FileManagerToolkit` per call, so that
directory is always empty) — but for exactly that reason it can never serve a
real import either. It is dead surface that only widens the attack area.

**2. `remote_path` is forwarded unvalidated.** TASK-4131 was amended during the
FEAT-639 run with two acceptance criteria requiring traversal validation and a
parametrised test; the implementation landed **without either**. Nothing in
`import_remote_file` rejects `..` segments or absolute paths before handing the
string to a transport. Containment currently depends entirely on whichever
backend happens to be selected — and the S3, GCS and Graph managers have no such
notion.

**3. Nothing caps the bytes.** `store_generated_file` encodes the whole model-authored
string and `import_remote_file` does `destination.read_bytes()` on whatever the
transport produced, then hands it to `SessionFileStore.put_bytes` — which only
*warns* past 500 MB per session (`session.py:27`, `_warn_if_over_threshold`),
never refuses. A single import holds the entire file in memory twice (bytes +
atomic write buffer). The Jira side caps uploads at 10 MB
(`jiratoolkit.py:392`), but that is after the store already absorbed the file.

**4. The toolkit is unreachable.** `SessionFileToolkit` is never instantiated or
registered anywhere outside its own module and tests — it is absent from
`parrot_tools.TOOL_REGISTRY` and from `parrot.tools._LAZY_CORE_TOOLS`. Meanwhile
`jiratoolkit.py:465` and `:591` tell the model its handles come "from
`sf_list_session_files`", a tool no agent can currently be given. FEAT-639's
delivered value is inaccessible until this is wired.

### Business Value

- Removes a credential-exfiltration path from an agent-callable tool.
- Makes FEAT-639's session-file feature actually usable (item 4).
- Bounds memory per import, so one oversized file cannot take out a worker.

### Success Criteria

- No default configuration of `SessionFileToolkit` can read a file outside a
  remote backend's own namespace.
- A `remote_path` that is absolute or contains a `..` segment is refused before
  any transport is constructed.
- A file over the configured cap is refused before it is stored.
- `session_files` resolves through `TOOL_REGISTRY`, so an agent can declare it.

---

## 2. Non-Goals

- **No change to `filemanager.py`.** FEAT-639 never modified it and neither does
  this feature; the confinement is applied at construction time, from the caller.
- **No change to `SessionFileStore`.** The store's sandbox and its 500 MB
  reporting threshold are correct as designed; the cap added here is a *toolkit*
  policy, enforced before `put_bytes` is ever reached.
- **No per-session quota.** Only a per-file cap is in scope. A cumulative quota
  would belong to the store and is deliberately deferred.
- **No URL/HTTP backend.** The SSRF boundary from FEAT-639 §1 stands.
- **No agent definition changes.** Registering the toolkit makes it *declarable*;
  which agents declare it stays an operator decision.

---

## 3. Design

### Module 1 — Backend policy: remote by default, local only by opt-in

`import_remote_file`'s backend set is split in two, and the LLM-facing default
admits only backends whose namespace is remote:

```python
REMOTE_BACKENDS = frozenset({"s3", "gcs", "sharepoint", "onedrive", "gdrive"})
LOCAL_BACKENDS = frozenset({"fs"})
SUPPORTED_BACKENDS = REMOTE_BACKENDS | LOCAL_BACKENDS
```

`"temp"` is removed from every set — it is dead surface (see §1). An agent asking
for it gets the same `ValueError` as any other unknown backend.

`SessionFileToolkit.__init__` gains `local_import_root: Optional[Path | str] = None`:

- **`None` (default)** — `"fs"` is refused with a `ValueError` naming only the
  remote backends. This is the shape every existing caller gets.
- **set** — the path is resolved once at construction and must be an existing
  directory (`ValueError` otherwise, so a typo fails at wiring time, not at the
  first model call). `"fs"` is then accepted, and the per-call
  `FileManagerToolkit` is built as
  `FileManagerToolkit(manager_type="fs", base_path=<root>, sandboxed=True)` —
  binding the upstream sandbox to the operator's directory instead of to
  `Path.cwd()`.

The refusal is a `ValueError` raised **before** `parrot.tools.filemanager` is
imported, so an unsupported backend still costs nothing (FEAT-639 AC, preserved).

### Module 2 — `remote_path` validation

A module-level `_validate_remote_path(remote_path: str) -> str` runs after the
backend check and before any transport work. It refuses:

| Input | Reason |
|---|---|
| `""` / whitespace only | nothing to fetch |
| contains `\x00` | NUL injection into a path |
| `/etc/passwd`, `C:\x`, `\\\\host\\share` | absolute / drive / UNC |
| `../x`, `a/../../b`, `a\..\b` | a `..` segment after `\` → `/` normalization |

Separators are normalized (`\` → `/`) before splitting so a Windows-style
traversal cannot slip past a POSIX-only check — the same normalization
`_sanitize_filename` already applies (`session.py:37`). The function returns the
cleaned, forward-slash path that is handed to the transport, with any leading
`./` and empty segments collapsed.

This applies to **every** backend, not only `fs`: a `..` in an S3 key or a Graph
drive-relative path is meaningless at best and a containment bypass at worst.

### Module 3 — Per-file byte cap

`SessionFileToolkit.__init__` gains `max_file_bytes: int = DEFAULT_MAX_FILE_BYTES`
with `DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024` (25 MB) — comfortably above
Jira's 10 MB default attachment limit (`jiratoolkit.py:392`) so a legitimate
document is never blocked, and far below `FileManagerToolkit`'s 100 MB.
A non-positive value raises `ValueError` at construction.

Enforcement, in both write paths, raises `FileTooLarge` (a new
`SessionFileError` subclass, `code = "file_too_large"`, so the refusal is
matchable the way every other store refusal is):

- `store_generated_file` — encode once, check `len(data)`, then store.
- `import_remote_file` — **`stat()` the downloaded file and check its size
  before `read_bytes()`**. This is the point of the ordering: an oversized import
  is refused without ever holding the file in memory. The temporary directory is
  still removed in the existing `finally`.

### Module 4 — Reachability

- `parrot_tools.TOOL_REGISTRY` gains
  `"session_files": "parrot.tools.session_files.SessionFileToolkit"`, next to the
  other core-package entries (`file_manager_toolkit`, `obsidian`) that already
  point back into `parrot.tools`.
- `parrot.tools.__init__` gains `SessionFileToolkit` in `__all__` and
  `_LAZY_CORE_TOOLS["SessionFileToolkit"] = ".session_files"`, so
  `from parrot.tools import SessionFileToolkit` works without importing the
  module at startup.

### Interaction

```
model → sf_import_remote_file(backend, remote_path)
          │
          ├─ backend ∉ allowed set ............... ValueError   (no import, no I/O)
          ├─ _validate_remote_path(remote_path) ... ValueError   (no transport built)
          │
          ├─ FileManagerToolkit(manager_type=backend[, base_path=local_import_root])
          │     └─ download_file → private tempdir (outside the session root)
          │
          ├─ stat(dest).st_size > max_file_bytes .. FileTooLarge (never read)
          └─ read_bytes → store.put_bytes(origin="remote")
                                                   finally: rmtree(tempdir)
```

---

## 4. Impact

| File | Action | Why |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/session_files.py` | MODIFY | Modules 1-3 |
| `packages/ai-parrot/src/parrot/tools/__init__.py` | MODIFY | Module 4 lazy export |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Module 4 registry entry |
| `packages/ai-parrot/tests/tools/test_session_files_remote_import.py` | MODIFY | existing tests use `backend="temp"`, which this feature removes |
| `packages/ai-parrot/tests/tools/test_session_files_security.py` | CREATE | backend policy, traversal, cap |
| `packages/ai-parrot/tests/tools/test_session_files_registry.py` | CREATE | Module 4 reachability |

### Backward compatibility

`"fs"` and `"temp"` stop working for every existing caller of
`import_remote_file`. Per the repo's hard-cut policy there are no external
consumers and no deprecation shim: the two in-repo tests that pass
`backend="temp"` are updated to `"s3"` in the same change, and no production
code calls `import_remote_file` at all today (the toolkit is unregistered —
that is defect 4).

---

## 5. Acceptance Criteria

- **AC1** `import_remote_file(backend="fs", ...)` on a default-constructed toolkit
  raises `ValueError` and constructs no `FileManagerToolkit`.
- **AC2** `import_remote_file(backend="temp", ...)` raises `ValueError` on every
  configuration — `"temp"` is in no backend set.
- **AC3** With `local_import_root=<dir>`, `"fs"` is accepted and the
  `FileManagerToolkit` is constructed with `base_path=<dir>` and `sandboxed=True`.
- **AC4** `SessionFileToolkit(local_import_root=<missing or non-dir path>)` raises
  `ValueError` at construction.
- **AC5** Every remote backend still works unchanged with a valid relative path.
- **AC6** `remote_path` that is empty, absolute, drive-qualified, UNC, NUL-bearing,
  or contains a `..` segment (`/` or `\` separated) raises `ValueError` before any
  transport is constructed.
- **AC7** `store_generated_file` with content over `max_file_bytes` raises
  `FileTooLarge` and stores nothing (`list_session_files` stays empty).
- **AC8** `import_remote_file` of an oversized file raises `FileTooLarge`, never
  calls `read_bytes` on the download, stores nothing, and still removes the
  temporary directory.
- **AC9** `SessionFileToolkit(max_file_bytes=0)` (or negative) raises `ValueError`.
- **AC10** `parrot_tools.TOOL_REGISTRY["session_files"]` resolves by import to
  `SessionFileToolkit`, and `from parrot.tools import SessionFileToolkit` works.
- **AC11** `ruff check` clean on every modified file.
- **AC12** The pre-existing remote-import and toolkit test modules still pass.

---

## 6. Test Plan

| Test | Module | Shape |
|---|---|---|
| `test_fs_refused_by_default` | M1 | transport patched to explode if constructed |
| `test_temp_is_never_supported` | M1 | parametrised over both configurations |
| `test_local_root_binds_base_path` | M1 | mock captures `base_path` / `sandboxed` kwargs |
| `test_local_root_must_be_a_directory` | M1 | construction-time `ValueError` |
| `test_rejects_bad_remote_path` | M2 | parametrised over the §3 table |
| `test_accepts_normalized_relative_path` | M2 | `./a/b.docx` → `a/b.docx` reaches the transport |
| `test_generated_file_over_cap` | M3 | `FileTooLarge`; store stays empty |
| `test_import_over_cap_not_read_into_memory` | M3 | `read_bytes` patched to fail the test if called |
| `test_import_at_cap_succeeds` | M3 | boundary: exactly `max_file_bytes` is allowed |
| `test_registry_resolves` | M4 | import by dotted path from `TOOL_REGISTRY` |

No network, no real backend: the transport is mocked at the
`FileManagerToolkit` boundary, as FEAT-639's tests already do.

---

## 7. Codebase Contract

### Verified (2026-10-08, `origin/dev` @ 78f646e42)

```python
# packages/ai-parrot/src/parrot/tools/session_files.py
SUPPORTED_BACKENDS = frozenset({...})                                   # line 15
class SessionFileToolkit(AbstractToolkit):                              # line 24
    tool_prefix: str = "sf"                                             # line 27
    def __init__(self, store: Optional[SessionFileStore] = None)        # line 29
    def _require_session(self) -> str                                   # line 38
    async def store_generated_file(self, filename, content)             # line 74
    async def import_remote_file(self, backend, remote_path, filename)  # line 88
class NoBoundSession(SessionFileError)                                  # line 18

# packages/ai-parrot/src/parrot/interfaces/file/session.py
class SessionFileError(Exception):  code = "session_file_error"         # line 60
class SessionFileStore:                                                 # line 100
    async def put_bytes(self, session_id, filename, data, *, origin)    # line 148
SESSION_FILES_WARN_BYTES = 500 * 1024 * 1024                            # line 27

# packages/ai-parrot/src/parrot/tools/filemanager.py
class FileManagerToolkit(AbstractToolkit):                              # line 724
    def __init__(self, manager_type="fs", default_output_dir=None,
                 allowed_operations=None, max_file_size=100*1024*1024,
                 auto_create_dirs=True, **manager_kwargs)               # line 764
    def _create_manager(self, manager_type, **kwargs)                   # line 824
        # "fs" → base_path=kwargs.get("base_path", Path.cwd()),
        #        sandboxed=kwargs.get("sandboxed", True)                # line 841
    async def download_file(self, path, destination=None)               # line 993

# packages/ai-parrot-tools/src/parrot_tools/__init__.py
TOOL_REGISTRY: dict[str, str] = {...}                                   # line 13
    "file_manager_toolkit": "parrot.tools.filemanager.FileManagerToolkit"
    "obsidian": "parrot.tools.obsidian.ObsidianToolkit"

# packages/ai-parrot/src/parrot/tools/__init__.py
_LAZY_CORE_TOOLS = {...}                                                # line 266

# .venv/.../navigator/utils/file/local.py
class LocalFileManager:
    def _resolve_path(self, path)   # strips leading "/", joins base_path, sandbox check
```

### Does NOT exist

- ~~a byte cap anywhere between the model and `put_bytes`~~ — only the store's
  500 MB *warning*, which never refuses
- ~~path validation in `import_remote_file`~~ — TASK-4131's amended ACs were not implemented
- ~~`SessionFileToolkit` in any registry~~ — defect 4
- ~~`FileTooLarge`~~ — this feature creates it
- ~~a `base_path` argument reaching `LocalFileManager` from `import_remote_file`~~ —
  nothing passes `**manager_kwargs` today

---

## 8. Resolution

Closes `issue:b2c54218dcef` (all four items of its body: `fs`/`temp` confinement,
the missing size cap, and the unregistered toolkit).
