# TASK-3815: Register `gdrive` — shims, factory, `ManagerType`, drive-relative sets, tests

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3810
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (goal G6; AC13, AC14). Make `gdrive` discoverable everywhere FEAT-603 made
`sharepoint` / `onedrive` discoverable. Only needs `parrot.interfaces.file.gdrive.GoogleDriveFileManager`
to import (TASK-3810). The class may still be abstract while TASK-3811..3814 are in flight, so
construction tests clear `__abstractmethods__` with `monkeypatch` (FEAT-603 precedent,
`test_file_shim.py:159-181`).

---

## Scope

- `parrot/interfaces/file/__init__.py`: docstring mention, `__all__` += `"GoogleDriveFileManager"`,
  `_LAZY_MANAGERS["GoogleDriveFileManager"] = "parrot.interfaces.file.gdrive"`.
- `parrot_tools/file/__init__.py`: `__all__` += name; lazy tuple += name.
- `parrot/tools/filemanager.py`: comment (:25-27), `ManagerType` (:28), `FileManagerFactory`
  docstring (:37) and `_PARROT_NATIVE` (:49-52), `create` docstring (:59-60), `FileManagerTool.description`
  (:183) and `__init__` docstring (:198), both `# s3, gcs, sharepoint, or onedrive` comments
  (:256, :847), both `_DRIVE_RELATIVE_BACKENDS` (:259, :864) + the comment above :864,
  toolkit docstring backend list (:748) and `__init__` docstring (:773).
- Tests: extend `test_file_shim.py` and `test_filemanager_batch_ops.py`.

