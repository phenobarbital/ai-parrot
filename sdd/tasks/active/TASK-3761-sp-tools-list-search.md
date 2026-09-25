# TASK-3761: SharePoint O365 tools (List, Search) delegate to SharePointFileManager

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3756, TASK-3751
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 7** (first half; Download/Upload are TASK-3762), AC13, design research **S1** (reuse the tool's cached
authenticated client via `adopt_client`, one authentication), **S4** (pagination — the current List tool reads one
page, `parrot_tools/o365/sharepoint.py:105-123`) and **S8** (library-relative tool paths == drive-relative manager paths
with `prefix=""`, so response `path` values do not change).

`O365Tool._get_client()` hands `_execute_graph_operation` a plain `O365Client` (`base.py:148`), yet these tools are
typed `client: SharepointClient` and call `SharepointClient`-only methods — they never actually received one. Routing
through the manager fixes that: `adopt_client` wraps the plain client into a `SharepointClient` that shares its
credential and Graph client.

The legacy `client.credentials["tenant"] = site` quirk (`:91`, `:259`) is **not** replicated (spec §7).

---

## Scope

- In `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py`: add the manager import; rewrite
  `ListSharePointFilesTool._execute_graph_operation` and `_list_recursive`, and
  `SearchSharePointFilesTool._execute_graph_operation`, keeping names, descriptions, `args_schema` and response keys.
- Create `packages/ai-parrot-tools/tests/test_o365_sharepoint_file_tools.py` (TASK-3762 appends).

**NOT in scope**: Download/Upload tools (TASK-3762); `DeltaSharePointFilesArgs` / `DeltaSharePointFilesTool` and their
imports (`DEFAULT_MAX_PAGES`, `DriveDeltaHelper`, `O365Client`) — byte-identical (FEAT-539); `base.py`, `bundle.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` | MODIFY | List + Search bodies via the manager |
| `packages/ai-parrot-tools/tests/test_o365_sharepoint_file_tools.py` | CREATE | response-shape tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
from parrot.interfaces.file.sharepoint import SharePointFileManager   # TASK-3756
from parrot.interfaces.o365 import O365Client                         # already imported: o365/sharepoint.py:17
from parrot_tools.o365.sharepoint import ListSharePointFilesTool, SearchSharePointFilesTool   # tests
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py
from parrot.interfaces.sharepoint import SharepointClient                   # :18 (keep — still used by type hints / Download+Upload until 3762)
class ListSharePointFilesArgs(O365ToolArgsSchema): site, library="Documents", folder_path="", recursive=False   # :25-33
class ListSharePointFilesTool(O365Tool):                                    # :36 — name "list_sharepoint_files"
    async def _execute_graph_operation(self, client: SharepointClient, **kwargs) -> Dict[str, Any]   # :72-153
        # returns {"site","library","folder_path","total_items","files":[{"name","path","is_folder","size","modified",
        #          "web_url","id"}],"recursive"}   (:126-146); "modified" is an ISO string or None
    async def _list_recursive(self, client, drive_id, folder_id, base_path) -> List[Dict[str, Any]]   # :155-185 (folders + descendants)
class SearchSharePointFilesArgs(O365ToolArgsSchema): site, query, library="Documents", folder_path="", file_extension=None, max_results=20   # :193-201
class SearchSharePointFilesTool(O365Tool):                                  # :204 — name "search_sharepoint_files"
    async def _execute_graph_operation(self, client: SharepointClient, **kwargs) -> Dict[str, Any]   # :239-305
        # max_results = min(kwargs.get("max_results", 20), 100); returns {"site","query","library","folder_path",
        #   "file_extension","total_results","files":[{"name","path","size","modified","web_url","id"}]}   (:282-301)
# packages/ai-parrot-tools/src/parrot_tools/o365/base.py (unchanged)
class O365Tool(AbstractTool):  credentials (self.credentials), logger, _get_client() -> O365Client (:148), cleanup()
# From TASK-3749..3751/3756: SharePointFileManager(site, library, *, tenant=None, credentials=..., prefix=""),
#   adopt_client(client), list_entries(path) -> List[DriveEntry], find_entries(keywords, extension, prefix) -> List[DriveEntry],
#   close(); DriveEntry(id, name, path, is_folder, size, modified_at, web_url, content_type)
```

### Does NOT Exist
- ~~`SharepointClient` instances from `O365Tool._get_client`~~ — it returns a plain `O365Client` (`base.py:148`).
- ~~`FileMetadata.id`~~ — use `DriveEntry` (`list_entries` / `find_entries`) where the response needs `id`.
- ~~`packages/ai-parrot-tools/tests/conftest.py`~~ — none; fakes are loaded by file path (Implementation Notes).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/test_o365_sharepoint_file_tools.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py#ListSharePointFilesTool",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py#ListSharePointFilesTool._execute_graph_operation",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py#ListSharePointFilesTool._list_recursive",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py#SearchSharePointFilesTool",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py#SearchSharePointFilesTool._execute_graph_operation",
    "sym:packages/ai-parrot-tools/src/parrot_tools/o365/base.py#O365Tool._get_client"
  ]
}
```

