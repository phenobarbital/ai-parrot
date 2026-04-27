# Feature Specification: FileManagerTool Migration to Toolkit

**Feature ID**: FEAT-127
**Date**: 2026-04-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The current `FileManagerTool` uses a **multi-operation dispatch pattern** where the LLM must set an `operation` field (one of `list`, `upload`, `download`, `copy`, `delete`, `exists`, `get_url`, `get_metadata`, `create`) alongside operation-specific arguments in a single flat schema containing 12+ optional fields.

This causes real failures:
- **LLMs confuse operation semantics**: weaker models cannot reliably determine when to use `"create"` vs `"upload"`, or forget to set required fields for a given operation.
- **Schema bloat**: every tool call sends the LLM a schema with all 12 fields, most irrelevant for the chosen operation. This wastes context tokens and increases hallucination risk.
- **Validation ambiguity**: the `FileManagerToolArgs` schema cannot enforce per-operation required fields via Pydantic (e.g., `content` is only required for `"create"` but appears Optional in the global schema).

The proven solution — already adopted by `DatabaseQueryToolkit` (FEAT-105), `JiraToolkit`, `ScrapingToolkit`, and `OpenAPIToolkit` — is the **AbstractToolkit pattern**: one public async method per action, each auto-wrapped as a separate tool with its own focused schema.

### Goals
- Replace `FileManagerTool` with `FileManagerToolkit` using `AbstractToolkit`.
- Each file operation becomes a standalone tool with a focused, minimal schema.
- All tools share the `fs_` prefix (e.g., `fs_list_files`, `fs_create_file`).
- Preserve all existing functionality: same backends (fs, temp, s3, gcs), same `FileManagerFactory`.
- Maintain backward compatibility: `FileManagerTool` stays importable (deprecated alias or wrapper).

### Non-Goals (explicitly out of scope)
- Rewriting or modifying the upstream `navigator.utils.file` file managers (S3FileManager, GCSFileManager, TempFileManager).
- Adding new file operations beyond what `FileManagerTool` currently supports.
- Changing the `FileManagerFactory` logic or backend registration.
- Modifying `parrot/interfaces/file/` abstractions.

---

## 2. Architectural Design

### Overview

`FileManagerToolkit` inherits from `AbstractToolkit` and exposes 9 public async methods — one per file operation. Each method receives only the arguments relevant to that specific operation, typed and documented for the LLM. The toolkit wraps the same `FileManagerFactory` and backend interface used by `FileManagerTool`.

The `tool_prefix` is set to `"fs"`, producing tool names like:
- `fs_list_files`
- `fs_upload_file`
- `fs_download_file`
- `fs_copy_file`
- `fs_delete_file`
- `fs_file_exists`
- `fs_get_file_url`
- `fs_get_file_metadata`
- `fs_create_file`

