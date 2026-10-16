# Feature Specification: GoogleDriveToolkit upload_file path safety

---
feature_id: FEAT-690
type: feature
base_branch: dev
projects: [ai-parrot-tools]
tags: [security, gdrive]
status: approved
version: 0.1
---

## 1. Problem Statement

`GoogleDriveToolkit.upload_file` (FEAT-608, Module 7) has two security issues
discovered during code review (ledger `issue:46cf08490263`):

1. **Arbitrary local-path read**: `source_path` is passed directly to
   `Path()` with no validation. An LLM-controlled agent can read ANY file on
   the host filesystem and exfiltrate it to Google Drive.

2. **Shared-manager mutation**: `conflict_behavior` is temporarily mutated on
   `self._manager` (a shared object). Concurrent calls see the wrong policy
   and the `finally` restore is not concurrency-safe.

## 2. Proposed Solution

### M1 — Path confinement

Add an `upload_root` parameter to `GoogleDriveToolkit.__init__` (default:
the toolkit's `download_dir`). In `upload_file`, resolve `source_path`
against `upload_root` and reject any path that escapes it (traversal, symlink
escape, absolute paths, NUL bytes). Use the same `_validate_remote_path`-style
checks already established by FEAT-643 (`SessionFileToolkit`), adapted for
local paths.

### M2 — Conflict-behavior isolation

Replace the mutate-restore pattern with a keyword argument forwarded to the
manager's `upload_file()` call, or with a context-local copy. The
`GoogleDriveFileManager.upload_file` signature will be checked: if it already
accepts `conflict_behavior`, pass it through directly; otherwise create a
shallow copy of the manager's settings for the duration of the call.

## 3. Acceptance Criteria

- AC1: `upload_file("../../etc/passwd", "dest")` raises `ValueError` before
  any I/O.
- AC2: `upload_file("/etc/passwd", "dest")` raises `ValueError`.
- AC3: `upload_file("subdir/file.txt", "dest")` succeeds when
  `upload_root/subdir/file.txt` exists.
- AC4: Symlink pointing outside `upload_root` is rejected.
- AC5: Concurrent `upload_file` calls with different `conflict_behavior`
  values do not interfere with each other.
- AC6: Existing callers that do not pass `upload_root` keep working (the
  default is `download_dir`).

## 4. Files to Modify

- `packages/ai-parrot-tools/src/parrot_tools/google/drive.py`

## 5. Test Files

- `packages/ai-parrot-tools/tests/google/test_gdrive_toolkit_upload_safety.py`
