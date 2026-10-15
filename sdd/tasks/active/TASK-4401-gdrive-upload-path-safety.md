# TASK-4401: GoogleDriveToolkit upload_file path confinement and conflict-behavior isolation

- **Feature**: gdrive-toolkit-upload-path-safety
- **Feature ID**: FEAT-690
- **Spec**: sdd/specs/gdrive-toolkit-upload-path-safety.spec.md
- **Status**: pending
- **Priority**: high
- **Estimated effort**: M
- **Depends-on**: —
- **Assigned-to**: —

## Context

`GoogleDriveToolkit.upload_file` accepts an arbitrary `source_path` from the
LLM and passes it directly to `Path()` with no confinement — enabling
arbitrary file exfiltration. The `conflict_behavior` parameter mutates a
shared manager attribute, breaking concurrent calls.

## Scope

### In scope

- Add `upload_root` parameter (default = `download_dir`) and a
  `_validate_local_source` helper that:
  - resolves `source_path` against `upload_root`
  - rejects absolute paths, `..` traversal, NUL bytes, and symlinks
    escaping `upload_root`
- Replace `conflict_behavior` mutate-restore with a direct keyword argument
  to the manager or a local copy.
- Tests covering AC1–AC6.

### NOT in scope

- Changes to `GoogleDriveFileManager` itself (interface unchanged).
- Changes to `download_file`.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/google/drive.py` | Modify |
| `packages/ai-parrot-tools/tests/google/test_gdrive_toolkit_upload_safety.py` | Create |

## Codebase Contract

### Verified Imports
- `from parrot.interfaces.file.gdrive import ConflictBehavior, GoogleDriveFileManager` — exists
- `from parrot.conf import OUTPUT_DIR` — exists
- `from parrot.tools.toolkit import AbstractToolkit` — exists

### Existing Signatures
- `GoogleDriveToolkit.__init__(self, manager, *, google_client, root_id, root_path, shared_drive_id, prefix, credentials, auth_mode, scopes, download_dir, max_results, **kwargs)` — drive.py:22
- `GoogleDriveToolkit.upload_file(self, source_path, destination, conflict_behavior=None)` — drive.py:176
- `GoogleDriveFileManager.upload_file(source, destination)` — to be checked at implementation time

### Does NOT Exist
- `GoogleDriveToolkit._validate_local_source` — to be created
- `packages/ai-parrot-tools/tests/google/test_gdrive_toolkit_upload_safety.py` — to be created

## Implementation Blueprint

1. Add `upload_root: Optional[Union[str, Path]] = None` to `__init__`,
   defaulting to `self.download_dir` after it is set.
2. Add `_validate_local_source(self, source_path: str) -> Path`:
   - Reject empty, NUL-containing, absolute, drive-qualified paths.
   - `resolved = (self.upload_root / source_path).resolve()`.
   - Check `resolved.is_relative_to(self.upload_root)` — rejects `..`
     traversal and symlink escape.
   - Check `resolved.is_file()`.
   - Return `resolved`.
3. In `upload_file`, call `_validate_local_source(source_path)` and pass
   `resolved` to the manager.
4. For `conflict_behavior`, check if `GoogleDriveFileManager.upload_file`
   accepts a `conflict_behavior` keyword. If yes, pass it through. If no,
   create a shallow copy of the behaviour for the call scope without
   mutating the shared instance.
5. Create test file with cases for AC1–AC6.

## Acceptance Criteria

- [ ] AC1: `upload_file("../../etc/passwd", "dest")` → ValueError
- [ ] AC2: `upload_file("/etc/passwd", "dest")` → ValueError
- [ ] AC3: `upload_file("subdir/file.txt", "dest")` succeeds when file exists under `upload_root`
- [ ] AC4: Symlink pointing outside `upload_root` → ValueError
- [ ] AC5: Concurrent uploads with different `conflict_behavior` do not interfere
- [ ] AC6: No `upload_root` → default to `download_dir`, existing behaviour preserved

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot-tools/src:packages/ai-parrot/src pytest packages/ai-parrot-tools/tests/google/test_gdrive_toolkit_upload_safety.py -v
```

## Test Specification

Unit tests with mocked `GoogleDriveFileManager`:
- `test_traversal_rejected` — AC1
- `test_absolute_path_rejected` — AC2
- `test_valid_subdir_upload` — AC3
- `test_symlink_escape_rejected` — AC4
- `test_concurrent_conflict_behavior_isolation` — AC5
- `test_default_upload_root_is_download_dir` — AC6

## Agent Instructions

Single-file vulnerability fix. Check `GoogleDriveFileManager.upload_file`
signature before deciding the conflict_behavior strategy.

## Completion Note

*(filled after implementation)*