### Component Diagram
```
FileManagerToolkit (AbstractToolkit)
    ├── fs_list_files()       ─┐
    ├── fs_upload_file()       │
    ├── fs_download_file()     │
    ├── fs_copy_file()         ├──→ FileManagerFactory.create(type)
    ├── fs_delete_file()       │         │
    ├── fs_file_exists()       │         ├──→ LocalFileManager (fs)
    ├── fs_get_file_url()      │         ├──→ TempFileManager (temp)
    ├── fs_get_file_metadata() │         ├──→ S3FileManager (s3)
    └── fs_create_file()      ─┘         └──→ GCSFileManager (gcs)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | inherits | Base class — auto-generates tools from public async methods |
| `FileManagerFactory` | uses | Reused verbatim from `filemanager.py` — maps backend keys to upstream managers |
| `ToolManager` | consumed by | Agents register toolkit tools via `toolkit.get_tools()` |
| `parrot/tools/__init__.py` | exports | New `FileManagerToolkit` added to lazy-load map and `__all__` |
| `parrot_tools/__init__.py` | registry | Update `TOOL_REGISTRY` entry for `file_manager` to point at toolkit |

### Data Models

No new Pydantic models are needed. Each toolkit method uses typed parameters directly — `AbstractToolkit._generate_tools()` auto-creates per-method arg schemas from type hints.

Return values continue to use `dict` (matching the current `FileManagerTool` pattern), wrapped by `ToolkitTool._execute` → `AbstractTool.execute` → `ToolResult`.

### New Public Interfaces
```python
class FileManagerToolkit(AbstractToolkit):
    """Toolkit for file operations across storage backends."""

    tool_prefix: str = "fs"

    def __init__(
        self,
        manager_type: Literal["fs", "temp", "s3", "gcs"] = "fs",
        default_output_dir: Optional[str] = None,
        allowed_operations: Optional[set[str]] = None,
        max_file_size: int = 100 * 1024 * 1024,
        auto_create_dirs: bool = True,
        **manager_kwargs,
    ) -> None: ...

    async def list_files(
        self, path: str = "", pattern: str = "*"
    ) -> dict[str, Any]: ...

    async def upload_file(
        self, source_path: str, destination: Optional[str] = None,
        destination_name: Optional[str] = None,
    ) -> dict[str, Any]: ...

    async def download_file(
        self, path: str, destination: Optional[str] = None,
    ) -> dict[str, Any]: ...

    async def copy_file(
        self, source: str, destination: str,
    ) -> dict[str, Any]: ...

    async def delete_file(self, path: str) -> dict[str, Any]: ...

    async def file_exists(self, path: str) -> dict[str, Any]: ...

    async def get_file_url(
        self, path: str, expiry_seconds: int = 3600,
    ) -> dict[str, Any]: ...

    async def get_file_metadata(self, path: str) -> dict[str, Any]: ...

    async def create_file(
        self, path: str, content: str, encoding: str = "utf-8",
    ) -> dict[str, Any]: ...
```

---

## 3. Module Breakdown

### Module 1: FileManagerToolkit
- **Path**: `packages/ai-parrot/src/parrot/tools/filemanager.py`
- **Responsibility**: New `FileManagerToolkit` class added alongside existing `FileManagerTool` and `FileManagerFactory`. Each file operation is a public async method with focused parameters and docstrings. Reuses internal helpers (`_resolve_output_path`, `_check_file_size`, `_check_operation`).
- **Depends on**: `AbstractToolkit`, `FileManagerFactory` (both already exist)

### Module 2: Exports & Registry Update
- **Path**: `packages/ai-parrot/src/parrot/tools/__init__.py`
- **Responsibility**: Add `FileManagerToolkit` to `__all__`, `_LAZY_CORE_TOOLS`, and the lazy-load map. Keep `FileManagerTool` for backward compat.
- **Depends on**: Module 1

### Module 3: parrot_tools Registry Update
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/__init__.py`
- **Responsibility**: Update the `TOOL_REGISTRY` entry `"file_manager"` to point at `FileManagerToolkit` (or add `"file_manager_toolkit"` as a new entry alongside the old one).
- **Depends on**: Module 1

### Module 4: Unit Tests
- **Path**: `tests/tools/test_filemanager_toolkit.py`
- **Responsibility**: Test each tool method individually, verify tool_prefix produces correct names, verify schema generation per-method, verify `allowed_operations` filtering, verify backward compat of `FileManagerTool`.
- **Depends on**: Module 1

