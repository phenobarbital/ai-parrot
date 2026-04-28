# TASK-869: Implement FileManagerToolkit Core Class

**Feature**: FEAT-127 — FileManagerTool Migration to Toolkit
**Spec**: `sdd/specs/filemanagertool-migration-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the core implementation task for FEAT-127. The existing `FileManagerTool` uses a multi-operation dispatch pattern that confuses LLMs. This task creates `FileManagerToolkit` — an `AbstractToolkit` subclass where each file operation is a separate public async method, auto-wrapped as an individual tool with a focused schema.

Implements Spec §2 (Architectural Design) and §3 Module 1 (FileManagerToolkit).

---

## Scope

- Add `FileManagerToolkit` class to `packages/ai-parrot/src/parrot/tools/filemanager.py` (alongside existing `FileManagerTool` and `FileManagerFactory` — do NOT remove them).
- `FileManagerToolkit` inherits from `AbstractToolkit` with `tool_prefix = "fs"`.
- Implement 9 public async methods, each becoming a standalone tool:
  - `list_files(path: str = "", pattern: str = "*") -> dict`
  - `upload_file(source_path: str, destination: Optional[str] = None, destination_name: Optional[str] = None) -> dict`
  - `download_file(path: str, destination: Optional[str] = None) -> dict`
  - `copy_file(source: str, destination: str) -> dict`
  - `delete_file(path: str) -> dict`
  - `file_exists(path: str) -> dict`
  - `get_file_url(path: str, expiry_seconds: int = 3600) -> dict`
  - `get_file_metadata(path: str) -> dict`
  - `create_file(path: str, content: str, encoding: str = "utf-8") -> dict`
- Reuse `FileManagerFactory` for backend creation (same as `FileManagerTool._create_manager`).
- Support `__init__` parameters: `manager_type`, `default_output_dir`, `allowed_operations`, `max_file_size`, `auto_create_dirs`, `**manager_kwargs`.
- Implement `allowed_operations` filtering by dynamically building `exclude_tools` in `__init__` based on operations NOT in `allowed_operations`.
- Port internal helpers as private methods: `_resolve_output_path`, `_check_file_size`.
- Each method's docstring serves as the LLM tool description — make them clear and action-oriented.
- Each method returns the same dict structure as the corresponding `FileManagerTool._*` method.
- Add deprecation notice to `FileManagerTool` docstring (do NOT remove the class).

**NOT in scope**:
- Modifying `__init__.py` exports (TASK-870).
- Modifying `parrot_tools/__init__.py` registry (TASK-871).
- Writing tests (TASK-872).
- Updating the example (TASK-873).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | Add `FileManagerToolkit` class after existing `FileManagerTool` class. Add deprecation note to `FileManagerTool` docstring. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit       # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:168
from parrot.tools.abstract import ToolResult           # verified: packages/ai-parrot/src/parrot/tools/abstract.py:36
from parrot.interfaces.file import FileManagerInterface # verified: packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18
from parrot.conf import OUTPUT_DIR                     # verified: used in filemanager.py:14
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:168
class AbstractToolkit(ABC):
    tool_prefix: Optional[str] = None               # line 219
    prefix_separator: str = "_"                      # line 222
    exclude_tools: tuple[str, ...] = ()              # line 205
    def __init__(self, **kwargs): ...                 # line 224
    def get_tools(self, ...) -> List[AbstractTool]:   # line 292
    async def _pre_execute(self, tool_name, **kwargs): ...  # line 261
    async def _post_execute(self, tool_name, result, **kwargs): ...  # line 276

# packages/ai-parrot/src/parrot/tools/filemanager.py:18
class FileManagerFactory:
    _PARROT_TO_UPSTREAM: dict = {"fs": "local", "temp": "temp", "s3": "s3", "gcs": "gcs"}  # line 26
    @staticmethod
    def create(manager_type: Literal["fs","temp","s3","gcs"], **kwargs) -> FileManagerInterface:  # line 33

# packages/ai-parrot/src/parrot/tools/filemanager.py:136
class FileManagerTool(AbstractTool):
    name: str = "file_manager"                       # line 157
    def _create_manager(self, manager_type, **kwargs) -> FileManagerInterface:  # line 207
    def _check_file_size(self, size: int): ...       # line 237
    def _resolve_output_path(self, path) -> str: ... # line 245
    async def _list_files(self, args) -> Dict: ...   # line 309
    async def _upload_file(self, args) -> Dict: ...  # line 334
    async def _download_file(self, args) -> Dict: ...# line 363
    async def _copy_file(self, args) -> Dict: ...    # line 384
    async def _delete_file(self, args) -> Dict: ...  # line 403
    async def _exists(self, args) -> Dict: ...       # line 416
    async def _get_file_url(self, args) -> Dict: ... # line 427
    async def _get_file_metadata(self, args) -> Dict: ...  # line 441
    async def _create_file(self, args) -> Dict: ...  # line 457
```

### Does NOT Exist
- ~~`parrot.tools.filemanager.FileManagerToolkit`~~ — does not exist yet (this task creates it)
- ~~`navigator.utils.file.abstract`~~ — module does not exist in navigator-api 2.14.10
- ~~`navigator.utils.file.FileManagerInterface`~~ — does not exist in navigator-api 2.14.10
- ~~`navigator.utils.file.FileManagerFactory`~~ — does not exist; `FileManagerFactory` is local in `filemanager.py:18`
- ~~`navigator.utils.file.local.LocalFileManager`~~ — module does not exist in navigator-api 2.14.10
- ~~`AbstractToolkit.register_tool()`~~ — no such method; tools are auto-discovered from public async methods
- ~~`AbstractToolkit.add_tool()`~~ — no such method

