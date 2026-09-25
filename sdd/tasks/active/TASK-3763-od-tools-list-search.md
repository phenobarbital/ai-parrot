# TASK-3763: OneDrive O365 tools (List, Search) delegate to OneDriveFileManager

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3757, TASK-3751
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 8** (first half; Download/Upload are TASK-3764), AC13, design research **S1**, **S4**, **S8**, **S9**.
The OneDrive List/Search tools call `client.verify_onedrive_access()` / `client.file_list()` / `client.file_search()`
(`parrot_tools/o365/onedrive.py:79-86`, `:176-179`) on what `O365Tool._get_client` actually returns — a plain
`O365Client` without those methods (`base.py:148`). Routing through `OneDriveFileManager.adopt_client` fixes that and
adds user targeting: the target user is the tool's existing `user_id` argument (`O365ToolArgsSchema.user_id`,
`base.py:40`, left in `kwargs` by `O365Tool._execute`), defaulting to `"me"`.

The OneDrive file dicts are **camelCase** (`webUrl`, `isFolder`) — unlike SharePoint's — and must stay so (AC13).

---

## Scope

- In `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py`: add the manager import; rewrite
  `ListOneDriveFilesTool._execute_graph_operation`, `_list_recursive`, and `SearchOneDriveFilesTool._execute_graph_operation`.
- Create `packages/ai-parrot-tools/tests/test_o365_onedrive_file_tools.py` (TASK-3764 appends).

**NOT in scope**: Download/Upload (TASK-3764); `DeltaOneDriveFiles*` and their imports (byte-identical, FEAT-539).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` | MODIFY | List + Search bodies via the manager |
| `packages/ai-parrot-tools/tests/test_o365_onedrive_file_tools.py` | CREATE | response-shape tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
from parrot.interfaces.file.onedrive import OneDriveFileManager       # TASK-3757
from parrot.interfaces.o365 import O365Client                         # already imported: o365/onedrive.py:17
from parrot_tools.o365.onedrive import ListOneDriveFilesTool, SearchOneDriveFilesTool   # tests
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py
from parrot.interfaces.onedrive import OneDriveClient                 # :18 (keep until TASK-3764)
class ListOneDriveFilesArgs(O365ToolArgsSchema): folder_path="", recursive=False     # :25-31
class ListOneDriveFilesTool(O365Tool):                               # :34 — name "list_onedrive_files"
    async def _execute_graph_operation(self, client: OneDriveClient, **kwargs) -> Dict[str, Any]   # :61-99
        # returns {"folder_path": folder_path or "root", "total_items", "files", "recursive"}   (:90-95)
    async def _list_recursive(self, client, folder_path) -> List[Dict[str, Any]]   # :101-118 (folders + descendants)
class SearchOneDriveFilesArgs(O365ToolArgsSchema): query, max_results=20            # :126-130
class SearchOneDriveFilesTool(O365Tool):                             # :133 — name "search_onedrive_files"
    async def _execute_graph_operation(self, client: OneDriveClient, **kwargs) -> Dict[str, Any]   # :158-191
        # max_results = min(kwargs.get("max_results", 20), 100); returns {"query", "total_results", "files"}   (:187)
# File dict shape produced today by OneDriveClient.file_list / file_search (interfaces/onedrive.py:167-242):
#   {"name", "id", "webUrl", "path", "isFolder", "size", "modified"}   (camelCase; "modified" ISO string or None)
# packages/ai-parrot-tools/src/parrot_tools/o365/base.py
class O365ToolArgsSchema(AbstractToolArgsSchema): user_id: Optional[str]   # :40 — stays in kwargs (O365Tool._execute pops only auth_mode, user_assertion, scopes: :239-242)
# From TASK-3751/3757: OneDriveFileManager(user="me", *, credentials=...), adopt_client, list_entries, find_entries, close
```