**NOT in scope**: `_OP_TO_METHOD` / op implementations (unchanged — they dispatch on
`hasattr(self.manager, "upload_files")`, `filemanager.py:1312`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` | MODIFY | Lazy export |
| `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py` | MODIFY | Lazy parity export |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | Literal, factory map, drive-relative sets, docstrings |
| `packages/ai-parrot/tests/interfaces/test_file_shim.py` | MODIFY | Leak / lazy / parity / factory tests |
| `packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` | MODIFY | `_storage_path` covers gdrive |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/file/__init__.py
__all__ = (..., "SharePointFileManager", "OneDriveFileManager",)          # :26-35
_LAZY_MANAGERS = {..., "OneDriveFileManager": "parrot.interfaces.file.onedrive",}   # :37-43 (anchor :42)
def __getattr__(name)                                                       # :46-52
# packages/ai-parrot-tools/src/parrot_tools/file/__init__.py
__all__ = (...)                                                             # :10-19
if name in ("S3FileManager", "GCSFileManager", "SharePointFileManager", "OneDriveFileManager"):   # :24
# packages/ai-parrot/src/parrot/tools/filemanager.py
ManagerType = Literal["fs", "temp", "s3", "gcs", "sharepoint", "onedrive"]  # :28
_PARROT_NATIVE = {"sharepoint": (...), "onedrive": ("parrot.interfaces.file.onedrive", "OneDriveFileManager"),}   # :49-52
class FileManagerTool(AbstractTool)                                         # :154 ; _DRIVE_RELATIVE_BACKENDS :259
class FileManagerToolkit(AbstractToolkit)                                   # :721 ; _DRIVE_RELATIVE_BACKENDS :864
# tests
def test_no_msgraph_leak_on_import()                                        # test_file_shim.py:43
def test_shim_exports_new_managers_lazily()                                 # :140
def test_parrot_tools_file_shim_parity()                                    # :151
def test_factory_sharepoint_and_onedrive_native(monkeypatch)                # :159
def test_factory_unknown_lists_all_keys()                                   # :181 (asserts six keys)
def test_storage_path_is_drive_relative_for_graph_and_unchanged_otherwise() # test_filemanager_batch_ops.py:170
```

### Does NOT Exist
- ~~`packages/ai-parrot/tests/tools/test_filemanager_toolkit.py`~~ — toolkit tests are `test_filemanager_batch_ops.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/file/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/tools/filemanager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_file_shim.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerTool",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerToolkit"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Edit both shims — *why*: AC13 lazy exports.
2. Edit `filemanager.py` (literal, map, sets, docs) — *why*: AC14.
3. Extend the two test modules — *why*: guard the registration.

### `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "OneDriveFileManager": "parrot.interfaces.file.onedrive",' file/__init__.py)
# AFTER — insert below that line (verified: file/__init__.py:42)
    # Parrot-native Google Drive manager (FEAT-608) — lazy so importing this package never loads aiogoogle/selenium/redis.
    "GoogleDriveFileManager": "parrot.interfaces.file.gdrive",
# ALSO: in `__all__ = (` (occurrences: 1, :26) add `"GoogleDriveFileManager",` after `"OneDriveFileManager",`;
#       in the module docstring's "Lazy re-exports" list add GoogleDriveFileManager and "aiogoogle".
```

### `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if name in ("S3FileManager", "GCSFileManager", "SharePointFileManager", "OneDriveFileManager"):' parrot_tools/file/__init__.py)
# REPLACE :24 with:
    if name in ("S3FileManager", "GCSFileManager", "SharePointFileManager", "OneDriveFileManager", "GoogleDriveFileManager"):
# ALSO: `__all__ = (` (occurrences: 1, :10) gains `"GoogleDriveFileManager",` after `"OneDriveFileManager",`
```

### `packages/ai-parrot/src/parrot/tools/filemanager.py` (MODIFY)
```python
# occurrences: 1 — ManagerType = Literal["fs", "temp", "s3", "gcs", "sharepoint", "onedrive"]  (:28) → REPLACE:
ManagerType = Literal["fs", "temp", "s3", "gcs", "sharepoint", "onedrive", "gdrive"]
# occurrences: 1 — `        "onedrive": ("parrot.interfaces.file.onedrive", "OneDriveFileManager"),` (:51) → AFTER:
        "gdrive": ("parrot.interfaces.file.gdrive", "GoogleDriveFileManager"),  # FEAT-608
# occurrences: 2 — `    _DRIVE_RELATIVE_BACKENDS = frozenset({"sharepoint", "onedrive"})`
# FILL IN: disambiguate — replace BOTH (the one right after FileManagerTool._create_manager's
#          `else:  # s3, gcs, sharepoint, or onedrive` / `return FileManagerFactory.create(manager_type, **kwargs)` at :256-259,
#          and the one preceded by `#: joined onto the local ``default_output_dir`` (FEAT-603).` at :862-864) with
#          `_DRIVE_RELATIVE_BACKENDS = frozenset({"sharepoint", "onedrive", "gdrive"})`; update the :862-863 comment
#          to "(Microsoft Graph document libraries and Google Drive)".
# occurrences: 2 — `        else:  # s3, gcs, sharepoint, or onedrive` (:256, :847) → both become
#          `        else:  # s3, gcs, sharepoint, onedrive, or gdrive`
# FILL IN: docstrings/strings — :25-27 comment, :37-38 class docstring, :59-60 create docstring, :183 description
#          ("..., SharePoint, OneDrive, Google Drive, temp)"), :198 and :773 manager_type lists (add "gdrive"),
#          :748 add line `      - ``"gdrive"`` — Google Drive folder or shared drive (requires ai-parrot[gdrive])`
```

### `packages/ai-parrot/tests/interfaces/test_file_shim.py` (MODIFY)
```python
# occurrences: 1 — AFTER the body of `def test_no_msgraph_leak_on_import():` (:43-49) insert:
def test_no_gdrive_leak_on_import():
    """Importing parrot.interfaces.file does not load aiogoogle/selenium/redis or the gdrive module (FEAT-608 AC13)."""
    watched = ("aiogoogle", "selenium", "redis", "parrot.interfaces.file.gdrive")
    if any(m in sys.modules for m in watched):
        pytest.skip("a watched module was already loaded by a prior test")
    importlib.reload(shim)
    for m in watched:
        assert m not in sys.modules
# FILL IN: better — also run the same check in a subprocess (`python -c "import parrot.interfaces.file, parrot_tools.file, sys; ..."`)
#          so it never skips in a full run.

# occurrences: 1 — test_factory_unknown_lists_all_keys (:181): change the tuple to seven keys incl. "gdrive" and the docstring to "seven".
# APPEND at end of file:
def test_shim_exports_gdrive_lazily(): ...                  # shim.GoogleDriveFileManager is gdrive.GoogleDriveFileManager; in __all__
def test_parrot_tools_file_shim_gdrive_parity(): ...
def test_factory_gdrive_native(monkeypatch): ...            # clear __abstractmethods__; create("gdrive", root_path="x") → instance, no I/O
def test_toolkit_literal_accepts_gdrive(monkeypatch): ...   # FileManagerToolkit(manager_type="gdrive", root_path="x").get_tools() builds
```

### `packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` (MODIFY)
```python
# occurrences: 1 — inside test_storage_path_is_drive_relative_for_graph_and_unchanged_otherwise (:170), AFTER
#   `    assert tk_graph._storage_path("a/b.txt") == "a/b.txt"` add:
    tk_gdrive = FileManagerToolkit.__new__(FileManagerToolkit)
    tk_gdrive.manager_type = "gdrive"
    assert tk_gdrive._storage_path("a/b.txt") == "a/b.txt"
# FILL IN: the same assertion for FileManagerTool (FileManagerTool.__new__ + manager_type="gdrive") as a new test
#          test_storage_path_is_drive_relative_for_gdrive
```

### FILL IN checklist
- [ ] Both `_DRIVE_RELATIVE_BACKENDS` edits (ambiguous anchor — use class context).
- [ ] Docstring/string edits.
- [ ] Subprocess leak check; five new/updated shim tests; batch-ops test.

---

## Acceptance Criteria

- [ ] AC13, AC14.
- [ ] All pre-existing tests in both test modules still pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/interfaces/test_file_shim.py -q`
- `pytest packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py -q`

---

## Agent Instructions
Standard. `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` inside the worktree.

---

## Completion Note

*(Agent fills this in when done)*