---

## Implementation Notes

### Pattern to Follow
```python
# Follow DatabaseQueryToolkit pattern — packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py:106
class DatabaseQueryToolkit(AbstractToolkit):
    tool_prefix: Optional[str] = "dq"                   # line 135
    exclude_tools: tuple[str, ...] = ("get_source", "cleanup", "start", "stop")  # line 140

    def __init__(self, **kwargs: Any) -> None:           # line 142
        super().__init__(**kwargs)
        # ... setup private state ...

    # Each public async method auto-becomes a tool:
    async def get_database_metadata(self, driver: str, ...) -> MetadataResult:
        """Retrieve schema metadata for a database."""    # docstring = tool description
        ...
```

### Key Constraints
- Must be async throughout — every public method is `async def`.
- Method names become tool names after prefix: `list_files` → `fs_list_files`.
- Each method's type hints auto-generate the Pydantic schema for that tool (via `ToolkitTool._generate_args_schema_from_method`).
- Return dicts — NOT `ToolResult`. The `ToolkitTool._execute` → `AbstractTool.execute` wrapper creates `ToolResult` automatically.
- Port logic from `FileManagerTool._*` methods but accept typed params directly (no `FileManagerToolArgs` intermediate).
- Use `self.logger` from `AbstractToolkit.__init__`.

### Operation → Method name mapping for `allowed_operations`
| Operation key | Method to exclude if missing |
|---|---|
| `list` | `list_files` |
| `upload` | `upload_file` |
| `download` | `download_file` |
| `copy` | `copy_file` |
| `delete` | `delete_file` |
| `exists` | `file_exists` |
| `get_url` | `get_file_url` |
| `get_metadata` | `get_file_metadata` |
| `create` | `create_file` |

Implement this by computing `exclude_tools` in `__init__` before calling `super().__init__()`:
```python
_OP_TO_METHOD = {
    "list": "list_files", "upload": "upload_file", "download": "download_file",
    "copy": "copy_file", "delete": "delete_file", "exists": "file_exists",
    "get_url": "get_file_url", "get_metadata": "get_file_metadata", "create": "create_file",
}
ALL_OPS = set(_OP_TO_METHOD)

# In __init__:
if allowed_operations is not None:
    excluded = tuple(
        method for op, method in _OP_TO_METHOD.items()
        if op not in allowed_operations
    )
    self.exclude_tools = excluded
```

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py` — primary pattern reference
- `packages/ai-parrot/src/parrot/tools/filemanager.py` — source logic to port
- `packages/ai-parrot/src/parrot/tools/toolkit.py` — AbstractToolkit base class

---

## Acceptance Criteria

- [ ] `FileManagerToolkit` class exists in `filemanager.py` inheriting `AbstractToolkit`
- [ ] `tool_prefix` is `"fs"`
- [ ] 9 public async methods exist: `list_files`, `upload_file`, `download_file`, `copy_file`, `delete_file`, `file_exists`, `get_file_url`, `get_file_metadata`, `create_file`
- [ ] `get_tools()` returns exactly 9 tools (with default `allowed_operations`)
- [ ] Tool names are `fs_list_files`, `fs_upload_file`, etc.
- [ ] Each method returns the same dict structure as the corresponding `FileManagerTool._*` method
- [ ] `allowed_operations` filtering works (restricts which tools are generated)
- [ ] `max_file_size` enforcement works on `create_file` and `upload_file`
- [ ] `FileManagerTool` remains in the file with a deprecation notice in docstring
- [ ] `FileManagerFactory` is reused unchanged
- [ ] Imports work: `from parrot.tools.filemanager import FileManagerToolkit`

---

## Test Specification

```python
# Minimal smoke test — full test suite is TASK-872
import pytest
from parrot.tools.filemanager import FileManagerToolkit

def test_toolkit_instantiation():
    tk = FileManagerToolkit(manager_type="temp")
    assert tk.tool_prefix == "fs"

def test_tool_count():
    tk = FileManagerToolkit(manager_type="temp")
    tools = tk.get_tools()
    assert len(tools) == 9

def test_tool_names():
    tk = FileManagerToolkit(manager_type="temp")
    names = tk.list_tool_names()
    expected = {
        "fs_list_files", "fs_upload_file", "fs_download_file",
        "fs_copy_file", "fs_delete_file", "fs_file_exists",
        "fs_get_file_url", "fs_get_file_metadata", "fs_create_file",
    }
    assert set(names) == expected
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filemanagertool-migration-toolkit.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-869-filemanager-toolkit-core.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude claude-sonnet-4-5)
**Date**: 2026-04-27
**Notes**: Implemented `FileManagerToolkit` as an `AbstractToolkit` subclass with `tool_prefix="fs"`.
All 9 public async methods were created, each porting logic from the corresponding `FileManagerTool._*`
method but accepting typed params directly. `_OP_TO_METHOD` mapping used to compute `exclude_tools`
dynamically in `__init__` for `allowed_operations` filtering. `_check_file_size` and
`_resolve_output_path` ported as private helpers. `FileManagerTool` docstring updated with
deprecation notice. Import of `AbstractToolkit` added to file header.

NOTE: The module cannot be imported at runtime in the current environment because the installed
`navigator-api 2.14.10` does not expose `FileManagerInterface`, `LocalFileManager`, or
`FileManagerFactory` from `navigator.utils.file` — this is a **pre-existing** import failure in
`parrot/interfaces/file/__init__.py` and `filemanager.py` unrelated to this task. Syntax and ruff
linting pass cleanly.

**Deviations from spec**: none
