# TASK-3760: FileManagerTool — operation find / batch_upload / batch_download + drive-relative storage paths

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3759
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 6** (single-tool half), AC12. The legacy single-tool API (`FileManagerTool`, one `operation` field)
gets the same three operations as the toolkit. The tool's handlers apply the same rules as TASK-3759's toolkit methods
(same manager calls, same pre-flight checks, same result shapes). `FileManagerTool` does not inherit from the toolkit, so
the rules are re-expressed here rather than shared; the tests in `test_filemanager_batch_ops.py` assert both classes
produce identical shapes.

Same task-time finding as TASK-3759: `FileManagerTool` also resolves *storage* paths with `_resolve_output_path`
(`:322`, `:360`, `:479`); add the tool-side `_storage_path` and swap those three sites so SharePoint/OneDrive paths stay
drive-relative. Record under "Deviations from spec".

Third and last edit to `parrot/tools/filemanager.py` (after TASK-3758, TASK-3759).

---

## Scope

- `FileManagerToolArgs`: extend the `operation` literal and its description; add `keywords`, `extension`, `prefix`, `items`.
- `FileManagerTool.__init__`: add the three ops to the default `allowed_operations` set.
- `FileManagerTool`: add `_storage_path`, swap the three storage call sites, add three `elif` branches in `_execute`, and
  add `_find_files`, `_batch_upload`, `_batch_download`.
- Append tool tests to `test_filemanager_batch_ops.py`.

**NOT in scope**: the toolkit (done in TASK-3759).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | tool args, dispatch, handlers, `_storage_path` |
| `packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` | MODIFY | append tool tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3` (line numbers are pre-TASK-3758/3759; re-grep before editing).

### Verified Imports
```python
from parrot.interfaces.file.batch import BatchItemResult, BatchSummary   # already imported by TASK-3759
from parrot.tools.filemanager import FileManagerTool                      # verified: parrot/tools/filemanager.py:140
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/filemanager.py
class FileManagerToolArgs(AbstractToolArgsSchema):         # :65
    operation: Literal["list", "upload", "download", "copy", "delete",
                       "exists", "get_url", "get_metadata", "create"] = Field(..., description=(... "- 'create': Create a new file with content"))   # :72-89 (last option line :87)
    expiry_seconds: Optional[int] = Field(3600, description="URL expiry time in seconds (default: 3600 = 1 hour)")   # :134-137 (last field)
class FileManagerTool(AbstractTool):                       # :140
    def __init__(...)                                      # :172 — self.allowed_operations = allowed_operations or {"list", ..., "create"} (:199-202)
    def _check_operation(self, operation: str)             # :240
    def _check_file_size(self, size: int)                  # :248
    def _resolve_output_path(self, path=None) -> str       # :256
    async def _execute(self, **kwargs) -> ToolResult       # :266 — `elif operation == "create":` (:291) then `result = await self._create_file(args)`
    async def _list_files(self, args)                      # :320 — storage path :322
    async def _upload_file(self, args)                     # :345 — storage dest :360
    async def _create_file(self, args)                     # :468 — storage dest :479; last method of the class (ends :493)
# Toolkit rules to mirror (TASK-3759): find -> manager.find_files(keywords, extension, prefix); batch -> native
#   upload_files/download_files when hasattr, else looped upload_file/download_file; BatchSummary.from_items(...).model_dump(mode="json")
```

### Does NOT Exist
- ~~`FileManagerToolArgs.keywords` / `.extension` / `.prefix` / `.items`~~ — added by this task.
- ~~`FileManagerTool._storage_path`~~ — added by this task (the toolkit has its own from TASK-3759).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/filemanager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerToolArgs",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerTool",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerTool._execute"
  ]
}
```

---

## Implementation Notes

