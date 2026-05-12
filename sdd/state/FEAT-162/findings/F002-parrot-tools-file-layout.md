---
id: F002
query_id: Q002
type: glob
intent: Inspect parrot/tools/file/ to verify S3FileManager, LocalFileManager, FileManagerInterface, FileManagerFactory exist and capture their public method signatures.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F002 — `parrot/tools/file/` is empty; canonical location moved to `parrot/interfaces/file/`

## Summary

The brainstorm's `parrot/tools/file/s3.py`, `local.py`, `abstract.py` paths
**no longer exist**. After the FEAT-089 monorepo migration and the
`fileinterface-migration` series (TASK-851, TASK-852, TASK-869, April 2026),
the canonical implementations live in `packages/ai-parrot/src/parrot/interfaces/file/`.
`packages/ai-parrot-tools/src/parrot_tools/file/` only contains a backward-compat
shim re-exporting from `parrot.interfaces.file`. Additionally, all S3/Local/Temp
managers are *themselves* re-exports of `navigator.utils.file.*` upstream
(installed via pip from `navigator-api`).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py`
  lines: 1-24
  symbol: backward-compat shim
  excerpt: |
    """Backward-compat re-exports — canonical location is parrot.interfaces.file."""
    from parrot.interfaces.file import (
        FileManagerInterface, FileMetadata, LocalFileManager, TempFileManager,
    )
    def __getattr__(name: str):
        if name in ("S3FileManager", "GCSFileManager"):
            from parrot.interfaces import file as _file
            return getattr(_file, name)

- path: `packages/ai-parrot/src/parrot/interfaces/file/`
  lines: directory
  symbol: contents
  excerpt: |
    abstract.py  -- re-exports navigator.utils.file.abstract (FileManagerInterface, FileMetadata)
    s3.py        -- re-exports navigator.utils.file.s3 (S3FileManager)
    local.py     -- re-exports navigator.utils.file.local (LocalFileManager)
    gcs.py       -- re-exports navigator.utils.file.gcs (GCSFileManager)
    tmp.py       -- re-exports navigator.utils.file.tmp (TempFileManager)
    __init__.py

- path: `packages/ai-parrot/src/parrot/interfaces/file/abstract.py`
  lines: 1-5
  symbol: shim
  excerpt: |
    """Re-export of navigator.utils.file.abstract for backward compat."""
    from navigator.utils.file.abstract import FileManagerInterface, FileMetadata
    __all__ = ("FileManagerInterface", "FileMetadata")

- path: `packages/ai-parrot/src/parrot/interfaces/file/s3.py`
  lines: 1-5
  symbol: shim
  excerpt: |
    """Re-export of navigator.utils.file.s3 for backward compat."""
    from navigator.utils.file.s3 import S3FileManager
    __all__ = ("S3FileManager",)

## Notes

- The brainstorm's "Existing infrastructure to reuse" table cites the wrong
  paths. For the spec, use either `parrot.interfaces.file` (preferred, parrot
  namespace) or directly `navigator.utils.file` (where the real code lives).
- See F020 for the recent commit history showing the migration.
