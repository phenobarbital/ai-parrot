# TASK-3816: `GoogleDriveToolkit` (agent-facing `gdrive_*` tools)

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3814
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (goal G7; AC15). A net-new `AbstractToolkit` in the `GoogleCalendarToolkit`
mould (`calendar.py:74-112`) that delegates every tool to `GoogleDriveFileManager`. Needs the
manager's full public surface (TASK-3811..3814).

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/google/drive.py` with `GoogleDriveToolkit`
  (constructor, `_open`, `_close`, six tools: `list_files`, `search_files`, `download_file`,
  `upload_file`, `share_file`, `get_file_link`) — `tool_prefix="gdrive"` makes them
  `gdrive_list_files` … `gdrive_get_file_link`.
- Export it from `parrot_tools/google/__init__.py`.
- Tests in `packages/ai-parrot-tools/tests/google/test_drive_toolkit.py` using the TASK-3806 fakes.

**NOT in scope**: Workspace export tool; any change to `GoogleCalendarToolkit` / `GoogleBaseTool`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/google/drive.py` | CREATE | Toolkit |
| `packages/ai-parrot-tools/src/parrot_tools/google/__init__.py` | MODIFY | Export |
| `packages/ai-parrot-tools/tests/google/test_drive_toolkit.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit                     # verified: toolkit.py:203
from parrot.interfaces.google import GoogleClient                    # verified: google.py:226 (module-level import OK here — base.py:12 already does it)
from parrot.interfaces.file.gdrive import GoogleDriveFileManager, ShareScope, ShareRole, ConflictBehavior   # TASK-3810
from parrot.conf import OUTPUT_DIR                                   # verified: conf.py:56
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC): tool_prefix: str | None = None (:254); auto_open: bool = False (:316); def __init__(self, **kwargs) (:329); async def _open(self) (:398)
# packages/ai-parrot-tools/src/parrot_tools/google/calendar.py — pattern
class GoogleCalendarToolkit(AbstractToolkit): auto_open = True; __init__ super().__init__(**kwargs) first; _open/_close (:74-112); _close calls await super()._close()
# packages/ai-parrot-tools/src/parrot_tools/google/__init__.py
from .lyria import LyriaToolkit     # :11
    "LyriaToolkit",                 # :22 (last __all__ entry)
# GoogleDriveFileManager public surface (TASK-3810..3814): connect, adopt_client, close, list_files, list_entries,
#   find_files, download_file, upload_file, create_sharing_link, get_file_url, conflict_behavior attribute
# FileManagerToolkit.list_files response shape (plain dicts, isoformat dates)   # filemanager.py:923-938
```

### Does NOT Exist
- ~~`parrot_tools.google.drive`~~, ~~`GoogleDriveTool`~~, ~~`DriveSearchTool`~~ — created here / never.
- ~~`GoogleCalendarToolkit` exported from `parrot_tools.google`~~ — it is not; don't add it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/google/drive.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/google/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/google/test_drive_toolkit.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/google/calendar.py#GoogleCalendarToolkit"
  ]
}
```

---

## Implementation Notes

- Every tool method needs a Google-style docstring — it becomes the LLM tool description.
- Response dicts are plain JSON-able (no `Path`, no Pydantic): `modified_at` via `.isoformat()`.
  Keys exactly as spec §3 M7:
  - `list_files` → `{"entries": [{name, path, is_folder, size, content_type, modified_at, web_url}], "count", "path"}` —
    `include_folders=False` filters out folders; uses `manager.list_entries`; `pattern` fnmatch on name.
  - `search_files` → `{"files": [{name, path, size, content_type, modified_at, url}], "count", "truncated"}`; `max_results`
    (default `self.max_results`) applied after filtering (AC12).
  - `download_file` → `{"downloaded": True, "path", "local_path", "size", "content_type"}`; local file is
    `download_dir / (destination_name or basename(path))`; `download_dir` default `OUTPUT_DIR / "gdrive"`.
  - `upload_file` → `{"uploaded": True, "name", "path", "size", "content_type", "url"}`; missing local file →
    `FileNotFoundError`; per-call `conflict_behavior` temporarily overrides `manager.conflict_behavior`
    (restore in `finally`).
  - `share_file` → `{"shared": True, "path", "scope", "role", "url"}`; `get_file_link` → `{"path", "url"}`.
- `_close` closes the manager only when the toolkit built it.
- Tests: `sys.modules.pop("parrot.interfaces.file", None)` is only needed if the ai-parrot-tools
  test bootstrap stubs it — check `packages/ai-parrot-tools/tests/conftest.py` first. Import the fakes
  with `sys.path` insertion of `packages/ai-parrot/tests/interfaces` or `importlib` by file path —
  FILL IN the least invasive way and record it in the Completion Note.

---

## Implementation Blueprint

### Steps (in order)
1. Create `drive.py` — *why*: AC15.
2. Export from `__init__.py` — *why*: `from parrot_tools.google import GoogleDriveToolkit`.
3. Write tests.

### `packages/ai-parrot-tools/src/parrot_tools/google/drive.py` (CREATE)
```python
"""GoogleDriveToolkit — Google Drive tools for agents (FEAT-608, Module 7)."""
from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from parrot.conf import OUTPUT_DIR
from parrot.interfaces.file.gdrive import ConflictBehavior, GoogleDriveFileManager, ShareRole, ShareScope
from parrot.interfaces.google import GoogleClient
from parrot.tools.toolkit import AbstractToolkit