- New arg fields (spec §3 M6): `keywords: Optional[Union[str, List[str]]]` ("find: substrings that must all appear in the
  filename"), `extension: Optional[str]` ("find: file extension filter, e.g. '.csv'"), `prefix: Optional[str]` ("find:
  restrict the search to this path prefix"), `items: Optional[List[Dict[str, str]]]` ("batch_*: list of {'source': ...,
  'destination': ...}").
- `_batch_upload` / `_batch_download` require `items` (missing → `ValueError`, which `_execute` turns into
  `ToolResult(success=False, ...)` like every other handler). Per-item failures never fail the tool call.
- `_find_files` returns the same `{"files": [...], "count": n}` shape as the toolkit.
- The `_storage_path` body is identical to the toolkit's (TASK-3759) — duplicated deliberately because the two classes
  are independent (`FileManagerTool` does not inherit from the toolkit).

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
1. Args: literal, description, fields.
2. `__init__` default `allowed_operations`.
3. `_storage_path` + three call-site swaps; dispatch; handlers.
4. Tests.

### `packages/ai-parrot/src/parrot/tools/filemanager.py` (MODIFY) — args
```python
# occurrences: 2 (verified: grep -c '        "exists", "get_url", "get_metadata", "create"' parrot/tools/filemanager.py) — :74 (args literal), :201 (__init__ default)
# FILL IN: disambiguate — in FileManagerToolArgs (the occurrence directly below `    operation: Literal[`) REPLACE the line with:
        "exists", "get_url", "get_metadata", "create", "find", "batch_upload", "batch_download"
#          and in FileManagerTool.__init__ (the occurrence inside `self.allowed_operations = allowed_operations or {`) REPLACE with:
            "exists", "get_url", "get_metadata", "create", "find", "batch_upload", "batch_download"

# occurrences: 1 (verified: grep -c "            \"- 'create': Create a new file with content\"" parrot/tools/filemanager.py) — :87
# REPLACE that line with:
            "- 'create': Create a new file with content\n"
            "- 'find': Find files by keywords / extension / prefix\n"
            "- 'batch_upload': Upload many local files (items=[{source, destination}])\n"
            "- 'batch_download': Download many files (items=[{source, destination}])"

# occurrences: 1 (verified: grep -c '        description="URL expiry time in seconds (default: 3600 = 1 hour)"') — :136
# AFTER — insert below the closing `    )` of the expiry_seconds Field (:137)

    # find / batch operations (FEAT-603)
    keywords: Optional[Union[str, List[str]]] = Field(
        None, description="find: substrings that must all appear in the filename"
    )
    extension: Optional[str] = Field(None, description="find: file extension filter, e.g. '.csv'")
    prefix: Optional[str] = Field(None, description="find: restrict the search to this path prefix")
    items: Optional[List[Dict[str, str]]] = Field(
        None, description="batch_*: list of {'source': ..., 'destination': ...}"
    )
```

### `packages/ai-parrot/src/parrot/tools/filemanager.py` (MODIFY) — `_storage_path`, call sites, dispatch
```python
# occurrences: 1 (verified: grep -c '    def _check_operation(self, operation: str):' parrot/tools/filemanager.py) — :240
# BEFORE — insert above `    def _check_operation(self, operation: str):` (FileManagerTool)
    _DRIVE_RELATIVE_BACKENDS = frozenset({"sharepoint", "onedrive"})

    def _storage_path(self, path: Optional[str]) -> str:
        """Storage-side path: unchanged (drive-relative) for Graph backends, else ``_resolve_output_path`` (unchanged)."""
        if self.manager_type in self._DRIVE_RELATIVE_BACKENDS:
            return (path or "").strip()
        return self._resolve_output_path(path) if path else ""

# FILL IN: disambiguate — swap ONLY inside FileManagerTool (the toolkit's were swapped by TASK-3759):
#   _list_files   :322  `path = self._resolve_output_path(args.path) if args.path else ""` -> `path = self._storage_path(args.path)`
#   _upload_file  :360  `dest = self._resolve_output_path(dest)` (now the only remaining occurrence) -> `dest = self._storage_path(dest)`
#   _create_file  :479  `dest = self._resolve_output_path(args.path)` -> `dest = self._storage_path(args.path)`

# occurrences: 1 (verified: grep -c '            elif operation == "create":' parrot/tools/filemanager.py) — :291
# AFTER — insert below `                result = await self._create_file(args)` (the line after the anchor)
            elif operation == "find":
                result = await self._find_files(args)
            elif operation == "batch_upload":
                result = await self._batch_upload(args)
            elif operation == "batch_download":
                result = await self._batch_download(args)
```

### `packages/ai-parrot/src/parrot/tools/filemanager.py` (MODIFY) — handlers
```python
# occurrences: 1 (verified: grep -cF '    async def _create_file(self, args: FileManagerToolArgs) -> Dict[str, Any]:') — :468
# AFTER — insert after the END of `_create_file` (its `return {...}` ending :493), before the
#         "# FileManagerToolkit — preferred API" comment block
    async def _find_files(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Find files by keywords / extension / prefix (server-side search on SharePoint / OneDrive)."""
        # FILL IN: same rule as FileManagerToolkit.find_files (TASK-3759)

    async def _batch_upload(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Upload ``args.items``; per-item results, never fails the call for one item."""
        # FILL IN: same rule as FileManagerToolkit.batch_upload (TASK-3759); items required

    async def _batch_download(self, args: FileManagerToolArgs) -> Dict[str, Any]:
        """Download ``args.items``; per-item results, never fails the call for one item."""
        # FILL IN: same rule as FileManagerToolkit.batch_download (TASK-3759); items required
```

### `packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` (MODIFY)
```python
# AFTER — append at end of file
from parrot.tools.filemanager import FileManagerTool


async def test_tool_find_batch_ops_dispatch(tmp_path):
    # FILL IN: FileManagerTool(manager_type="temp"); operation "find" / "batch_upload" / "batch_download" succeed;
    #          ToolResult.success True; batch result has the BatchSummary keys


async def test_tool_batch_requires_items():
    # FILL IN: operation="batch_upload" without items -> ToolResult(success=False)


def test_tool_default_allowed_operations_include_new_ops():
    # FILL IN


def test_tool_storage_path_is_drive_relative_for_graph():
    # FILL IN: manager_type "onedrive" with the manager stubbed -> _storage_path("x/y") == "x/y"
```

### FILL IN checklist
- [ ] the two disambiguated literal edits
- [ ] three call-site swaps inside FileManagerTool
- [ ] `_find_files`, `_batch_upload`, `_batch_download`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `FileManagerToolArgs.operation` accepts `find`, `batch_upload`, `batch_download`; the tool dispatches them and
      allows them by default (spec AC12).
- [ ] Batch/find behave exactly like the toolkit's (same result shapes); per-item failures never fail the call.
- [ ] SharePoint/OneDrive storage paths are drive-relative in the tool too; other backends unchanged.
- [ ] `tests/tools/test_filemanager_toolkit.py` and `packages/ai-parrot/tests/interfaces/test_file_shim.py` still pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py -q`
- `pytest tests/tools/test_filemanager_toolkit.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_file_shim.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_tool_find_batch_ops_dispatch` | AC12 dispatch |
| `test_tool_batch_requires_items` | validation |
| `test_tool_default_allowed_operations_include_new_ops` | defaults |
| `test_tool_storage_path_is_drive_relative_for_graph` | path fix |

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
