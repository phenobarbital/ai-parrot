---
id: F010
query_id: Q013
type: read
intent: file/__init__.py (dev + FEAT-603 worktree) and parrot_tools.file shim — the lazy registration pattern
executed_at: 2026-09-25T22:53:50Z
duration_ms: 400
parent_id: null
depth: 0
---

# F010 — Registration is a two-line edit per shim: `__all__` + `_LAZY_MANAGERS` entry, mirrored in `parrot_tools.file`

## Summary

On `dev`, `parrot/interfaces/file/__init__.py` eagerly re-exports
`FileManagerInterface`, `FileMetadata`, `LocalFileManager`, `TempFileManager`
from `navigator.utils.file` and lazily resolves `S3FileManager` /
`GCSFileManager` through `_LAZY_MANAGERS` + `__getattr__` so no cloud SDK is
imported at package load. The FEAT-603 worktree adds `SharePointFileManager`
/ `OneDriveFileManager` pointing at **parrot** modules
(`parrot.interfaces.file.sharepoint` / `.onedrive`). `parrot_tools/file/__init__.py`
re-exports the same names lazily from core. `test_file_shim.py::test_no_cloud_sdk_leak_on_import`
guards the leak invariant.

## Citations

- path: `packages/ai-parrot/src/parrot/interfaces/file/__init__.py`
  lines: 26-42
  symbol: `__all__ / _LAZY_MANAGERS / __getattr__`
  excerpt: |
    _LAZY_MANAGERS = {"S3FileManager": "navigator.utils.file.s3", "GCSFileManager": "navigator.utils.file.gcs"}
    def __getattr__(name: str):
        if name in _LAZY_MANAGERS: mod = importlib.import_module(_LAZY_MANAGERS[name]); ...

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/interfaces/file/__init__.py`
  lines: 37-43
  symbol: `_LAZY_MANAGERS` (FEAT-603)
  excerpt: |
    # Parrot-native Graph managers (FEAT-603) — lazy so importing this package never loads msgraph.
    "SharePointFileManager": "parrot.interfaces.file.sharepoint",
    "OneDriveFileManager": "parrot.interfaces.file.onedrive",

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot-tools/src/parrot_tools/file/__init__.py`
  lines: 21-27
  symbol: `__getattr__`
  excerpt: |
    if name in ("S3FileManager", "GCSFileManager", "SharePointFileManager", "OneDriveFileManager"):
        from parrot.interfaces import file as _file
        return getattr(_file, name)

- path: `packages/ai-parrot/tests/interfaces/test_file_shim.py`
  lines: 21-100
  symbol: tests
  excerpt: |
    def test_root_identity(): ...
    def test_no_cloud_sdk_leak_on_import(): ...
    def test_lazy_identity(): ...
    def test_factory_unknown_type_raises_valueerror(): ...
