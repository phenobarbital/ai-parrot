# TASK-3817: FEAT-608 cross-cutting guards (parity, bans, signature snapshot, relocation)

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3807, TASK-3808, TASK-3815, TASK-3816
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 (AC1, AC2, AC4-snapshot, AC18, AC23). The FEAT-603 guard set
(`test_feat603_guards.py` + `feat603_signature_snapshot.json`) applied to this feature.

---

## Scope

- Create `packages/ai-parrot/tests/interfaces/test_gdrive_guards.py` with the six tests in the
  spec §3 M10 skeleton.
- Create `packages/ai-parrot/tests/interfaces/gdrive_signature_snapshot.json` — public-method
  signatures (`str(inspect.signature(...))`) of `GoogleClient` (minus `get_drive_client`),
  `CalendarClient`, `GoogleBaseTool`, `GoogleCalendarToolkit`, `FileManagerFactory.create`,
  `FileManagerTool.__init__`, `FileManagerToolkit.__init__`, `GraphDriveFileManager`,
  `SharePointFileManager`, `OneDriveFileManager` **as they are on the base commit**.

**NOT in scope**: editing `test_feat603_guards.py` or its snapshot.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/interfaces/test_gdrive_guards.py` | CREATE | Guard tests |
| `packages/ai-parrot/tests/interfaces/gdrive_signature_snapshot.json` | CREATE | Base-commit signature snapshot |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator.utils.file import FileManagerInterface                        # verified: abstract.py:36
from parrot.interfaces.file.gdrive import GoogleDriveFileManager              # TASK-3810..3814
from parrot.interfaces.file import entries, graph                             # TASK-3808; graph.py
from parrot.interfaces.google import GoogleClient, CalendarClient             # verified: google.py:226, :160
from parrot_tools.google.base import GoogleBaseTool                           # verified: base.py:36
from parrot_tools.google.calendar import GoogleCalendarToolkit                # verified: calendar.py:74
from parrot.tools.filemanager import FileManagerFactory, FileManagerTool, FileManagerToolkit   # verified: filemanager.py:31, :154, :721
from parrot.interfaces.file.graph import GraphDriveFileManager                # verified: graph.py:142
from parrot.interfaces.file.sharepoint import SharePointFileManager           # verified: sharepoint.py:12
from parrot.interfaces.file.onedrive import OneDriveFileManager
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/interfaces/test_feat603_guards.py — pattern
ROOT = pathlib.Path(__file__).resolve().parents[4]         # :16
BANNED_MODULES = frozenset({"httpx", "requests", "langchain", ...})   # :50-52
test_no_banned_imports_or_print_in_new_modules              # :69 (AST walk: Import/ImportFrom + print Call)
# test_graph_filemanager.py:523-528 — interface-signature parity pattern
```

### Does NOT Exist
- ~~`gdrive_signature_snapshot.json`~~ — created here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/interfaces/test_gdrive_guards.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interfaces/gdrive_signature_snapshot.json", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/google.py#GoogleClient",
    "sym:packages/ai-parrot-tools/src/parrot_tools/google/base.py#GoogleBaseTool",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory"
  ]
}
```

---

## Implementation Notes

- **Snapshot provenance**: generate the JSON from the **base commit** — the merge-base of the
  feature branch with `origin/dev` (`git merge-base HEAD origin/dev`) — e.g. `git worktree add
  --detach <scratch> <sha>` (then remove it) and run a small extraction script with
  `PYTHONPATH=<scratch>/packages/ai-parrot/src:<scratch>/packages/ai-parrot-tools/src`. Record the sha
  in the JSON (`"base_commit"`). Never regenerate it from the feature branch — that would make AC23 vacuous.
- `test_public_signatures_unchanged_vs_snapshot` compares every snapshot entry to the live
  signature; `GoogleClient.get_drive_client` is excluded (its return annotation is the only allowed change).
- `test_all_interface_methods_implemented_with_exact_signatures`: for every abstract method in
  `FileManagerInterface` plus `create_folder/remove_folder/rename_folder/rename_file/find_files`,
  `inspect.signature(GoogleDriveFileManager.m) == inspect.signature(FileManagerInterface.m)` (compare
  parameter names/kinds/defaults; tolerate annotation string-vs-object differences caused by
  `from __future__ import annotations` by comparing `str()` forms after normalisation — FILL IN).
- `test_no_httpx_or_requests_in_new_modules`: AST scan of `gdrive.py`, `entries.py`,
  `parrot_tools/google/drive.py` for banned imports and `print(` calls (AC18).
- `test_gdrive_module_imports_no_google_client_at_module_level`: subprocess `import parrot.interfaces.file.gdrive`
  then assert `parrot.interfaces.google` and `aiogoogle` not in `sys.modules` (AC2).
- `sys.modules.pop("parrot.interfaces.file", None)` at the top.

---

## Implementation Blueprint

### Steps (in order)
1. Generate the snapshot from the base commit — *why*: AC23 compares against pre-feature signatures.
2. Write the six tests — *why*: AC1/AC2/AC18/AC23/AC16.

### `packages/ai-parrot/tests/interfaces/test_gdrive_guards.py` (CREATE)
```python
"""FEAT-608 TASK-3817 — cross-cutting invariants (AC1, AC2, AC16, AC18, AC23)."""
import ast
import inspect
import json
import pathlib
import subprocess
import sys

import pytest

sys.modules.pop("parrot.interfaces.file", None)

ROOT = pathlib.Path(__file__).resolve().parents[4]
SNAPSHOT = pathlib.Path(__file__).with_name("gdrive_signature_snapshot.json")
NEW_MODULES = [
    ROOT / "packages/ai-parrot/src/parrot/interfaces/file/gdrive.py",
    ROOT / "packages/ai-parrot/src/parrot/interfaces/file/entries.py",
    ROOT / "packages/ai-parrot-tools/src/parrot_tools/google/drive.py",
]
BANNED_MODULES = frozenset({"httpx", "requests", "langchain", "langchain_core", "langchain_community", "langgraph", "langsmith"})
INTERFACE_METHODS = ("list_files", "get_file_url", "upload_file", "download_file", "copy_file", "delete_file", "exists",
                     "get_file_metadata", "create_file", "create_folder", "remove_folder", "rename_folder", "rename_file",
                     "find_files")


def test_all_interface_methods_implemented_with_exact_signatures(): ...   # FILL IN (+ issubclass, not a GraphDriveFileManager subclass)
def test_get_file_url_signature_matches_interface(): ...
def test_no_httpx_or_requests_in_new_modules(): ...                          # FILL IN: AST scan (test_feat603_guards.py:69 pattern)
def test_public_signatures_unchanged_vs_snapshot(): ...                      # FILL IN: exclude GoogleClient.get_drive_client
def test_graph_reexports_relocated_names(): ...
def test_gdrive_module_imports_no_google_client_at_module_level(): ...      # FILL IN: subprocess
```

### FILL IN checklist
- [ ] Snapshot JSON from the base commit (sha recorded).
- [ ] Six tests.

---

## Acceptance Criteria

- [ ] AC1, AC2, AC18, AC23 guarded; AC16 re-asserted.

## Validation Commands
- `pytest packages/ai-parrot/tests/interfaces/test_gdrive_guards.py -q`

---

## Agent Instructions
Standard. `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` inside the worktree.

---

## Completion Note

*(Agent fills this in when done)*
