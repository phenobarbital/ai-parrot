# TASK-852: Adapt FileManagerTool._create_file and delegate FileManagerFactory to upstream

**Feature**: FEAT-123 — fileinterface-migration
**Spec**: `sdd/specs/fileinterface-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-851
**Assigned-to**: unassigned

---

## Context

Two pieces of `parrot.tools.filemanager` rely on details that
diverge from the upstream `navigator.utils.file` API:

1. **`FileManagerTool._create_file` (line 453)** assumes
   `manager.create_from_bytes(...)` returns a `FileMetadata`. The
   upstream contract (`navigator.utils.file.abstract.FileManagerInterface.create_from_bytes`)
   returns `bool`. After TASK-851, calling
   `metadata.name` on the return value will raise
   `AttributeError`. The fix is to discard the bool result and
   call `manager.get_file_metadata(dest)` to obtain the
   `FileMetadata` the response dict needs.

2. **`FileManagerFactory.create(...)` (line 21)** is a
   parrot-level factory that branches on
   `Literal["fs","temp","s3","gcs"]` and instantiates managers
   directly from `parrot.interfaces.file.*`. Upstream now ships
   its own `FileManagerFactory` (`navigator.utils.file.FileManagerFactory`)
   keyed on `"local"`/`"temp"`/`"s3"`/`"gcs"`. Per the spec, the
   parrot-level factory keeps its public signature (so existing
   callers — including `FileManagerTool._create_manager` — do
   not change) and delegates to the upstream factory, mapping
   only `"fs" → "local"`.

Implements **Modules 4 and 5** of the spec.

---

## Scope

- Modify `packages/ai-parrot/src/parrot/tools/filemanager.py`:
  - Replace the body of
    `FileManagerFactory.create(manager_type, **kwargs)` (lines
    20–40) with a delegation to
    `navigator.utils.file.FileManagerFactory.create(...)`,
    mapping `"fs" → "local"` and forwarding everything else
    unchanged. Keep the `Literal["fs","temp","s3","gcs"]`
    annotation on the public signature.
  - In `FileManagerTool._create_file` (lines 439–465), after
    the `await self.manager.create_from_bytes(...)` call,
    *discard* the bool return value and add a follow-up
    `metadata = await self.manager.get_file_metadata(dest)` to
    populate the response dict (`name`, `path`, `size`,
    `content_type`, `url`).
- Keep the existing logger lines and error handling intact.
- The change must be observable: `FileManagerFactory.create("fs", ...)`
  must return an instance of `navigator.utils.file.local.LocalFileManager`
  (verified via `isinstance` against the upstream class).

**NOT in scope**:
- Editing `parrot/interfaces/file/*` (TASK-851 already did).
- Bumping `pyproject.toml` (TASK-850).
- Writing the shim regression test file (TASK-853).
- Touching `tests/test_video_reel_storage.py` or
  `tests/storage/test_overflow_store.py` (TASK-854 — only if
  failures surface).
- Adapting any of the four `create_from_bytes` callsites in
  `parrot/clients/google/generation.py` (lines 2158, 2211, 2229,
  2340) — they already discard the return value, so no edit is
  needed. Likewise `parrot/storage/overflow.py:67` discards.
- Changing `FileManagerTool`'s public arguments, schema, or
  behaviour (max file size checks, allowed_operations,
  output_dir resolution, etc.).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | (a) Delegate `FileManagerFactory.create` to `navigator.utils.file.FileManagerFactory`. (b) Adapt `FileManagerTool._create_file` to call `get_file_metadata` after `create_from_bytes`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Upstream — to be added:
from navigator.utils.file import FileManagerFactory as _UpstreamFileManagerFactory
# (alias avoids name collision with the parrot-level FileManagerFactory class
#  that lives in this same module).

# Existing in this file (verified, do NOT change):
from parrot.interfaces.file import FileManagerInterface, LocalFileManager, TempFileManager
# (after TASK-851 these are re-exports of navigator.utils.file.*)
```

### Existing Signatures to Use

```python
# parrot/tools/filemanager.py:17-40 — current FileManagerFactory (TO REPLACE)
class FileManagerFactory:
    """Factory for creating file managers."""

    @staticmethod
    def create(
        manager_type: Literal["fs", "temp", "s3", "gcs"],
        **kwargs
    ) -> FileManagerInterface:
        """Create a file manager instance."""
        if manager_type == "fs":
            return LocalFileManager(**kwargs)
        elif manager_type == "temp":
            return TempFileManager(**kwargs)
        elif manager_type == "s3":
            from parrot.interfaces.file import S3FileManager
            return S3FileManager(**kwargs)
        elif manager_type == "gcs":
            from parrot.interfaces.file import GCSFileManager
            return GCSFileManager(**kwargs)
        else:
            raise ValueError(
                f"Unknown manager type: {manager_type}. "
                f"Available: ['fs', 'temp', 's3', 'gcs']"
            )
```

```python
# parrot/tools/filemanager.py:439-465 — current _create_file (TO ADAPT)
async def _create_file(self, args: FileManagerToolArgs) -> Dict[str, Any]:
    """Create a new file with content."""
    if not args.path:
        raise ValueError("path is required for create operation")
    if not args.content:
        raise ValueError("content is required for create operation")

    encoding = args.encoding or 'utf-8'
    content_bytes = args.content.encode(encoding)
    self._check_file_size(len(content_bytes))

    dest = self._resolve_output_path(args.path)
    self.logger.info(f"Creating file '{dest}' ({len(content_bytes)} bytes)")

    metadata = await self.manager.create_from_bytes(   # ← line 453, returns bool upstream
        dest,
        BytesIO(content_bytes)
    )

    return {
        "created": True,
        "name": metadata.name,        # ← AttributeError after migration
        "path": metadata.path,
        "size": metadata.size,
        "content_type": metadata.content_type,
        "url": metadata.url
    }
```

```python
# Upstream signatures (verified 2026-04-25):

# navigator/utils/file/factory.py:42
class FileManagerFactory:
    @staticmethod
    def create(manager_type: str, **kwargs: Any) -> FileManagerInterface: ...
    # Keys: "local", "temp", "s3", "gcs". Note: "local", NOT "fs".

# navigator/utils/file/abstract.py:245 — FileManagerInterface
async def create_from_bytes(
    self, path: str, data: Union[bytes, BytesIO, StringIO]
) -> bool: ...

# navigator/utils/file/abstract.py:141
async def get_file_metadata(self, path: str) -> FileMetadata:
    """Returns FileMetadata; raises FileNotFoundError if absent."""
```

### Does NOT Exist

- ~~`navigator.utils.file.FileManagerFactory.create("fs", ...)`~~ —
  upstream uses `"local"`, not `"fs"`. The mapping must happen
  in this file.
- ~~`FileManagerInterface.create_from_bytes` returning
  `FileMetadata`~~ — it returns `bool` per
  `navigator/utils/file/abstract.py:245`. Do not "fix" it
  upstream-side; adapt the caller.
- ~~`navigator.utils.file.LocalFileManager.create_from_bytes`
  override returning `FileMetadata`~~ — does not exist; the
  upstream concrete class inherits the abstract default. (The
  ai-parrot fork had this override; it is gone after TASK-851.)
- ~~`FileManagerTool` instance attribute named `manager_factory`~~ —
  not present; the tool calls `FileManagerFactory.create(...)`
  as a static method via the module-level class.
- ~~`asyncio.gather` with `create_from_bytes` and
  `get_file_metadata`~~ — do them sequentially. They are not
  independent; the metadata read must happen after the write
  completes.

---

## Implementation Notes

### Pattern to Follow — delegating `FileManagerFactory.create`

```python
from typing import Any, Literal
from navigator.utils.file import FileManagerFactory as _UpstreamFileManagerFactory


class FileManagerFactory:
    """Factory for creating file managers.

    Thin delegate over ``navigator.utils.file.FileManagerFactory``.
    Maps the historical parrot-side key ``"fs"`` to the upstream
    ``"local"`` key; forwards all other keys verbatim.
    """

    _PARROT_TO_UPSTREAM = {
        "fs": "local",
        "temp": "temp",
        "s3": "s3",
        "gcs": "gcs",
    }

    @staticmethod
    def create(
        manager_type: Literal["fs", "temp", "s3", "gcs"],
        **kwargs: Any,
    ) -> FileManagerInterface:
        """Create a file manager instance via the upstream factory.

        Args:
            manager_type: One of ``"fs"`` (local disk), ``"temp"``,
                ``"s3"``, ``"gcs"``.
            **kwargs: Forwarded to the upstream manager constructor.

        Returns:
            A FileManagerInterface instance.

        Raises:
            ValueError: If ``manager_type`` is not recognised.
        """
        try:
            upstream_key = FileManagerFactory._PARROT_TO_UPSTREAM[manager_type]
        except KeyError:
            raise ValueError(
                f"Unknown manager type: {manager_type}. "
                f"Available: {sorted(FileManagerFactory._PARROT_TO_UPSTREAM)}"
            )
        return _UpstreamFileManagerFactory.create(upstream_key, **kwargs)
```

### Pattern to Follow — adapted `_create_file`

```python
async def _create_file(self, args: FileManagerToolArgs) -> Dict[str, Any]:
    """Create a new file with content."""
    if not args.path:
        raise ValueError("path is required for create operation")
    if not args.content:
        raise ValueError("content is required for create operation")

    encoding = args.encoding or "utf-8"
    content_bytes = args.content.encode(encoding)
    self._check_file_size(len(content_bytes))

    dest = self._resolve_output_path(args.path)
    self.logger.info(f"Creating file '{dest}' ({len(content_bytes)} bytes)")

    # Upstream create_from_bytes returns bool; fetch metadata explicitly.
    await self.manager.create_from_bytes(dest, BytesIO(content_bytes))
    metadata = await self.manager.get_file_metadata(dest)

    return {
        "created": True,
        "name": metadata.name,
        "path": metadata.path,
        "size": metadata.size,
        "content_type": metadata.content_type,
        "url": metadata.url,
    }
```

### Key Constraints

- Use the alias `_UpstreamFileManagerFactory` to avoid shadowing
  the parrot-level `FileManagerFactory` class in this file. Any
  other alias name is fine; just don't `from navigator.utils.file
  import FileManagerFactory` directly into this module's
  namespace.
- Do **not** import `LocalFileManager` / `TempFileManager` /
  `S3FileManager` / `GCSFileManager` inside the new
  `FileManagerFactory.create` body — the upstream factory does
  the lazy import for cloud managers; we just forward.
- The eager `from parrot.interfaces.file import FileManagerInterface, LocalFileManager, TempFileManager`
  at the top of the file (line 14) **stays as-is** — it is
  still needed for the type annotation
  (`-> FileManagerInterface`) and is harmless after TASK-851
  (the imports are re-exports of the upstream classes).
- Do not silently catch the new `FileNotFoundError` that
  `get_file_metadata` may raise — let it propagate so the
  outer `_execute` `try/except` in `FileManagerTool` (line 280)
  can convert it to a `ToolResult(success=False, ...)`. That
  outer handler already exists.
- Do not reorder the existing `_check_file_size`,
  `_resolve_output_path`, or `self.logger.info` calls.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/filemanager.py:14` —
  existing eager imports (keep).
- `packages/ai-parrot/src/parrot/tools/filemanager.py:175,189-209` —
  `_create_manager` calls `FileManagerFactory.create` with the
  parrot-side keys; after this task it transparently flows
  through the upstream factory.
- `packages/ai-parrot/src/parrot/tools/filemanager.py:280-289` —
  outer try/except in `_execute` that converts exceptions into
  `ToolResult(success=False, ...)`.
- `~/proyectos/navigator/navigator/navigator/utils/file/factory.py:42` —
  upstream factory signature.

---

## Acceptance Criteria

- [ ] `parrot.tools.filemanager.FileManagerFactory.create("fs", base_path=tmp)`
      returns an instance of
      `navigator.utils.file.local.LocalFileManager` (verified
      with `isinstance`).
- [ ] `parrot.tools.filemanager.FileManagerFactory.create("temp")`
      returns a `navigator.utils.file.tmp.TempFileManager`.
- [ ] `parrot.tools.filemanager.FileManagerFactory.create("xyz")`
      raises `ValueError` whose message lists the valid keys
      `['fs', 'gcs', 's3', 'temp']` (or the same set in any
      order).
- [ ] The body of `parrot.tools.filemanager.FileManagerFactory.create`
      contains no `LocalFileManager(...)`, `TempFileManager(...)`,
      `S3FileManager(...)`, or `GCSFileManager(...)` calls — only
      a delegation to `_UpstreamFileManagerFactory.create(...)`.
- [ ] `FileManagerTool` with `manager_type="fs"` and a temp
      `base_path` can:
      1. Run a `create` operation with text content.
      2. Return a result dict whose `result["name"]`,
         `result["path"]`, `result["size"]`, and
         `result["content_type"]` are populated (no
         `AttributeError`).
- [ ] `grep -n 'metadata = await self.manager.create_from_bytes' packages/ai-parrot/src/parrot/tools/filemanager.py`
      returns no matches (confirms the bool-return-misuse pattern
      is gone).
- [ ] `grep -n 'await self.manager.get_file_metadata' packages/ai-parrot/src/parrot/tools/filemanager.py`
      shows the new explicit metadata fetch inside `_create_file`.
- [ ] No linting errors:
      `ruff check packages/ai-parrot/src/parrot/tools/filemanager.py`.
- [ ] The smoke check in Test Specification below passes.

---

## Test Specification

The dedicated regression test file is added in TASK-853. This
task's verification is the inline smoke check below.

```bash
source .venv/bin/activate
python - <<'PY'
import asyncio
import tempfile
from pathlib import Path

from parrot.tools.filemanager import FileManagerFactory, FileManagerTool
from navigator.utils.file.local import LocalFileManager as UpstreamLocal
from navigator.utils.file.tmp import TempFileManager as UpstreamTemp


def test_factory_delegation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        fm = FileManagerFactory.create("fs", base_path=tmp)
        assert isinstance(fm, UpstreamLocal), type(fm)
    fm = FileManagerFactory.create("temp")
    assert isinstance(fm, UpstreamTemp), type(fm)
    try:
        FileManagerFactory.create("xyz")
    except ValueError as exc:
        assert "xyz" in str(exc) or "Unknown" in str(exc)
    else:
        raise AssertionError("ValueError not raised")


async def test_tool_create_file_uses_get_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tool = FileManagerTool(
            manager_type="fs",
            default_output_dir=tmp,
            base_path=tmp,
        )
        result = await tool._execute(
            operation="create",
            path="hello.txt",
            content="hi",
        )
        assert result.success, result.error
        body = result.result
        assert body["created"] is True
        assert body["name"] == "hello.txt"
        assert body["size"] == len("hi".encode("utf-8"))
        # path returned by upstream LocalFileManager is relative
        assert "hello.txt" in body["path"]


test_factory_delegation()
asyncio.run(test_tool_create_file_uses_get_metadata())
print("ok")
PY
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — TASK-850 and TASK-851 must be in
   `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read the current
   `parrot/tools/filemanager.py` (lines 17–40 and 439–465). If
   line numbers have shifted, locate the same constructs by
   name (`class FileManagerFactory:`, `async def _create_file`).
4. **Update status** in `sdd/tasks/.index.json` →
   `"in-progress"` with your session ID.
5. **Implement** both edits in the same file. Run the smoke
   check in Test Specification above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to
   `sdd/tasks/completed/TASK-852-adapt-filemanager-tool-and-factory.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
