# Feature Specification: FileInterface Migration to navigator-api

**Feature ID**: FEAT-123
**Date**: 2026-04-25
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

---

## 1. Motivation & Business Requirements

### Problem Statement

`ai-parrot` originally **copied** the `FileInterface` family
(`FileManagerInterface`, `FileMetadata`, `LocalFileManager`,
`TempFileManager`, `S3FileManager`, `GCSFileManager`) from
`navigator-api` and then locally extended it (lazy imports for
S3/GCS, an internal `parrot.tools.filemanager.FileManagerFactory`,
small overrides on `create_from_bytes` returning `FileMetadata`,
etc.).

The upstream copy in `navigator-api` has since been **rewritten
and homologated** under
[`navigator/utils/file/`](https://github.com/phenobarbital/navigator/tree/master/navigator/utils/file).
The new upstream version is now strictly richer than ai-parrot's
fork:

- Same abstract contract (`FileManagerInterface`, `FileMetadata`).
- Adds `find_files()` with default + concrete overrides.
- Adds `FileManagerFactory` (`local`, `temp`, `s3`, `gcs`) with
  lazy SDK loading.
- Adds `FileServingExtension` — aiohttp web serving layer with
  HTTP Range / streaming support.
- Adds `manager_name` class attribute and `setup()` /
  `handle_file()` web-serving hooks on every concrete manager.
- Hardens credential resolution (S3 reads `aws_key`/`aws_secret`
  matching the actual `AWS_CREDENTIALS` config schema; ai-parrot's
  current S3 code reads `aws_access_key_id`/`aws_secret_access_key`
  which silently fall back to the AWS default-credentials chain
  when unset — a latent bug that the migration removes).
- Has a full SDD-driven test suite (95 tests, see TASK-018 in the
  upstream history).

Maintaining the duplicated fork in ai-parrot is now strictly worse:
fixes and features land upstream and have to be re-applied by hand
here, code drifts (the GCS/S3 code is already several patches
behind), and consumers cannot share managers between
navigator-api-based services and ai-parrot.

`ai-parrot` already declares `navigator-api` as a runtime
dependency, so the migration is a refactor — not a new dependency
adoption.

### Goals

1. Make `navigator.utils.file` the **single source of truth** for
   the FileInterface family used inside ai-parrot.
2. Remove (or thin-shim) the duplicated implementation under
   `parrot/interfaces/file/` so divergence cannot accumulate again.
3. Keep all existing public import paths working
   (`from parrot.interfaces.file import FileManagerInterface, ...`)
   for at least one minor version, so downstream code doesn't
   break.
4. Adapt internal consumers to the upstream API where it differs
   (notably the `create_from_bytes` return type and the
   `parrot.tools.filemanager.FileManagerFactory`).
5. Bump the `navigator-api` minimum version in `pyproject.toml`
   to a release that ships `navigator/utils/file/`
   (≥ `2.14.1`).

### Non-Goals

- **Not** changing the public abstract contract
  (`FileManagerInterface` / `FileMetadata`). Those are identical
  on both sides.
- **Not** consuming `FileServingExtension` from
  `navigator.utils.file.web` in this feature — that's a follow-up
  if/when ai-parrot needs to serve files over HTTP. Mention only.
- **Not** rewriting `parrot.storage.overflow.OverflowStore` or
  `parrot.storage.s3_overflow.S3OverflowStore`. They consume
  `FileManagerInterface` and stay as-is.
- **Not** changing how ai-parrot resolves AWS credentials at
  config level (`parrot.conf.AWS_CREDENTIALS` already uses
  `aws_key`/`aws_secret`, which matches navigator's lookup).

---

## 2. Architectural Design

### Overview

After the migration, `parrot.interfaces.file` becomes a thin
**re-export shim** over `navigator.utils.file`:

```
┌────────────────────────────────────────────────────────┐
│ navigator.utils.file (upstream — single source of truth)│
│   FileManagerInterface, FileMetadata,                   │
│   LocalFileManager, TempFileManager,                    │
│   S3FileManager, GCSFileManager,                        │
│   FileManagerFactory, FileServingExtension              │
└──────────────────────────▲──────────────────────────────┘
                           │  re-export (lazy for S3/GCS)
                           │
┌──────────────────────────┴──────────────────────────────┐
│ parrot.interfaces.file   (shim — backward compat only) │
│   from navigator.utils.file import (                   │
│       FileManagerInterface, FileMetadata,              │
│       LocalFileManager, TempFileManager,               │
│   )                                                     │
│   __getattr__(S3FileManager / GCSFileManager) = lazy   │
└──────────────────────────▲──────────────────────────────┘
                           │
        ┌──────────────────┼─────────────────────┐
        │                  │                     │
parrot.tools.filemanager   parrot.storage.*   parrot.handlers.*
(FileManagerTool +         (OverflowStore,    (video_reel,
  delegating Factory)        S3OverflowStore,   stores/handler,
                             backends builder)  google.generation)
```

The `parrot.tools.filemanager.FileManagerFactory` keeps its current
public signature (`create("fs"|"temp"|"s3"|"gcs", **kwargs)`) but
internally **delegates** to `navigator.utils.file.FileManagerFactory`,
mapping `"fs" → "local"` and forwarding `**kwargs`. Existing
callers (the in-tool `_create_manager` method and any direct
external callers) keep working.

### Component Diagram

```
parrot.interfaces.file.__init__         (shim re-exports)
parrot.interfaces.file.abstract  ──┐
parrot.interfaces.file.local     ──┼─→ DELETED
parrot.interfaces.file.tmp       ──┤   (covered by upstream)
parrot.interfaces.file.s3        ──┤
parrot.interfaces.file.gcs       ──┘

parrot.tools.filemanager.FileManagerFactory
   .create("fs"|"temp"|"s3"|"gcs", **kw)
        │
        ▼  delegates
navigator.utils.file.FileManagerFactory.create("local"|"temp"|...)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator.utils.file.*` (upstream) | uses (re-export) | Single source of truth after migration. |
| `parrot.storage.overflow.OverflowStore` | unchanged | Imports from `parrot.interfaces.file.abstract` — shim must keep that path importable. |
| `parrot.storage.s3_overflow.S3OverflowStore` | unchanged | Imports `from parrot.interfaces.file.s3 import S3FileManager` — shim must keep that path importable (or re-export at submodule level). |
| `parrot.storage.backends.__init__.build_overflow_store` | unchanged code path, behaviour preserved | Imports `LocalFileManager`/`S3FileManager`/`GCSFileManager`/`TempFileManager` from `parrot.interfaces.file.*`. |
| `parrot.handlers.video_reel` | unchanged | Type hint `FileManagerInterface` resolves through shim. |
| `parrot.handlers.stores.handler` | unchanged | Imports `TempFileManager` from `parrot.interfaces.file.tmp`. |
| `parrot.clients.google.generation` | unchanged | Type hints + 4 `create_from_bytes(...)` calls that **discard** the return value (so divergent return type does not affect them). |
| `parrot.tools.filemanager.FileManagerTool._create_file` | **adapted** | Currently relies on `create_from_bytes(...)` returning `FileMetadata`. Upstream returns `bool`. Must call `get_file_metadata()` afterwards. |
| `parrot.tools.filemanager.FileManagerFactory` | **delegates** | Public signature kept; internals call upstream factory. |
| `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py` | unchanged | Already a re-export shim from `parrot.interfaces.file`; will transparently follow the migration. |
| `pyproject.toml` (`navigator-api[uvloop,locale]>=2.13.5`) | **bumped** | Pin to `>=2.14.1` (release that ships `navigator/utils/file/`). |

### Data Models

No new data models. `FileMetadata` (dataclass) is reused as-is from
`navigator.utils.file.abstract`.

### New Public Interfaces

No new public interfaces are introduced by this feature. All
public symbols (`FileManagerInterface`, `FileMetadata`,
`LocalFileManager`, `TempFileManager`, `S3FileManager`,
`GCSFileManager`) keep the same names and same import paths
(`from parrot.interfaces.file import ...`) via the shim. The
upstream classes do gain `manager_name` / `find_files()` / `setup()`
/ `handle_file()` members, but those are additive and pre-existing
in upstream.

---

## 3. Module Breakdown

### Module 1: navigator-api dependency bump

- **Path**: `packages/ai-parrot/pyproject.toml`
- **Responsibility**: Bump `navigator-api[uvloop,locale]>=2.13.5`
  to `>=2.14.1`. Verify there are no transitive conflicts with
  `navigator-auth`, `navigator-session`, `flowtask`, or
  `azure-teambots` (all listed as `Required-by` for navigator-api).
- **Depends on**: nothing.

### Module 2: Shim `parrot.interfaces.file`

- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/__init__.py`
- **Responsibility**: Replace the current re-exports of local
  `.abstract`, `.local`, `.tmp`, `.s3`, `.gcs` with re-exports
  from `navigator.utils.file`. Preserve the existing
  `__getattr__` lazy-loading contract for `S3FileManager` /
  `GCSFileManager` so the shim still avoids importing cloud SDKs
  until used.
- **Depends on**: Module 1.

### Module 3: Submodule shims (`abstract`, `local`, `tmp`, `s3`, `gcs`)

- **Path**: `packages/ai-parrot/src/parrot/interfaces/file/abstract.py`,
  `packages/ai-parrot/src/parrot/interfaces/file/local.py`,
  `packages/ai-parrot/src/parrot/interfaces/file/tmp.py`,
  `packages/ai-parrot/src/parrot/interfaces/file/s3.py`,
  `packages/ai-parrot/src/parrot/interfaces/file/gcs.py`
- **Responsibility**: Replace each module body with a one-line
  re-export from the matching `navigator.utils.file.<sub>`. This
  is required because consumers (e.g.,
  `parrot.storage.overflow`, `parrot.storage.s3_overflow`) import
  from these *submodule* paths, not just the package root.
- **Depends on**: Module 1.

### Module 4: Adapt `FileManagerTool._create_file`

- **Path**: `packages/ai-parrot/src/parrot/tools/filemanager.py`
- **Responsibility**: The current `_create_file` (line 439) does
  `metadata = await self.manager.create_from_bytes(...)`. After
  migration, upstream's `create_from_bytes` returns `bool`, so
  this must be adapted to:
  1. `await self.manager.create_from_bytes(dest, BytesIO(content_bytes))`
  2. `metadata = await self.manager.get_file_metadata(dest)`
  3. Build the response dict from `metadata` as before.
- **Depends on**: Module 2.

### Module 5: Refactor `parrot.tools.filemanager.FileManagerFactory`

- **Path**: `packages/ai-parrot/src/parrot/tools/filemanager.py`
  (lines 17–40)
- **Responsibility**: Replace the body of the parrot-level
  `FileManagerFactory.create(...)` with a delegation to
  `navigator.utils.file.FileManagerFactory.create(...)`, mapping:
  - `"fs"`  → `"local"`
  - `"temp"` → `"temp"`
  - `"s3"`  → `"s3"`
  - `"gcs"` → `"gcs"`
  
  Keep the current `Literal["fs", "temp", "s3", "gcs"]` public
  signature unchanged so `FileManagerTool` callers don't need
  edits.
- **Depends on**: Module 1.

### Module 6: Tests

- **Path**: `packages/ai-parrot/tests/interfaces/test_file_shim.py`
  (new)
- **Responsibility**:
  1. Verify all existing import paths still resolve:
     `from parrot.interfaces.file import FileManagerInterface, FileMetadata, LocalFileManager, TempFileManager`
     and the lazy ones (`S3FileManager`, `GCSFileManager`).
  2. Verify they are the same identity as
     `navigator.utils.file.<X>` (after the shim).
  3. Run a small smoke test: instantiate `LocalFileManager` with
     a temp `base_path`, write/read/delete via the shim, assert
     `create_from_bytes` returns `bool` (proves we are using
     upstream and not the old override).
  4. Verify `parrot.tools.filemanager.FileManagerFactory.create("fs", base_path=tmp)`
     returns a `navigator.utils.file.LocalFileManager` instance.
- **Depends on**: Modules 2, 3, 4, 5.

### Module 7: Existing test updates

- **Path**:
  - `packages/ai-parrot/tests/test_video_reel_storage.py`
  - `packages/ai-parrot/tests/storage/test_overflow_store.py`
- **Responsibility**: These two files use
  `MagicMock(spec=FileManagerInterface)` /
  `AsyncMock(spec=FileManagerInterface)`. Verify that the spec
  still matches all 9 abstract methods after switching to the
  upstream class. If any test asserts on a method/attribute that
  changed name (e.g., new `manager_name` attribute, new
  `find_files` method) the spec list needs adjustment — but
  since `MagicMock(spec=...)` is permissive about extra
  attributes on the spec class, no edits are expected. Run the
  suite; only edit if a real failure surfaces.
- **Depends on**: Modules 2, 3.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_shim_reexports_identity` | 6 | `parrot.interfaces.file.FileManagerInterface is navigator.utils.file.FileManagerInterface` (and same for `FileMetadata`, `LocalFileManager`, `TempFileManager`). |
| `test_shim_lazy_s3_gcs` | 6 | Accessing `parrot.interfaces.file.S3FileManager` returns the upstream `S3FileManager`; same for GCS; first access triggers import. |
| `test_shim_submodule_paths` | 6 | `from parrot.interfaces.file.abstract import FileManagerInterface, FileMetadata` works. Same for `.local`, `.tmp`, `.s3`, `.gcs`. |
| `test_create_from_bytes_returns_bool` | 6 | Direct `LocalFileManager.create_from_bytes(path, b"data")` returns `True` (upstream contract). Confirms migration. |
| `test_filemanager_tool_create_uses_get_metadata` | 4 | `FileManagerTool._create_file(...)` returns a dict with `"name"`, `"path"`, `"size"`, `"content_type"`, `"url"` populated, even though `create_from_bytes` returns `bool`. Proves adapter wiring. |
| `test_factory_fs_returns_localfilemanager` | 5 | `FileManagerFactory.create("fs", base_path=tmp)` is a `LocalFileManager` from `navigator.utils.file.local`. |
| `test_factory_temp_returns_tempfilemanager` | 5 | `FileManagerFactory.create("temp")` is a `TempFileManager` from `navigator.utils.file.tmp`. |
| `test_factory_s3_lazy` | 5 | `FileManagerFactory.create("s3", credentials={...})` returns `S3FileManager` without crashing on `aws_access_key_id` lookup (regression: ai-parrot's S3 used the wrong key). |

### Integration Tests

| Test | Description |
|---|---|
| `test_overflow_store_with_localfilemanager` | Existing `tests/storage/test_overflow_store.py` continues to pass, using an upstream `LocalFileManager` via the shim. |
| `test_video_reel_storage_factory` | Existing `tests/test_video_reel_storage.py` continues to pass — `_resolve_file_manager` (in `handlers/video_reel.py`) returns upstream managers via the shim. |
| `test_filemanager_tool_full_cycle` | `FileManagerTool` with `manager_type="fs"`: `create` → `list` → `get_metadata` → `download` → `delete`. Smoke-tests every operation against the upstream backend. |

### Test Data / Fixtures

```python
@pytest.fixture
def tmp_base(tmp_path):
    """Sandbox directory for LocalFileManager smoke tests."""
    return tmp_path

@pytest.fixture
def upstream_local(tmp_base):
    from navigator.utils.file import LocalFileManager
    return LocalFileManager(base_path=tmp_base)
```

---

## 5. Acceptance Criteria

- [ ] `pyproject.toml` requires `navigator-api[uvloop,locale]>=2.14.1`.
- [ ] `parrot/interfaces/file/__init__.py` exports
      `FileManagerInterface`, `FileMetadata`, `LocalFileManager`,
      `TempFileManager` from `navigator.utils.file` (eager) and
      `S3FileManager`, `GCSFileManager` lazily.
- [ ] All five submodule files
      (`abstract.py`, `local.py`, `tmp.py`, `s3.py`, `gcs.py`)
      contain only re-exports of their `navigator.utils.file.<sub>`
      counterparts — no duplicate logic.
- [ ] `parrot.interfaces.file.<X> is navigator.utils.file.<X>`
      holds for every public symbol (identity check, not
      structural).
- [ ] `parrot.tools.filemanager.FileManagerFactory.create(...)`
      delegates to `navigator.utils.file.FileManagerFactory`
      and returns `navigator.utils.file.<X>` instances.
- [ ] `parrot.tools.filemanager.FileManagerTool._create_file`
      no longer relies on `create_from_bytes` returning
      `FileMetadata`; it calls `get_file_metadata` afterwards.
- [ ] All existing tests that import from
      `parrot.interfaces.file*` keep passing without code edits
      (or with edits limited to mock spec lists).
- [ ] New tests in Module 6 all pass.
- [ ] `grep -rn "class FileManagerInterface\|class FileMetadata" packages/ai-parrot/src/parrot/`
      returns **zero matches** — proving the duplicate definition
      is gone.
- [ ] `grep -rn "class LocalFileManager\|class TempFileManager\|class S3FileManager\|class GCSFileManager" packages/ai-parrot/src/parrot/`
      returns **zero matches**.
- [ ] No breaking change to any public symbol exported from
      `parrot.interfaces.file`.

---

## 6. Codebase Contract

> Anti-Hallucination Anchor — every entry below was verified by
> reading source on 2026-04-25.

### Verified Imports

```python
# Upstream (single source of truth after migration)
from navigator.utils.file import (
    FileManagerInterface,        # navigator/utils/file/abstract.py:36
    FileMetadata,                # navigator/utils/file/abstract.py:16
    LocalFileManager,            # navigator/utils/file/local.py:22
    TempFileManager,             # navigator/utils/file/tmp.py (verified at runtime)
    FileManagerFactory,          # navigator/utils/file/factory.py:14
    FileServingExtension,        # navigator/utils/file/web.py:28  (out of scope here)
)
# Lazy:
from navigator.utils.file import S3FileManager   # navigator/utils/file/s3.py:35
from navigator.utils.file import GCSFileManager  # navigator/utils/file/gcs.py:34

# ai-parrot — current (pre-migration) imports that MUST keep working
from parrot.interfaces.file import (
    FileManagerInterface, FileMetadata,
    LocalFileManager, TempFileManager,
)                                               # __init__.py:10-12
from parrot.interfaces.file import S3FileManager, GCSFileManager  # lazy via __getattr__:29-35
from parrot.interfaces.file.abstract import FileManagerInterface  # storage/overflow.py:17
from parrot.interfaces.file.tmp import TempFileManager            # handlers/stores/handler.py:16
from parrot.interfaces.file.s3 import S3FileManager               # storage/s3_overflow.py:13
from parrot.interfaces.file.local import LocalFileManager         # storage/backends/__init__.py:133
from parrot.interfaces.file.s3 import S3FileManager               # storage/backends/__init__.py:146
from parrot.interfaces.file.gcs import GCSFileManager             # storage/backends/__init__.py:149
from parrot.interfaces.file.tmp import TempFileManager            # storage/backends/__init__.py:154
```

### Existing Class Signatures (relevant slices)

```python
# navigator/utils/file/abstract.py
@dataclass
class FileMetadata:                          # line 16
    name: str
    path: str
    size: int
    content_type: Optional[str]
    modified_at: Optional[datetime]
    url: Optional[str]

class FileManagerInterface(ABC):             # line 36
    # 9 abstract methods identical in name + signature to ai-parrot's:
    async def list_files(...) -> List[FileMetadata]                # line 53
    async def get_file_url(...) -> str                              # line 67
    async def upload_file(...) -> FileMetadata                      # line 79
    async def download_file(...) -> Path                            # line 93
    async def copy_file(...) -> FileMetadata                        # line 107
    async def delete_file(...) -> bool                              # line 119
    async def exists(...) -> bool                                   # line 130
    async def get_file_metadata(...) -> FileMetadata                # line 141
    async def create_file(path, content) -> bool                    # line 155
    # Folder ops with NotImplementedError defaults:
    async def create_folder(...) -> None                            # line 170
    async def remove_folder(...) -> None                            # line 183
    async def rename_folder(...) -> None                            # line 196
    async def rename_file(...) -> None                              # line 212
    # Concrete helpers:
    async def create_from_text(path, text, encoding="utf-8") -> bool        # line 230
    async def create_from_bytes(path, data) -> bool                          # line 245   ← RETURNS bool
    async def find_files(keywords, extension, prefix) -> List[FileMetadata]  # line 265
```

```python
# navigator/utils/file/local.py
class LocalFileManager(FileManagerInterface):  # line 22
    manager_name: str = "localfile"            # line 39 (NEW vs ai-parrot)
    def __init__(self, base_path=None,
                 create_base=True,
                 follow_symlinks=False,
                 sandboxed=True) -> None       # line 41 — same signature as ai-parrot's
    # ...
    def setup(self, app, route="/data", base_url=None)   # line 376 (NEW)
    async def handle_file(self, request)                  # line 398 (NEW)
```

```python
# navigator/utils/file/factory.py
class FileManagerFactory:                                   # line 14
    _EAGER_MANAGERS = {"local": (".local","LocalFileManager"),
                       "temp":  (".tmp",  "TempFileManager")}    # line 30
    _LAZY_MANAGERS  = {"s3": (".s3","S3FileManager"),
                       "gcs": (".gcs","GCSFileManager")}         # line 36
    @staticmethod
    def create(manager_type: str, **kwargs) -> FileManagerInterface  # line 42
        # Note: keys are "local" not "fs"
```

```python
# parrot/tools/filemanager.py — current (pre-migration)
class FileManagerFactory:                                   # line 17  ← TO BE DELEGATED
    @staticmethod
    def create(manager_type: Literal["fs","temp","s3","gcs"],
               **kwargs) -> FileManagerInterface            # line 21
        # current body branches on manager_type and instantiates from
        # parrot.interfaces.file.* directly.

class FileManagerTool(AbstractTool):                        # line 118
    name: str = "file_manager"                              # line 139
    async def _create_file(self, args) -> Dict[str, Any]:   # line 439
        # line 453 currently does:
        #     metadata = await self.manager.create_from_bytes(dest, BytesIO(...))
        # ← will break after migration; adapt to call get_file_metadata afterwards.
```

```python
# parrot/storage/overflow.py
class OverflowStore:                                        # line 20
    def __init__(self, file_manager: FileManagerInterface): # line 35
    # line 67 calls await self._fm.create_from_bytes(ref_key, json_bytes)
    #         and DISCARDS the return value → migration-safe.
```

```python
# parrot/clients/google/generation.py
# Lines 2158, 2211, 2229, 2340 each do:
#   await file_manager.create_from_bytes(<key>, <bytes>)
# All 4 callsites discard the return value → migration-safe.
```

### Integration Points

| New / Edited Component | Connects To | Via | Verified At |
|---|---|---|---|
| `parrot/interfaces/file/__init__.py` (shim) | `navigator.utils.file.*` | re-export | `__init__.py:10-12, 29-35` (current); to be replaced |
| `parrot/interfaces/file/abstract.py` (shim) | `navigator.utils.file.abstract` | `from navigator.utils.file.abstract import *` | new |
| `parrot/interfaces/file/{local,tmp,s3,gcs}.py` (shim) | `navigator.utils.file.{local,tmp,s3,gcs}` | re-export | new |
| `parrot/tools/filemanager.py:FileManagerFactory.create` | `navigator.utils.file.FileManagerFactory.create` | static call, `"fs"→"local"` mapping | `filemanager.py:21` (edit) |
| `parrot/tools/filemanager.py:FileManagerTool._create_file` | `manager.get_file_metadata(dest)` | replaces reliance on bool return | `filemanager.py:453` (edit) |
| `pyproject.toml` `navigator-api` pin | `>=2.14.1` | dependency declaration | `pyproject.toml` (current pin `>=2.13.5`) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.interfaces.file.factory`~~ — no factory module under
  ai-parrot. The factory currently lives in
  `parrot/tools/filemanager.py:17`.
- ~~`parrot.interfaces.file.web`~~ — ai-parrot has **no**
  `FileServingExtension` equivalent. Out of scope here.
- ~~`navigator.utils.file.FileManagerFactory.create("fs", ...)`~~ —
  upstream factory uses key `"local"`, not `"fs"`. The mapping
  must happen in the parrot-level shim factory.
- ~~`LocalFileManager.create_from_bytes(...)` returns `FileMetadata`~~ —
  the upstream override (`navigator.utils.file.local`) does **not**
  override `create_from_bytes`; it inherits the abstract default
  that returns `bool`. The `FileMetadata`-returning override is
  ai-parrot-only and disappears with the migration.
- ~~`AWS_CREDENTIALS[...]['aws_access_key_id']`~~ — both
  `parrot.conf.AWS_CREDENTIALS` and `navigator.conf.AWS_CREDENTIALS`
  use `aws_key`/`aws_secret`, not the boto-style names. The
  ai-parrot `S3FileManager` reading `aws_access_key_id` was always
  reading `None` and silently relying on the AWS default
  credential chain.
- ~~`navigator.utils.file.LocalFileManager.create_from_bytes` override~~ —
  not present (verified by reading `navigator/utils/file/local.py`,
  no override after `create_file` line 309).
- ~~`parrot.interfaces.file.find_files`~~ — pre-migration
  `FileManagerInterface` does **not** define `find_files`. After
  migration it gains the upstream default. Code that wants to
  rely on it must do so post-migration.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Shim style**: each `parrot/interfaces/file/<sub>.py` should be
  a one-liner using `from navigator.utils.file.<sub> import *` plus
  an `__all__` mirroring the public symbols. Avoid star-import
  side effects by listing names explicitly when the module has
  many helpers (e.g., `local.py` exports `LocalFileManager` only).
- **Lazy cloud loading**: keep the existing `__getattr__` lazy
  pattern in `parrot/interfaces/file/__init__.py` so importing
  `parrot.interfaces.file` does not load `aioboto3` or
  `google-cloud-storage`. Upstream's `__init__.py` already does
  this; the shim can simply re-import its `__getattr__` or
  replicate the pattern.
- **`FileManagerFactory` adapter**: the parrot-level factory is
  the only place that translates `"fs" → "local"`. Keep the
  `Literal` type annotation for IDE completion. Forward all
  `**kwargs` untouched — upstream signatures match.
- **Async-first**: nothing changes here; both fork and upstream
  are already async-first.

### Known Risks / Gotchas

1. **Behavioural drift in `create_from_bytes`** — The most
   subtle risk. ai-parrot's `LocalFileManager.create_from_bytes`
   accepts an `encoding` keyword and treats `StringIO` specially
   (writes via text-mode `open()`). Upstream's interface default
   does `data.getvalue().encode("utf-8")` for `StringIO` and
   writes via `create_file` (binary). Net result for callers:
   *bytes-on-disk are identical for UTF-8 input* but the encoding
   kwarg goes away. **Mitigation**: scan codebase for
   `create_from_bytes(...encoding=...)`. Currently only the
   abstract method declares it; no callsite passes it (verified
   `grep -rn 'create_from_bytes' packages/ai-parrot/src`).
2. **`MagicMock(spec=FileManagerInterface)` test breakage** — the
   upstream class adds `find_files`, `create_folder`,
   `remove_folder`, `rename_folder`, `rename_file` on the
   abstract class. Mocks built with `spec=` will gain these
   attributes; tests that patch behaviour by name keep working,
   tests that assert the spec list explicitly may need updates.
3. **navigator-api 3.0.0 vs 2.14.1** — the locally installed
   navigator-api reports version `3.0.0` (likely a pre-release
   editable install). The first **published** version that ships
   `navigator/utils/file/` is `2.14.1` per local git tags.
   The `pyproject.toml` pin must be `>=2.14.1`, not `>=3.0.0`,
   unless we explicitly want to wait for a 3.x release. See Open
   Question 1.
4. **Diamond imports** — `navigator.utils.file.web` imports
   `navigator.applications.base.BaseApplication` and
   `navigator.types.WebApp`. The `BaseApplication` import is
   already lazy (deferred to `setup()`) so importing
   `navigator.utils.file` does not pull in the aiohttp app stack.
   No action needed; just be aware if introducing
   `FileServingExtension` later.
5. **`packages/ai-parrot-tools/src/parrot_tools/file/__init__.py`** —
   already a re-export from `parrot.interfaces.file`. Once the
   shim points upstream, this file follows transparently. No edit
   needed; just keep the file as a witness that imports work.
6. **AWS S3 credentials regression** — upstream resolves
   `creds["aws_key"]` (matching `parrot.conf.AWS_CREDENTIALS`),
   while ai-parrot's S3FileManager reads
   `credentials.get('aws_access_key_id')` (always `None` against
   the actual config). After migration, S3 will start picking up
   the configured credentials instead of the AWS default chain.
   This is an *improvement* but it can change behaviour for
   environments that relied on the IAM/instance role fallback —
   document in CHANGELOG.
7. **Build artifacts** — `packages/ai-parrot/build/lib.linux-x86_64-cpython-311/parrot/interfaces/file/`
   contains stale copies of the old code. Not a runtime risk
   (not on `sys.path`) but should be cleaned in CI to avoid
   confusion. Out of scope unless it bites.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-api[uvloop,locale]` | `>=2.14.1` | Provides `navigator.utils.file/` — the new single source of truth. |

No new SDKs are introduced. `aioboto3` / `google-cloud-storage`
remain optional (lazy-loaded) and continue to live as
sub-dependencies pulled in only when S3/GCS are used.

---

## 8. Open Questions

- [ ] **Q1 — navigator-api version pin floor.** Should
      `pyproject.toml` pin `navigator-api[uvloop,locale]>=2.14.1`
      (first published tag with the file module), or wait for /
      align with a `3.x` release? — *Owner: Jesus*: align with 3.x release.
- [ ] **Q2 — Hard switch vs shim.** This spec assumes a **shim**
      under `parrot.interfaces.file` that preserves all current
      import paths. Confirm this is preferred over a hard switch
      that deletes `parrot.interfaces.file/` outright and forces
      every internal callsite (storage backends, handlers, tools,
      tests) to import from `navigator.utils.file` directly.
      Trade-off: shim = zero downstream churn, slightly more
      indirection; hard switch = cleaner, ~10 callsite edits.
      — *Owner: Jesus*: hard switch
- [ ] **Q3 — `create_from_bytes` return-type adapter location.**
      The proposed Module 4 fix calls `get_file_metadata(dest)`
      after `create_from_bytes`. Acceptable? Alternative: file a
      PR upstream to make `create_from_bytes` return
      `FileMetadata` like `upload_file` does, and gate this
      migration on that PR landing. — *Owner: Jesus*: file a PR upstream to make `create_from_bytes` return `FileMetadata` like `upload_file` does, and gate this migration on that PR landing.
- [ ] **Q4 — `parrot.tools.filemanager.FileManagerFactory` fate.**
      Module 5 keeps it as a thin delegating wrapper. Alternative:
      delete it entirely and have `FileManagerTool._create_manager`
      call `navigator.utils.file.FileManagerFactory.create` directly,
      with the `"fs"→"local"` mapping inlined. The wrapper is
      kept for backward compat (any external caller of
      `parrot.tools.filemanager.FileManagerFactory`?). Confirm or
      drop. — *Owner: Jesus*: drop it entirely.
- [ ] **Q5 — `FileServingExtension` adoption.** Out of scope here,
      but does ai-parrot want to use the upstream
      `FileServingExtension` for any HTTP file-serving handler
      (e.g., persisted artifacts, video reels)? If yes, file a
      follow-up spec; if no, drop the line in §1 Non-Goals.
      — *Owner: Jesus*: in scope, we should use it.

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` (sequential tasks in a
  single worktree). The tasks are tightly coupled — Module 2 has
  to land before any consumer-facing module compiles cleanly.
- **No parallelism opportunities** worth splitting; total
  diff is small (≈ 6 files edited, 5 files reduced to one-line
  shims, 1 dependency bump, 1 new test file).
- **Cross-feature dependencies**: none. `navigator-api>=2.14.1`
  is already published and used elsewhere.
- **Recommended worktree command** after spec is approved and
  decomposed:

  ```bash
  git checkout dev
  git worktree add -b feat-123-fileinterface-migration \
    .claude/worktrees/feat-123-fileinterface-migration HEAD
  cd .claude/worktrees/feat-123-fileinterface-migration
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-25 | Jesus Lara | Initial draft. No prior brainstorm. Scaffolded directly from `/sdd-spec` free-form notes plus codebase + upstream research. |