### Module 5: Example Update
- **Path**: `examples/tool/fs.py`
- **Responsibility**: Update the example to demonstrate `FileManagerToolkit` usage (show individual tool calls vs the old operation dispatch).
- **Depends on**: Module 1, Module 2

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_toolkit_initialization` | Module 1 | Toolkit creates with default and custom configs |
| `test_tool_prefix_applied` | Module 1 | All generated tools have `fs_` prefix |
| `test_tool_count` | Module 1 | `get_tools()` returns exactly 9 tools |
| `test_tool_names` | Module 1 | Tool names match `fs_list_files`, `fs_create_file`, etc. |
| `test_list_files_schema` | Module 1 | Schema has `path` and `pattern` only |
| `test_create_file_schema` | Module 1 | Schema has `path`, `content`, `encoding` only |
| `test_upload_file_schema` | Module 1 | Schema has `source_path`, `destination`, `destination_name` only |
| `test_list_files_operation` | Module 1 | Lists files from local fs backend |
| `test_create_file_operation` | Module 1 | Creates a file with content |
| `test_delete_file_operation` | Module 1 | Deletes a file |
| `test_file_exists_operation` | Module 1 | Checks file existence |
| `test_copy_file_operation` | Module 1 | Copies a file within storage |
| `test_download_file_operation` | Module 1 | Downloads a file to destination |
| `test_get_file_url_operation` | Module 1 | Returns URL for a file |
| `test_get_file_metadata_operation` | Module 1 | Returns file metadata dict |
| `test_allowed_operations_filter` | Module 1 | Restricting operations disables specific tools |
| `test_max_file_size_enforcement` | Module 1 | Large content rejected on create |
| `test_backward_compat_filemanagertool` | Module 2 | `FileManagerTool` still importable and functional |

### Integration Tests
| Test | Description |
|---|---|
| `test_toolkit_with_agent` | Attach toolkit to an Agent, verify tools are registered |
| `test_toolkit_temp_backend` | End-to-end create → exists → metadata → delete with temp backend |

### Test Data / Fixtures
```python
@pytest.fixture
def fs_toolkit(tmp_path):
    """FileManagerToolkit with local fs backend pointing at tmp_path."""
    return FileManagerToolkit(
        manager_type="fs",
        default_output_dir=str(tmp_path),
        base_path=tmp_path,
    )

@pytest.fixture
def temp_toolkit():
    """FileManagerToolkit with temp backend."""
    return FileManagerToolkit(manager_type="temp")
