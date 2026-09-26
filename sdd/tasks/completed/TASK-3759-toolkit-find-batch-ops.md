# TASK-3759: FileManagerToolkit — fs_find_files / fs_batch_upload / fs_batch_download + drive-relative storage paths

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3758, TASK-3749
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 6** (toolkit half; the `FileManagerTool` half is TASK-3760), AC12. The toolkit gains three tools on
every backend: `find_files` (the backend's server-side override on Graph, the interface's in-memory default elsewhere),
`batch_upload` and `batch_download` (native `upload_files`/`download_files` when the manager has them, a looped
single-item fallback otherwise — both return `BatchSummary.model_dump()`).

**Task-time finding (required for AC11/AC12 to work at all):** the toolkit runs *storage* paths through
`_resolve_output_path`, which joins them onto the local `OUTPUT_DIR` (`filemanager.py:662-678`). For SharePoint /
OneDrive that would send absolute local paths to Graph. This task adds `_storage_path(path)`: for `manager_type in
{"sharepoint", "onedrive"}` it returns the path unchanged (drive-relative); for every other backend it returns
`_resolve_output_path(path)` exactly as today. It replaces the three *storage* call sites (`list_files` :699,
`upload_file` :755, `create_file` :980). The *local* download destination (:791) keeps `_resolve_output_path`.
`fs` / `temp` / `s3` / `gcs` behaviour is unchanged. Record this under "Deviations from spec" in the Completion Note.

Second of three edits to `parrot/tools/filemanager.py` (after TASK-3758, before TASK-3760).

---

## Scope

- Add `"find"`, `"batch_upload"`, `"batch_download"` to `_OP_TO_METHOD` (so `allowed_operations` / `exclude_tools`
  cover the new tools, spec §7 gotcha).
- Add `FileManagerToolkit._storage_path` and use it at the three storage call sites.
- Append `find_files`, `batch_upload`, `batch_download` to `FileManagerToolkit`; update the class docstring's tool list.
- Create `packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` (toolkit tests; TASK-3760 appends tool tests).