### Does NOT Exist
- ~~`OneDriveClient.verify_onedrive_access` on the client the tool receives~~ — `_get_client` returns a plain `O365Client`.
- ~~a `folder_path` filter on OneDrive search today~~ — the Search tool has none; `find_entries` is called with no prefix.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/test_o365_onedrive_file_tools.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py#ListOneDriveFilesTool._execute_graph_operation",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py#ListOneDriveFilesTool._list_recursive",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py#SearchOneDriveFilesTool._execute_graph_operation",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/base.py#O365ToolArgsSchema"
  ]
}
```

---

## Implementation Notes

- `manager = OneDriveFileManager(user=kwargs.get("user_id") or "me", credentials=dict(self.credentials or {}))`,
  `manager.adopt_client(client)`, `try … finally: await manager.close()`. Under app-only auth without `user_id` the
  manager raises the explicit "me requires delegated auth" `RuntimeError` — surfaced by `O365Tool._execute` as a failed
  `ToolResult` (better than today's `AttributeError`).
- `_entry_dict(entry)` → `{"name", "id", "webUrl": entry.web_url, "path": entry.path, "isFolder": entry.is_folder,
  "size", "modified": ISO or None}`.
- List: non-recursive `list_entries(folder_path)`; recursive breadth-first (all pages each). Search: `find_entries(
  keywords=query)` then slice to `max_results` (after filtering, S4). Search results carry `"isFolder": False` as today.
- Load the fakes by path exactly as TASK-3761 does (same helper block); use `fakes.make_onedrive_client(fake,
  app_only=False)` for `"me"` and `app_only=True` with a `user_id` kwarg for the app-only path.

### Key Constraints (all FEAT-603 tasks)
- **aiohttp only** for raw HTTP. `httpx`, `requests`, `langchain*` are banned (ruff TID251). The two legacy
  clients carry an unused `import httpx` (`interfaces/sharepoint.py:11`, `interfaces/onedrive.py:10`) — never copy
  their import blocks into new code.
- **Core never imports the tools distribution**: nothing under `packages/ai-parrot/src/parrot/` may import
  `parrot_tools` (the retry helpers of `parrot_tools/o365/delta.py` are *re-implemented*, not imported).
- Pydantic v2 models; Google-style docstrings and strict type hints on every function/class; `self.logger`
  (or a module `logger = logging.getLogger(__name__)`), never `print`; `black` line length 120; `ruff check` clean.
- **Never log** upload-session `uploadUrl`s, copy monitor URLs, `@microsoft.graph.downloadUrl`s, tokens or secrets.
- **Byte-identical files** (no edit, ever, in this feature): `packages/ai-parrot/src/parrot/interfaces/sharepoint.py`,
  `packages/ai-parrot/src/parrot/interfaces/o365.py`, `packages/ai-parrot-tools/src/parrot_tools/o365/delta.py`,
  `packages/ai-parrot-tools/src/parrot_tools/o365/bundle.py`, `packages/ai-parrot-tools/src/parrot_tools/o365/base.py`,
  and the `Delta*Args` / `Delta*Tool` class blocks inside `parrot_tools/o365/{sharepoint,onedrive}.py` (FEAT-539).
- Tests never construct a real `O365Client` / `SharepointClient` / `OneDriveClient` (their `__init__` builds an
  aioredis client, `o365.py:198-200`) — use the fakes of TASK-3748 and `GraphDriveFileManager.adopt_client`.
- Tests are async with `asyncio_mode = auto` (`pytest.ini:3`); the `live` marker is registered (`pytest.ini:6`).
- **Worktree testing**: the shared `.venv` is editable-installed against the MAIN checkout, so run
  `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src timeout -s KILL 600 pytest <file> -q`.
  Never `uv sync` inside a worktree.

---

## Implementation Blueprint

### Steps (in order)
1. Add the import.
2. Rewrite List (`_execute_graph_operation`, `_list_recursive`, new `_entry_dict`) and Search bodies.
3. Tests.

### `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -c 'from parrot.interfaces.onedrive import OneDriveClient' parrot_tools/o365/onedrive.py) — :18
# AFTER — insert below `from parrot.interfaces.onedrive import OneDriveClient`
from parrot.interfaces.file.onedrive import OneDriveFileManager
```

### `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` (MODIFY) — List
```python
# occurrences: 1 (verified: grep -c 'class ListOneDriveFilesTool(O365Tool):' parrot_tools/o365/onedrive.py) — :34
# FILL IN: disambiguate — REPLACE ListOneDriveFilesTool._execute_graph_operation (:61-99) and _list_recursive (:101-118):
    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """List OneDrive files through OneDriveFileManager (user_id or "me"; all pages)."""
        folder_path = kwargs.get("folder_path", "")
        recursive = kwargs.get("recursive", False)
        manager = OneDriveFileManager(user=kwargs.get("user_id") or "me", credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            self.logger.info(f"Listing OneDrive files in: {folder_path or 'root'}")
            if recursive:
                files = await self._list_recursive(manager, folder_path)
            else:
                files = [self._entry_dict(e) for e in await manager.list_entries(folder_path)]
            self.logger.info(f"Found {len(files)} items")
            return {"folder_path": folder_path or "root", "total_items": len(files), "files": files,
                    "recursive": recursive}
        except Exception as e:
            self.logger.error(f"Failed to list OneDrive files: {e}")
            raise
        finally:
            await manager.close()

    async def _list_recursive(self, manager: OneDriveFileManager, folder_path: str) -> List[Dict[str, Any]]:
        """Breadth-first listing of ``folder_path`` and every sub-folder (folders included, all pages)."""
        # FILL IN

    @staticmethod
    def _entry_dict(entry: Any) -> Dict[str, Any]:
        return {"name": entry.name, "id": entry.id, "webUrl": entry.web_url, "path": entry.path,
                "isFolder": entry.is_folder, "size": entry.size or 0,
                "modified": entry.modified_at.isoformat() if entry.modified_at else None}
```

### `packages/ai-parrot-tools/src/parrot_tools/o365/onedrive.py` (MODIFY) — Search
```python
# occurrences: 1 (verified: grep -c 'class SearchOneDriveFilesTool(O365Tool):' parrot_tools/o365/onedrive.py) — :133
# FILL IN: disambiguate — REPLACE SearchOneDriveFilesTool._execute_graph_operation (:158-191):
    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """Search OneDrive through OneDriveFileManager.find_entries (all pages; max_results after filtering)."""
        query = kwargs.get("query")
        max_results = min(kwargs.get("max_results", 20), 100)
        manager = OneDriveFileManager(user=kwargs.get("user_id") or "me", credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            self.logger.info(f"Searching OneDrive for: {query}")
            # FILL IN: find_entries(keywords=query); slice; ListOneDriveFilesTool._entry_dict for each (isFolder False)
            return {"query": query, "total_results": len(files), "files": files}
        except Exception as e:
            self.logger.error(f"Failed to search OneDrive: {e}")
            raise
        finally:
            await manager.close()
```

### `packages/ai-parrot-tools/tests/test_o365_onedrive_file_tools.py` (CREATE)
```python
"""FEAT-603 TASK-3763/3764 — OneDrive O365 tools keep their response shapes on top of OneDriveFileManager."""
import importlib.util
import pathlib

import pytest

from parrot_tools.o365.onedrive import ListOneDriveFilesTool, SearchOneDriveFilesTool

_FAKES = pathlib.Path(__file__).resolve().parents[2] / "ai-parrot" / "tests" / "interfaces" / "_graph_fakes.py"
_spec = importlib.util.spec_from_file_location("feat603_graph_fakes", _FAKES)
fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fakes)

FILE_KEYS = {"name", "id", "webUrl", "path", "isFolder", "size", "modified"}


@pytest.fixture
def fake():
    # FILL IN: me drive "drive-me" with Documents/Projects/plan.docx, Documents/budget.xlsx; user drive "drive-u"; page_size=2


async def test_list_onedrive_files_me_delegated_shape(fake):
    # FILL IN: keys {"folder_path","total_items","files","recursive"}; each file FILE_KEYS; folder_path "" -> "root"


async def test_list_onedrive_files_user_id_app_only(fake):
    # FILL IN: app-only client + user_id="u@t.com" -> lists drive-u


async def test_list_onedrive_me_under_app_only_raises(fake):
    # FILL IN: RuntimeError mentioning delegated authentication


async def test_search_onedrive_files_shape_and_max_results(fake):
    # FILL IN
```

### FILL IN checklist
- [ ] `_list_recursive`; Search body
- [ ] test bodies

---

## Acceptance Criteria

- [ ] List/Search keep names, args and response shapes, including camelCase file keys (spec AC13).
- [ ] `user_id` selects the drive; default `"me"`; app-only + `"me"` fails with the explicit message.
- [ ] Every page is read (S4); the tool's client is adopted, not re-authenticated or closed (S1).
- [ ] `DeltaOneDriveFiles*` blocks byte-identical; `test_o365_delta_tools.py` passes.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/test_o365_onedrive_file_tools.py -q`
- `pytest packages/ai-parrot-tools/tests/test_o365_delta_tools.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_list_onedrive_files_me_delegated_shape` | AC13 shape |
| `test_list_onedrive_files_user_id_app_only` / `test_list_onedrive_me_under_app_only_raises` | user targeting |
| `test_search_onedrive_files_shape_and_max_results` | AC13, S4 |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** `sdd/specs/sharepoint-filemanager.spec.md` (§2, the §3 module named in Context, §6, §7).
2. **Check dependencies** — every `Depends-on` task must be `done` in `sdd/tasks/index/sharepoint-filemanager.json`.
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still resolves (`grep` or `read` the source).
   - Re-run the `grep -c` of every MODIFY anchor in the blueprint; a changed count means the anchor moved —
     re-locate it; a count of `0` means STOP and report drift.
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists.
4. **Update status** in `sdd/tasks/index/sharepoint-filemanager.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker, and never
   change a signature, class name or file path the blueprint fixes.
6. **Verify** every acceptance criterion and run every Validation Command (plus `ruff check` on touched files).
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