```

---

## 5. Acceptance Criteria

- [ ] `FileManagerToolkit` inherits from `AbstractToolkit` and exposes 9 tools via `get_tools()`.
- [ ] Every tool has the `fs_` prefix (e.g., `fs_list_files`, `fs_create_file`).
- [ ] Each tool schema contains only the parameters relevant to that operation (no shared flat schema).
- [ ] All 9 operations produce the same return dicts as the current `FileManagerTool._*` methods.
- [ ] `FileManagerFactory` is reused unchanged.
- [ ] `allowed_operations` parameter can restrict which tools are generated.
- [ ] `max_file_size` enforcement works on `create_file` and `upload_file`.
- [ ] `FileManagerTool` remains importable from `parrot.tools` (backward compat).
- [ ] `from parrot.tools import FileManagerToolkit` works.
- [ ] All unit tests pass: `pytest tests/tools/test_filemanager_toolkit.py -v`
- [ ] Example updated in `examples/tool/fs.py`.
- [ ] No breaking changes to existing public API.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit       # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:168
from parrot.tools.abstract import AbstractTool, ToolResult, AbstractToolArgsSchema  # verified: packages/ai-parrot/src/parrot/tools/abstract.py:71,36,23
from parrot.tools.filemanager import FileManagerFactory  # verified: packages/ai-parrot/src/parrot/tools/filemanager.py:18
from parrot.interfaces.file import FileManagerInterface  # verified: packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18
                                                          # NOTE: depends on navigator-api upgrade — may fail on current 2.14.10
from parrot.conf import OUTPUT_DIR                       # verified: used in filemanager.py:14
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                      # line 168
    tool_prefix: Optional[str] = None                            # line 219
    prefix_separator: str = "_"                                  # line 222
    exclude_tools: tuple[str, ...] = ()                          # line 205
    def __init__(self, **kwargs): ...                             # line 224
    def get_tools(self, ...) -> List[AbstractTool]: ...          # line 292
    def _resolve_tool_name(self, method_name: str) -> str: ...   # line 324
    def _generate_tools(self) -> None: ...                       # line 345
    async def _pre_execute(self, tool_name, **kwargs): ...       # line 261
    async def _post_execute(self, tool_name, result, **kwargs): ...  # line 276

# packages/ai-parrot/src/parrot/tools/filemanager.py
class FileManagerFactory:                                        # line 18
    _PARROT_TO_UPSTREAM: dict = {"fs": "local", "temp": "temp", "s3": "s3", "gcs": "gcs"}  # line 26
    @staticmethod
    def create(manager_type: Literal["fs","temp","s3","gcs"], **kwargs) -> FileManagerInterface:  # line 33

class FileManagerToolArgs(AbstractToolArgsSchema):               # line 61
    operation: Literal["list","upload","download","copy","delete","exists","get_url","get_metadata","create"]  # line 68
    path: Optional[Union[str, Path]]                             # line 88
    pattern: Optional[str]                                       # line 94
    source_path: Optional[str]                                   # line 100
    destination: Optional[str]                                   # line 104
    destination_name: Optional[str]                              # line 108
    source: Optional[str]                                        # line 114
    content: Optional[str]                                       # line 120
    encoding: Optional[str]                                      # line 124
    expiry_seconds: Optional[int]                                # line 130

class FileManagerTool(AbstractTool):                             # line 136
    name: str = "file_manager"                                   # line 157
    def __init__(self, manager_type, default_output_dir, allowed_operations, max_file_size, auto_create_dirs, **manager_kwargs):  # line 161
    def _create_manager(self, manager_type, **kwargs) -> FileManagerInterface:  # line 207
    def _check_operation(self, operation: str): ...              # line 229
    def _check_file_size(self, size: int): ...                   # line 237
    def _resolve_output_path(self, path) -> str: ...             # line 245
    async def _execute(self, **kwargs) -> ToolResult: ...        # line 255
    async def _list_files(self, args) -> Dict: ...               # line 309
    async def _upload_file(self, args) -> Dict: ...              # line 334
    async def _download_file(self, args) -> Dict: ...            # line 363
    async def _copy_file(self, args) -> Dict: ...                # line 384
    async def _delete_file(self, args) -> Dict: ...              # line 403
    async def _exists(self, args) -> Dict: ...                   # line 416
    async def _get_file_url(self, args) -> Dict: ...             # line 427
    async def _get_file_metadata(self, args) -> Dict: ...        # line 441
    async def _create_file(self, args) -> Dict: ...              # line 457

# packages/ai-parrot/src/parrot/tools/__init__.py
__all__: includes "FileManagerTool", "FileManagerFactory"        # line 207
_LAZY_CORE_TOOLS: includes "FileManagerTool": ".filemanager"     # line 238-239

# packages/ai-parrot-tools/src/parrot_tools/__init__.py
"file_manager": "parrot.tools.filemanager.FileManagerTool"       # line 51
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FileManagerToolkit` | `AbstractToolkit` | inheritance | `toolkit.py:168` |
| `FileManagerToolkit` | `FileManagerFactory.create()` | method call in `__init__` | `filemanager.py:33` |
| `FileManagerToolkit` | `ToolManager` | `toolkit.get_tools()` returns `List[AbstractTool]` | `toolkit.py:292` |
| `__init__.py` | `FileManagerToolkit` | lazy import `".filemanager"` | `__init__.py:238` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.tools.filemanager.FileManagerToolkit`~~ — does not exist yet (this spec creates it)
- ~~`FileManagerInterface.copy_file()`~~ — the navigator S3/GCS/Temp managers do NOT have a uniform `copy_file` method; `FileManagerTool._copy_file` wraps `self.manager.copy_file()` but this may not exist on all backends
- ~~`FileManagerInterface.exists()`~~ — not guaranteed on all backends; verify per backend
- ~~`FileManagerInterface.get_file_metadata()`~~ — same; S3FileManager does not expose this
- ~~`FileManagerInterface.create_from_bytes()`~~ — used in `FileManagerTool._create_file` line 472, but not present on all backends
- ~~`navigator.utils.file.abstract`~~ — module does not exist in navigator-api 2.14.10
- ~~`navigator.utils.file.FileManagerInterface`~~ — class does not exist in navigator-api 2.14.10
- ~~`navigator.utils.file.FileManagerFactory`~~ — class does not exist in navigator-api 2.14.10; `FileManagerFactory` is defined locally in `filemanager.py:18`
- ~~`navigator.utils.file.local.LocalFileManager`~~ — module `navigator.utils.file.local` does not exist in navigator-api 2.14.10

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Follow `DatabaseQueryToolkit` pattern** (`packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py:106`): same `AbstractToolkit` base, `tool_prefix`, `exclude_tools`, helper methods excluded from tool generation.
- **Reuse existing private methods**: The logic in `FileManagerTool._list_files()`, `_upload_file()`, etc. is correct — extract and adapt it into standalone public async methods on the toolkit.
- **Keep `FileManagerFactory` unchanged**: the factory already delegates to upstream navigator managers correctly.
- **Use `self.logger`** for all logging (inherited from `AbstractToolkit.__init__`).
- **Each public method's docstring** becomes the LLM tool description — write them as clear action descriptions.

### Implementing `allowed_operations`

The toolkit must support the existing `allowed_operations` parameter from `FileManagerTool`. Two approaches:

**Recommended**: Override `_generate_tools()` to skip methods whose operation name is not in `allowed_operations`. Alternatively, populate `exclude_tools` dynamically in `__init__` based on `allowed_operations`.

Map: `allowed_operations` value → method name:
| Operation | Method |
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

### Known Risks / Gotchas
- **Backend method availability**: Not all navigator file manager backends implement all methods uniformly (e.g., `copy_file`, `exists`, `get_file_metadata`, `create_from_bytes` may not exist on S3/GCS/Temp). The current `FileManagerTool` has the same limitation — the toolkit must handle this identically (raise on unsupported operations).
- **`FileManagerInterface` import**: The `parrot/interfaces/file/__init__.py` shim imports `FileManagerInterface` from navigator, but it does not exist in 2.14.10. The toolkit should use the same import path as `FileManagerTool` — if it breaks there, it breaks here identically. No new risk introduced.
- **Backward compatibility**: `FileManagerTool` must remain importable. Mark it as deprecated in its docstring but do not remove it.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-api` | `>=2.14.1` | Upstream file managers (S3, GCS, Temp) |
| `aioboto3` | optional | Required only for S3 backend |
| `google-cloud-storage` | optional | Required only for GCS backend |

---

## 8. Open Questions

- [x] Should `FileManagerTool` be converted to a thin wrapper that instantiates `FileManagerToolkit` internally (preserving the single-tool API for users who explicitly want it), or should it remain as a standalone class? — *Owner: Jesus:*: remains alone class, in way to be deprecated.
- [ ] Should the `file_manager` key in `parrot_tools/TOOL_REGISTRY` point to the new toolkit or keep pointing to the old tool? Or should both be registered under different keys? — *Owner: Jesus*: now points to new toolkit.
- [ ] For backends that don't support certain operations (e.g., S3 `copy_file`), should the toolkit skip generating those tools, or generate them and raise `NotImplementedError` at call time? — *Owner: Jesus*: generates with a warning (used by LLM for information) about the error of trying to do a "copy_file" in an S3 bucket.

---

## Worktree Strategy

- **Default isolation**: `per-spec` (sequential tasks in one worktree).
- All modules modify the same file (`filemanager.py`) or closely related files — parallelism would cause merge conflicts.
- **Cross-feature dependencies**: None. No in-flight specs touch `parrot/tools/filemanager.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-27 | Jesus Lara | Initial draft |