class GoogleDriveToolkit(AbstractToolkit):
    """Google Drive tools: ``gdrive_list_files``, ``gdrive_search_files``, ``gdrive_download_file``,
    ``gdrive_upload_file``, ``gdrive_share_file``, ``gdrive_get_file_link`` — all delegating to
    :class:`GoogleDriveFileManager`."""

    tool_prefix: str = "gdrive"
    auto_open: bool = True

    def __init__(self, manager: Optional[GoogleDriveFileManager] = None, *, google_client: Optional[GoogleClient] = None,
                 root_id: Optional[str] = None, root_path: str = "", shared_drive_id: Optional[str] = None,
                 prefix: str = "", credentials: Optional[Union[str, Dict[str, Any], Path]] = None,
                 auth_mode: str = "service_account", scopes: Optional[Union[str, List[str]]] = None,
                 download_dir: Optional[Union[str, Path]] = None, max_results: int = 50, **kwargs: Any) -> None:
        """``manager`` wins; else the manager is built from the remaining kwargs in ``_open()``."""
        super().__init__(**kwargs)
        self.logger = logging.getLogger(__name__)
        self._manager = manager
        self._owns_manager = manager is None
        self._google_client = google_client
        self._manager_kwargs = dict(root_id=root_id, root_path=root_path, shared_drive_id=shared_drive_id,
                                    prefix=prefix, credentials=credentials, auth_mode=auth_mode, scopes=scopes)
        self.download_dir = Path(download_dir) if download_dir else Path(OUTPUT_DIR) / "gdrive"
        self.max_results = max_results

    async def _open(self) -> None:
        """Build the manager if needed; adopt ``google_client`` when given, else ``connect()``."""
        # FILL IN: build GoogleDriveFileManager(**self._manager_kwargs) when None; adopt_client(google_client)
        #          then `await manager._ready()` — or `await manager.connect()` — bounded by spec §3 M7 _open docstring
        raise NotImplementedError

    async def _close(self) -> None:
        # FILL IN: close only an owned manager; then `await super()._close()` (calendar.py:108-111 pattern)
        ...

    async def list_files(self, path: str = "", pattern: str = "*", include_folders: bool = False) -> Dict[str, Any]:
        """List a Google Drive folder (non-recursive).

        Args:
            path: Folder path relative to the configured root ("" = root).
            pattern: Glob matched against item names.
            include_folders: Include sub-folders in the result.

        Returns:
            ``{"entries": [...], "count": int, "path": str}``.
        """
        # FILL IN
        raise NotImplementedError

    # FILL IN: search_files / download_file / upload_file / share_file / get_file_link with the exact
    #          spec §3 M7 signatures, full Google-style docstrings and the response keys in Implementation Notes
```

### `packages/ai-parrot-tools/src/parrot_tools/google/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .lyria import LyriaToolkit' parrot_tools/google/__init__.py) — AFTER :11
from .drive import GoogleDriveToolkit
# occurrences: 1 (verified: grep -c '    "LyriaToolkit",' parrot_tools/google/__init__.py) — AFTER :22
    "GoogleDriveToolkit",
```

### `packages/ai-parrot-tools/tests/google/test_drive_toolkit.py` (CREATE)
```python
"""FEAT-608 TASK-3816 — GoogleDriveToolkit."""
import pytest

# FILL IN: import FakeDrive/FakeDriveClient/make_google_client from packages/ai-parrot/tests/interfaces/_gdrive_fakes.py


async def test_toolkit_builds_manager_or_adopts_google_client(): ...
def test_toolkit_tool_names(): ...          # exactly the six gdrive_* names
async def test_toolkit_response_shapes(): ...
async def test_toolkit_search_max_results_after_filtering(): ...   # 3-page fake; truncated flag
async def test_toolkit_download_uses_download_dir(tmp_path): ...
async def test_toolkit_upload_missing_local_file_raises(tmp_path): ...
async def test_toolkit_share_and_link(): ...
```

### FILL IN checklist
- [ ] `_open` / `_close`.
- [ ] Six tools with docstrings and exact response keys.
- [ ] Fake import mechanism; 7 tests.

---

## Acceptance Criteria

- [ ] AC15; AC12 toolkit half (`max_results` after filtering).
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/google/drive.py` clean.

## Validation Commands
- `pytest packages/ai-parrot-tools/tests/google/test_drive_toolkit.py -q`

---

## Agent Instructions
Standard. `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` inside the worktree.

---

## Completion Note

*(Agent fills this in when done)*
