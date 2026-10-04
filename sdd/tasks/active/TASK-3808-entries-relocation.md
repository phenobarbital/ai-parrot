# TASK-3808: Relocate `DriveEntry` + guarded serving extension to Graph-free `entries.py`

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. `GoogleDriveFileManager` needs `DriveEntry` and the 413-guarded
`FileServingExtension`, but both live in `graph.py`, which imports msgraph/kiota at module
level. Move them verbatim into `parrot/interfaces/file/entries.py` (imports neither msgraph
nor aiogoogle) and re-import them in `graph.py` under the old names. Pure move — no
behaviour change, no FEAT-603 test edited.

---

## Scope

- Create `entries.py` with `GuardedFileServingExtension` (body of `graph.py:73-102`, class
  renamed without the underscore) and `DriveEntry` (body of `graph.py:104-118`), verbatim.
- In `graph.py`: delete both class blocks, add `from .entries import DriveEntry, GuardedFileServingExtension`
  and the alias `_GuardedFileServingExtension = GuardedFileServingExtension`. Keep the
  `ConflictBehavior` / `LinkType` / `LinkScope` / `AuthMode` literals (`graph.py:98-101`) in `graph.py`.
- Keep `"DriveEntry"` in `graph.__all__`.
- Create `test_entries.py`.

**NOT in scope**: editing any FEAT-603 test; anything gdrive-specific.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/entries.py` | CREATE | Relocated classes |
| `packages/ai-parrot/src/parrot/interfaces/file/graph.py` | MODIFY | Remove blocks, re-import + alias |
| `packages/ai-parrot/tests/interfaces/test_entries.py` | CREATE | Relocation invariants |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web                                     # verified: graph.py:48
from navigator.utils.file.web import FileServingExtension   # verified: graph.py:50; web.py:28
from pydantic import BaseModel, ConfigDict                  # verified: graph.py:51
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/file/graph.py
__all__ = (... "DriveEntry", "GraphDriveFileManager", "GraphFileManagerError")   # :62-70
class _GuardedFileServingExtension(FileServingExtension):                   # :73-95 (handle_file uses self.manager, self.logger)
ConflictBehavior / LinkType / LinkScope / AuthMode = Literal[...]           # :98-101 — STAY in graph.py
class DriveEntry(BaseModel):                                                # :104-118 (model_config extra="forbid")
_GuardedFileServingExtension(...) used in setup()/handle_file()             # graph.py:1117, :1131
```

### Does NOT Exist
- ~~`parrot.interfaces.file.entries`~~ — created here.
- `BaseModel`/`ConfigDict`/`web`/`FileServingExtension` may still be needed by other code in
  `graph.py` — check with grep before removing any import from `graph.py` (keep them if used).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/entries.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/graph.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_entries.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/file/graph.py#_GuardedFileServingExtension",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/graph.py#DriveEntry"
  ]
}
```

---

## Implementation Notes

- Copy the class bodies byte-for-byte (docstrings and comments included) — the FEAT-603
  suites are the regression gate (AC16).
- The guard's comment mentions "transient Graph error"; keep it verbatim (a pure move).
- `test_entries.py` must `sys.modules.pop("parrot.interfaces.file", None)` first (conftest stub,
  `packages/ai-parrot/tests/conftest.py:221-229`).
- The Graph-free check runs in a subprocess (`python -c "import parrot.interfaces.file.entries, sys; ..."`)
  so earlier imports in the pytest process cannot mask a leak.

---

## Implementation Blueprint

### Steps (in order)
1. Create `entries.py` by copying the two blocks — *why*: verbatim move keeps behaviour identical.
2. Replace the blocks in `graph.py` with the import + alias — *why*: old names keep resolving for O365 tools and tests.
3. Run the FEAT-603 suites — *why*: AC16 gate.

### `packages/ai-parrot/src/parrot/interfaces/file/entries.py` (CREATE)
```python
"""Backend-neutral file-manager models shared by Graph and Google Drive managers (FEAT-608 M5).

Moved verbatim from ``graph.py``; imports neither msgraph nor aiogoogle.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from aiohttp import web
from navigator.utils.file.web import FileServingExtension
from pydantic import BaseModel, ConfigDict

__all__ = ("DriveEntry", "GuardedFileServingExtension")


class GuardedFileServingExtension(FileServingExtension):
    # FILL IN: verbatim body of graph.py:74-95 (docstring, __init__, handle_file) — bounded by AC16 (pure move)
    ...


class DriveEntry(BaseModel):
    # FILL IN: verbatim body of graph.py:105-118 — bounded by AC16
    ...
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class _GuardedFileServingExtension(FileServingExtension):' graph.py)
# occurrences: 1 (verified: grep -c 'class DriveEntry(BaseModel):' graph.py)
# REPLACE graph.py:73-95 (the whole _GuardedFileServingExtension class) with:
from .entries import DriveEntry, GuardedFileServingExtension  # noqa: E402  (relocated, FEAT-608 M5)

_GuardedFileServingExtension = GuardedFileServingExtension

# DELETE graph.py:104-118 (the whole `class DriveEntry(BaseModel):` block), leaving the
# ConflictBehavior/LinkType/LinkScope/AuthMode literals (:98-101) untouched.
```
**Why**: `graph.DriveEntry is entries.DriveEntry` and `graph._GuardedFileServingExtension is
entries.GuardedFileServingExtension` (AC16); `setup()` / `handle_file()` at :1117/:1131 keep working
unchanged. Prefer placing the import with the other `from .batch import ...` line (:55) if ruff
flags E402 — either placement is acceptable.

### `packages/ai-parrot/tests/interfaces/test_entries.py` (CREATE)
```python
"""FEAT-608 TASK-3808 — entries.py relocation invariants (AC16)."""
import subprocess
import sys

sys.modules.pop("parrot.interfaces.file", None)


def test_entries_module_is_graph_free():
    # FILL IN: subprocess python -c importing parrot.interfaces.file.entries then asserting
    #          no module name startswith "msgraph"/"kiota"/"aiogoogle" in sys.modules
    ...


def test_graph_reexports_relocated_names():
    from parrot.interfaces.file import entries, graph

    assert graph.DriveEntry is entries.DriveEntry
    assert graph._GuardedFileServingExtension is entries.GuardedFileServingExtension
    assert "DriveEntry" in graph.__all__
```

### FILL IN checklist
- [ ] `entries.py` class bodies — verbatim copies.
- [ ] `test_entries_module_is_graph_free` — subprocess check.

---

## Acceptance Criteria

- [ ] AC16 holds; the FEAT-603 suites pass unchanged.
- [ ] `ruff check` clean on both source files.

## Validation Commands
- `pytest packages/ai-parrot/tests/interfaces/test_entries.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_graph_filemanager.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_graph_fakes.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_sharepoint_filemanager.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_onedrive_filemanager.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_onedrive_client_user_drive.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_feat603_guards.py -q`

---

## Agent Instructions
Standard. `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` inside the worktree.

---

## Completion Note

*(Agent fills this in when done)*