---

## Implementation Notes

- **Manager per call**: `manager = SharePointFileManager(site=site, library=library, credentials=dict(self.credentials))`
  then `manager.adopt_client(client)`; wrap the work in `try: ... finally: await manager.close()` (closes only the
  wrapper the manager built — never the tool's cached client).
- **List**: non-recursive → `await manager.list_entries(folder_path)`; recursive → breadth-first over folders using
  `list_entries(entry.path)` (all pages each, S4). Each file dict: `{"name", "path", "is_folder", "size",
  "modified": modified_at.isoformat() or None, "web_url", "id"}` — `path` is the entry's drive-relative path.
- **Search**: `extension = f".{ext.lstrip('.')}"` when `file_extension` is given; `entries = await
  manager.find_entries(keywords=query, extension=extension, prefix=folder_path or None)`; slice to `max_results`
  AFTER filtering (S4); dict shape as today (no `is_folder`).
- Keep each method's `self.logger.info(...)` lines (no URLs); keep the `except Exception: self.logger.error(...); raise`
  pattern so `O365Tool._execute` still reports failures.
- **Tests load the fakes by path** (they live in another distribution's test tree):
  ```python
  import importlib.util, pathlib
  _FAKES = pathlib.Path(__file__).resolve().parents[2] / "ai-parrot" / "tests" / "interfaces" / "_graph_fakes.py"
  _spec = importlib.util.spec_from_file_location("feat603_graph_fakes", _FAKES)
  fakes = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fakes)
  ```
  (`_graph_fakes.py` uses only absolute imports.) Call `tool._execute_graph_operation(client, **kwargs)` directly with
  `client = fakes.make_sharepoint_client(fake, drive_id="drive-1")`; build tools with `ListSharePointFilesTool(
  credentials={})`.

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
2. Rewrite the two List methods and the Search method bodies — signatures and docstrings stay (only `client`'s type hint
   widens to `O365Client`, which is what `_get_client` returns).
3. Write the tests.

### `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` (MODIFY) — import
```python
# occurrences: 1 (verified: grep -c 'from parrot.interfaces.sharepoint import SharepointClient' parrot_tools/o365/sharepoint.py) — :18
# AFTER — insert below `from parrot.interfaces.sharepoint import SharepointClient`
from parrot.interfaces.file.sharepoint import SharePointFileManager
```

### `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` (MODIFY) — List
```python
# occurrences: 1 (verified: grep -c 'class ListSharePointFilesTool(O365Tool):' parrot_tools/o365/sharepoint.py) — :36
# FILL IN: disambiguate — REPLACE the bodies of ListSharePointFilesTool._execute_graph_operation (:72-153) and
#          ListSharePointFilesTool._list_recursive (:155-185) with the versions below (class header, name, description,
#          args_schema and docstring examples :36-70 unchanged):
    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """List SharePoint files through SharePointFileManager (one authentication, all pages)."""
        site = kwargs.get("site")
        library = kwargs.get("library", "Documents")
        folder_path = kwargs.get("folder_path", "")
        recursive = kwargs.get("recursive", False)
        manager = SharePointFileManager(site=site, library=library, credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            self.logger.info(f"Listing files in: {site}/{library}/{folder_path}".rstrip("/"))
            if recursive:
                files = await self._list_recursive(manager, folder_path)
            else:
                files = [self._entry_dict(e) for e in await manager.list_entries(folder_path)]
            self.logger.info(f"Found {len(files)} items")
            return {"site": site, "library": library, "folder_path": folder_path, "total_items": len(files),
                    "files": files, "recursive": recursive}
        except Exception as e:
            self.logger.error(f"Failed to list SharePoint files: {e}")
            raise
        finally:
            await manager.close()

    async def _list_recursive(self, manager: SharePointFileManager, base_path: str) -> List[Dict[str, Any]]:
        """Breadth-first listing of ``base_path`` and every sub-folder (folders included, all pages)."""
        # FILL IN: queue of folder paths; manager.list_entries(p); append _entry_dict(e); enqueue e.path when e.is_folder

    @staticmethod
    def _entry_dict(entry: Any) -> Dict[str, Any]:
        return {"name": entry.name, "path": entry.path, "is_folder": entry.is_folder, "size": entry.size or 0,
                "modified": entry.modified_at.isoformat() if entry.modified_at else None,
                "web_url": entry.web_url, "id": entry.id}
```

### `packages/ai-parrot-tools/src/parrot_tools/o365/sharepoint.py` (MODIFY) — Search
```python
# occurrences: 1 (verified: grep -c 'class SearchSharePointFilesTool(O365Tool):' parrot_tools/o365/sharepoint.py) — :204
# FILL IN: disambiguate — REPLACE the body of SearchSharePointFilesTool._execute_graph_operation (:239-305):
    async def _execute_graph_operation(self, client: O365Client, **kwargs) -> Dict[str, Any]:
        """Search SharePoint files through SharePointFileManager.find_entries (all pages; max_results after filtering)."""
        site = kwargs.get("site")
        query = kwargs.get("query")
        library = kwargs.get("library", "Documents")
        folder_path = kwargs.get("folder_path", "")
        file_extension = kwargs.get("file_extension")
        max_results = min(kwargs.get("max_results", 20), 100)
        manager = SharePointFileManager(site=site, library=library, credentials=dict(self.credentials or {}))
        manager.adopt_client(client)
        try:
            self.logger.info(f"Searching SharePoint for: {query}")
            # FILL IN: extension normalisation; find_entries; slice; dicts WITHOUT is_folder (today's shape)
            return {"site": site, "query": query, "library": library, "folder_path": folder_path,
                    "file_extension": file_extension, "total_results": len(files), "files": files}
        except Exception as e:
            self.logger.error(f"Failed to search SharePoint: {e}")
            raise
        finally:
            await manager.close()
```
**Why**: the two bodies are written out because the response dicts are the AC13 contract. `SharepointClient` stays
imported (TASK-3762 still references it until it rewrites Download/Upload).

### `packages/ai-parrot-tools/tests/test_o365_sharepoint_file_tools.py` (CREATE)
```python
"""FEAT-603 TASK-3761/3762 — SharePoint O365 tools keep their response shapes on top of SharePointFileManager."""
import importlib.util
import pathlib

import pytest

from parrot_tools.o365.sharepoint import ListSharePointFilesTool, SearchSharePointFilesTool

_FAKES = pathlib.Path(__file__).resolve().parents[2] / "ai-parrot" / "tests" / "interfaces" / "_graph_fakes.py"
_spec = importlib.util.spec_from_file_location("feat603_graph_fakes", _FAKES)
fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fakes)

LIST_KEYS = {"site", "library", "folder_path", "total_items", "files", "recursive"}
LIST_FILE_KEYS = {"name", "path", "is_folder", "size", "modified", "web_url", "id"}
SEARCH_KEYS = {"site", "query", "library", "folder_path", "file_extension", "total_results", "files"}
SEARCH_FILE_KEYS = {"name", "path", "size", "modified", "web_url", "id"}


@pytest.fixture
def fake():
    # FILL IN: FakeDrive with Reports/2025/q4.pdf, Reports/2025/q4.xlsx, Reports/notes.txt; page_size=2


async def test_list_sharepoint_files_tool_response_shape(fake):
    # FILL IN: exact key sets; folder entry has is_folder True; paths library-relative ("Reports/2025")


async def test_list_recursive_includes_descendants_all_pages(fake):
    # FILL IN


async def test_search_sharepoint_files_tool_response_shape_and_max_results(fake):
    # FILL IN: file_extension="pdf" -> only q4.pdf; max_results=1 applied after filtering


async def test_tools_do_not_close_the_adopted_client(fake):
    # FILL IN: after the call, the client passed in still has its _graph_client
```

### FILL IN checklist
- [ ] `_list_recursive` body
- [ ] Search extension normalisation / slicing / dicts
- [ ] test bodies

---

## Acceptance Criteria

- [ ] List and Search tools keep `name`, `description`, `args_schema` and return exactly the key sets above (spec AC13).
- [ ] Both read every page (S4); Search applies `max_results` after filtering.
- [ ] One authentication: the tool's client is adopted, not re-authenticated, and not closed by the manager (S1).
- [ ] The `DeltaSharePointFiles*` class blocks are byte-identical (`git diff` shows no hunk inside them);
      `packages/ai-parrot-tools/tests/test_o365_delta_tools.py` passes.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/test_o365_sharepoint_file_tools.py -q`
- `pytest packages/ai-parrot-tools/tests/test_o365_delta_tools.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_list_sharepoint_files_tool_response_shape` | AC13 keys, S8 paths |
| `test_list_recursive_includes_descendants_all_pages` | S4 |
| `test_search_sharepoint_files_tool_response_shape_and_max_results` | AC13, S4 |
| `test_tools_do_not_close_the_adopted_client` | S1 ownership |

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