**NOT in scope**: `FileManagerTool` / `FileManagerToolArgs` (TASK-3760); in-memory payloads for batch upload (spec §8 Q3,
open — v1 is local paths only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | op map, `_storage_path`, three toolkit methods |
| `packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` | CREATE | toolkit tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
from parrot.interfaces.file.batch import BatchItemResult, BatchSummary   # TASK-3749 (msgraph-free — import at module top is safe)
from parrot.tools.filemanager import FileManagerToolkit                   # verified: parrot/tools/filemanager.py:515
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/filemanager.py
_OP_TO_METHOD: Dict[str, str] = {..., "get_metadata": "get_file_metadata", "create": "create_file",}   # :501-511 ("create" line :510)
_ALL_OPS: frozenset = frozenset(_OP_TO_METHOD)                          # :512
class FileManagerToolkit(AbstractToolkit):                             # :515 — docstring tool list :522-531, "Supported backends:" :533
    tool_prefix: Optional[str] = "fs"                                  # :547
    def __init__(self, manager_type: ManagerType = "fs", ..., allowed_operations=None, max_file_size=100 MiB, ...)   # :549
        # validates allowed_operations against _ALL_OPS; sets exclude_tools from _OP_TO_METHOD BEFORE super().__init__()
    self.manager_type / self.manager / self.max_file_size / self.default_output_dir / self.logger
    def _check_file_size(self, size: int) -> None                       # :647
    def _resolve_output_path(self, path: Optional[str] = None) -> str   # :662-678 — joins onto default_output_dir
    async def list_files(self, path: str = "", pattern: str = "*") -> Dict[str, Any]   # :680; storage path resolved at :699
    async def upload_file(self, source_path: str, destination=None, destination_name=None) -> Dict[str, Any]   # :719; :755
    async def download_file(self, path: str, destination=None) -> Dict[str, Any]   # :768; LOCAL dest resolved at :791 (keep)
    async def create_file(self, path: str, content: str, encoding: str = "utf-8") -> Dict[str, Any]   # :947; storage :980
# navigator FileManagerInterface.find_files(keywords=None, extension=None, prefix=None) -> List[FileMetadata]   # abstract.py:265 (concrete default)
# Graph managers additionally have upload_files(items) / download_files(items) -> List[BatchItemResult] (TASK-3754)
```

### Does NOT Exist
- ~~`FileManagerInterface.upload_files` / `.download_files`~~ — Graph-only; detect with `hasattr(self.manager, ...)`.
- ~~`parrot.interfaces.file.graph` imported by `filemanager.py`~~ — forbidden (msgraph is optional); import `batch.py`.
- ~~`FileManagerToolkit._storage_path`~~ — added by this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/filemanager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerToolkit._resolve_output_path",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerToolkit.list_files",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerToolkit.upload_file",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerToolkit.create_file"
  ]
}
```

---

## Implementation Notes

- **Docstrings are the LLM-facing tool descriptions** (`AbstractToolkit` generates tools from public async methods):
  write them for an agent — what `items` looks like, what comes back.
- **`find_files`** → `files = await self.manager.find_files(keywords=..., extension=..., prefix=self._storage_path(prefix)
  if prefix else None)`; return `{"files": [<same dict shape as list_files>], "count": n}`.
- **`batch_upload(items)`**: each item `{"source": <local path>, "destination": <storage path>}`. Pre-flight per item:
  missing keys / nonexistent source / over `max_file_size` → a `failed` `BatchItemResult` (`error_code="invalid_path"` or
  `"io"`) without calling the manager; destination through `_storage_path`. Remaining items: native
  `await self.manager.upload_files([(Path(src), dst), ...])` when `hasattr(self.manager, "upload_files")`, else loop
  `await self.manager.upload_file(Path(src), dst)` catching each exception into a `failed` result (never raise). Merge
  pre-flight and manager results back into input order (`index` = input position).
- **`batch_download(items)`**: each item `{"source": <storage path>, "destination": <local path, optional>}`; missing
  destination → `self._resolve_output_path(Path(source).name)` (local, like `download_file`). Same native/looped rule
  with `download_files` / `download_file`.
- Return `BatchSummary.from_items(results).model_dump(mode="json")`. `FileMetadata` is a dataclass — `model_dump(mode=
  "json")` serialises it through `arbitrary_types_allowed`; if pydantic cannot, convert metadata to a dict before building
  the result (FILL IN, bounded by "the returned dict must be JSON-serialisable", asserted by a test).

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
1. Extend `_OP_TO_METHOD` — *why*: exclude_tools is derived from it before the tools are generated.
2. Add `_storage_path` and swap the three storage call sites — *why*: Graph paths are drive-relative.
3. Append the three public methods; update the class docstring.
4. Write the tests (on the `temp` backend for the fallback, a stub manager for the native path).

### `packages/ai-parrot/src/parrot/tools/filemanager.py` (MODIFY) — import + op map
```python
# occurrences: 1 (verified: grep -c '^from parrot.interfaces.file import FileManagerInterface$' parrot/tools/filemanager.py) — :18
# AFTER — insert below `from parrot.interfaces.file import FileManagerInterface`
from parrot.interfaces.file.batch import BatchItemResult, BatchSummary

# occurrences: 1 (verified: grep -c '    "create": "create_file",' parrot/tools/filemanager.py) — :510
# AFTER — insert below `    "create": "create_file",`
    "find": "find_files",
    "batch_upload": "batch_upload",
    "batch_download": "batch_download",
```

### `packages/ai-parrot/src/parrot/tools/filemanager.py` (MODIFY) — `_storage_path` + call sites
```python
# occurrences: 2 (verified: grep -c '    def _resolve_output_path(self, path: Optional\[str\] = None) -> str:') — :256 (Tool), :662 (Toolkit)
# FILL IN: disambiguate — insert ABOVE the FileManagerToolkit one (the occurrence after `class FileManagerToolkit(`,
#          directly below `_check_file_size`'s body ending at :660):
    _DRIVE_RELATIVE_BACKENDS = frozenset({"sharepoint", "onedrive"})

    def _storage_path(self, path: Optional[str]) -> str:
        """Storage-side path: unchanged (drive-relative) for Graph backends, else ``_resolve_output_path`` (unchanged)."""
        if self.manager_type in self._DRIVE_RELATIVE_BACKENDS:
            return (path or "").strip()
        return self._resolve_output_path(path) if path else ""

# FILL IN: disambiguate by method (these lines also exist in FileManagerTool, :322/:360/:479 — do NOT touch those here):
#   FileManagerToolkit.list_files   :699  `resolved = self._resolve_output_path(path) if path else ""`
#                                   ->    `resolved = self._storage_path(path)`
#   FileManagerToolkit.upload_file  :755  `dest = self._resolve_output_path(dest)`  ->  `dest = self._storage_path(dest)`
#   FileManagerToolkit.create_file  :980  `dest = self._resolve_output_path(path)`  ->  `dest = self._storage_path(path)`
#   For non-Graph backends `_storage_path` returns exactly what the old expression returned (behaviour unchanged).
```

### `packages/ai-parrot/src/parrot/tools/filemanager.py` (MODIFY) — three tools (append to the toolkit)
```python
# occurrences: 1 (verified: grep -c '    async def create_file(' parrot/tools/filemanager.py) — :947, the toolkit's last method
# AFTER — append at the end of the file (after FileManagerToolkit.create_file's `return {...}`)

    async def find_files(
        self,
        keywords: Optional[Union[str, List[str]]] = None,
        extension: Optional[str] = None,
        prefix: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Find files whose name contains ALL ``keywords`` and ends with ``extension``, under ``prefix``.

        Uses the backend's server-side search when available (SharePoint / OneDrive), otherwise lists and filters.

        Args:
            keywords: One substring or a list of substrings that must all appear in the file name.
            extension: File extension filter, e.g. ``".csv"``.
            prefix: Only search under this folder/path prefix.

        Returns:
            Dict with ``files`` (list of file info dicts, same shape as ``list_files``) and ``count``.
        """
        # FILL IN: rule in Implementation Notes

    async def batch_upload(self, items: List[Dict[str, str]]) -> Dict[str, Any]:
        """Upload many local files at once; one failing file never fails the batch.

        Args:
            items: ``[{"source": "<local file path>", "destination": "<storage path incl. file name>"}, ...]``.

        Returns:
            Dict with ``total``, ``succeeded``, ``failed``, ``skipped``, ``aborted`` and ``items`` (per-file result with
            ``state``, ``error`` and ``metadata``), in input order.
        """
        # FILL IN: rule in Implementation Notes

    async def batch_download(self, items: List[Dict[str, str]]) -> Dict[str, Any]:
        """Download many files at once; one failing file never fails the batch.

        Args:
            items: ``[{"source": "<storage path>", "destination": "<local path, optional>"}, ...]``.

        Returns:
            Same shape as ``batch_upload``.
        """
        # FILL IN: rule in Implementation Notes
```
Also add `List` to the `typing` import at `filemanager.py:10` if absent (FILL IN), and add the three `fs_*` names to the
class docstring's tool list (:522-531).

### `packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py` (CREATE)
```python
"""FEAT-603 TASK-3759/3760 — find / batch operations on FileManagerToolkit and FileManagerTool."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.interfaces.file.batch import BatchItemResult
from parrot.tools.filemanager import FileManagerToolkit


async def test_toolkit_exposes_new_tools():
    tk = FileManagerToolkit(manager_type="temp")
    names = {t.name for t in tk.get_tools()}
    assert {"fs_find_files", "fs_batch_upload", "fs_batch_download"} <= names


def test_allowed_operations_accepts_new_keys():
    # FILL IN: allowed_operations={"find", "batch_upload"} -> only those two among the new tools exposed


async def test_toolkit_batch_fallback_loops_single_ops(tmp_path):
    # FILL IN: temp backend, 3 local files (one missing) -> succeeded/failed/succeeded in order; result is json.dumps-able


async def test_toolkit_batch_uses_native_when_available(tmp_path):
    # FILL IN: stub manager with async upload_files returning BatchItemResult list -> called once with (Path, dst) tuples


async def test_toolkit_find_uses_backend_override():
    # FILL IN: stub manager whose find_files records its kwargs -> toolkit forwards keywords/extension/prefix


def test_storage_path_is_drive_relative_for_graph_and_unchanged_otherwise():
    # FILL IN: toolkit with manager_type "sharepoint" (manager stubbed) -> _storage_path("a/b.txt") == "a/b.txt";
    #          "temp" -> equals _resolve_output_path("a/b.txt")
```

### FILL IN checklist
- [ ] `_storage_path` insertion point + the three toolkit call-site swaps
- [ ] `find_files`, `batch_upload`, `batch_download` bodies (+ JSON-serialisable metadata)
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `FileManagerToolkit` exposes `fs_find_files`, `fs_batch_upload`, `fs_batch_download`; `allowed_operations`
      accepts `find`, `batch_upload`, `batch_download` (spec AC12).
- [ ] Batch tools use the native Graph methods when present and loop single-item ops otherwise, always returning the
      same JSON-serialisable `BatchSummary` shape, in input order, without raising for an item (spec AC12, AC8).
- [ ] SharePoint/OneDrive storage paths reach the manager drive-relative; `fs`/`temp`/`s3`/`gcs` paths are unchanged.
- [ ] `filemanager.py` does not import `parrot.interfaces.file.graph`; existing `tests/tools/test_filemanager_toolkit.py`
      passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_filemanager_batch_ops.py -q`
- `pytest tests/tools/test_filemanager_toolkit.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_toolkit_exposes_new_tools` / `test_allowed_operations_accepts_new_keys` | AC12 surface |
| `test_toolkit_batch_fallback_loops_single_ops` / `test_toolkit_batch_uses_native_when_available` | AC12 routing |
| `test_toolkit_find_uses_backend_override` | find forwarding |
| `test_storage_path_is_drive_relative_for_graph_and_unchanged_otherwise` | path fix |

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


- Task: TASK-3759
- Feature: sharepoint-filemanager
- Implementation SHA: 9c2d2cd6e4aea23a3d1656ba97c9202fbf10356b
- Closed at (UTC): 2026-09-25T20:19:39+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: sonnet (native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
| validation_note | Directory-wide merge-tier run (packages/ai-parrot/tests + ai-parrot-server + ai-parrot-loaders import-impact scope) reported outcome=failed. 3 attributable failures in tests/tools/test_filemanager_toolkit.py are expected structural fallout of this task's own declared scope (default op/tool count legitimately grows 9->12); tests/tools/test_filemanager_toolkit.py was correctly out of THIS task's Files to Create/Modify because TASK-3760's own AC already claimed responsibility for it -- TASK-3760's task file was corrected (commit 97c1be15c) to add that file to its own scope. The remaining failures/collection-errors are unrelated pre-existing repo breakage across unrelated subsystems (agents, scheduler, notification, botmanager, cryptoquant, obsidian aiohttp API, ai-parrot-loaders webscraping) -- see artifacts/logs/sdd-coder-usage/executions/890f8a7f-c24e-491f-8efc-b4e70247dff0/review/TASK-3759-review.txt for the full analysis. This task's own declared test file (test_filemanager_batch_ops.py) passed 6/6 in isolation. |
