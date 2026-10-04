---
id: F011
query_id: Q014
type: grep
intent: FileManagerFactory / manager_type literal / _PARROT_NATIVE / _OP_TO_METHOD / drive-relative path handling (worktree vs dev)
executed_at: 2026-09-25T22:54:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# F011 — Four edit sites in `parrot/tools/filemanager.py` register a parrot-native backend; `find`/`batch_*` ops are already generic

## Summary

On `dev` the factory only knows `_PARROT_TO_UPSTREAM` (`fs|temp|s3|gcs`) and
`manager_type: Literal["fs","temp","s3","gcs"]`. The FEAT-603 worktree adds a
module-level `ManagerType` literal (six keys), `FileManagerFactory._PARROT_NATIVE`
mapping key → `(module, class)` resolved by lazy import, and the
`_DRIVE_RELATIVE_BACKENDS` frozenset (used by both `FileManagerTool` and
`FileManagerToolkit._storage_path`) so drive-relative backends skip the
`default_output_dir` join. `_OP_TO_METHOD` already carries `find`,
`batch_upload`, `batch_download`; the toolkit falls back to looping single
ops for backends without `upload_files`/`download_files`. Adding Drive means
one key in each of `ManagerType`, `_PARROT_NATIVE`, `_DRIVE_RELATIVE_BACKENDS`
(×2) and the docstring lists.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/filemanager.py`
  lines: 30-39
  symbol: `FileManagerFactory._PARROT_TO_UPSTREAM` (dev)
  excerpt: |
    _PARROT_TO_UPSTREAM = { ..., "gcs": "gcs" }
    manager_type: Literal["fs", "temp", "s3", "gcs"],

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/tools/filemanager.py`
  lines: 27-52
  symbol: `ManagerType / FileManagerFactory._PARROT_NATIVE`
  excerpt: |
    ManagerType = Literal["fs", "temp", "s3", "gcs", "sharepoint", "onedrive"]
    _PARROT_NATIVE = {
        "sharepoint": ("parrot.interfaces.file.sharepoint", "SharePointFileManager"),
        "onedrive": ("parrot.interfaces.file.onedrive", "OneDriveFileManager"),
    }

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/tools/filemanager.py`
  lines: 69-77
  symbol: `FileManagerFactory.create`
  excerpt: |
    native = FileManagerFactory._PARROT_NATIVE.get(manager_type)
    ... available = sorted({**_PARROT_TO_UPSTREAM, **_PARROT_NATIVE}); raise ValueError(f"Unknown manager type: {manager_type}. Available: {available}")

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/tools/filemanager.py`
  lines: 259-271
  symbol: `FileManagerTool._DRIVE_RELATIVE_BACKENDS`
  excerpt: |
    _DRIVE_RELATIVE_BACKENDS = frozenset({"sharepoint", "onedrive"})

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/tools/filemanager.py`
  lines: 704-718
  symbol: `_OP_TO_METHOD / _ALL_OPS`
  excerpt: |
    "find": "find_files", "batch_upload": "batch_upload", "batch_download": "batch_download",

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/tools/filemanager.py`
  lines: 862-881
  symbol: `FileManagerToolkit._DRIVE_RELATIVE_BACKENDS / _storage_path`
  excerpt: |
    _DRIVE_RELATIVE_BACKENDS = frozenset({"sharepoint", "onedrive"})
    def _storage_path(self, path: Optional[str]) -> str:
        if self.manager_type in self._DRIVE_RELATIVE_BACKENDS: return (path or "").strip()

- path: `.claude/worktrees/feat-FEAT-603-sharepoint-filemanager/packages/ai-parrot/src/parrot/tools/filemanager.py`
  lines: 721-773
  symbol: `FileManagerToolkit.__init__` docstring
  excerpt: |
    - ``"sharepoint"`` — SharePoint document library (requires ai-parrot[msgraph])
    - ``"onedrive"`` — a user's OneDrive (requires ai-parrot[msgraph])
