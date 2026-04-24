# TASK-851: Replace parrot.interfaces.file with re-export shim over navigator.utils.file

**Feature**: FEAT-123 — fileinterface-migration
**Spec**: `sdd/specs/fileinterface-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-850
**Assigned-to**: unassigned

---

## Context

Today `packages/ai-parrot/src/parrot/interfaces/file/` contains a
full duplicate of the `FileManagerInterface` family
(`abstract.py`, `local.py`, `tmp.py`, `s3.py`, `gcs.py`,
`__init__.py`). Upstream `navigator-api` now ships the homologated
version under `navigator/utils/file/`. This task collapses the
local duplicate to thin re-export shims so that:

1. `from parrot.interfaces.file import X` keeps working for
   every public symbol.
2. Submodule imports (`from parrot.interfaces.file.abstract import …`,
   `… .local`, `… .tmp`, `… .s3`, `… .gcs`) keep working — they
   are used directly by `parrot.storage.overflow`,
   `parrot.storage.s3_overflow`, `parrot.storage.backends`, and
   `parrot.handlers.stores.handler`.
3. `S3FileManager` / `GCSFileManager` remain **lazy-imported** at
   the package root so importing `parrot.interfaces.file` does
   not pull in `aioboto3` or `google-cloud-storage`.

Implements **Modules 2 and 3** of the spec.

---

## Scope

- Replace `packages/ai-parrot/src/parrot/interfaces/file/__init__.py`
  with a shim that:
  - Eagerly re-exports `FileManagerInterface`, `FileMetadata`,
    `LocalFileManager`, `TempFileManager` from
    `navigator.utils.file`.
  - Keeps the existing `__getattr__` lazy pattern so
    `parrot.interfaces.file.S3FileManager` and
    `parrot.interfaces.file.GCSFileManager` import lazily from
    `navigator.utils.file.s3` / `navigator.utils.file.gcs` on
    first access, and cache the result in
    `sys.modules[__name__]` for subsequent access.
  - Preserves the current `__all__` tuple verbatim (same names,
    same order).
- Replace each of these files with a one-purpose re-export shim
  whose entire body is a `from navigator.utils.file.<sub> import …`
  followed by an `__all__` tuple:
  - `abstract.py` → exports `FileManagerInterface`, `FileMetadata`.
  - `local.py` → exports `LocalFileManager`.
  - `tmp.py` → exports `TempFileManager`.
  - `s3.py` → exports `S3FileManager`.
  - `gcs.py` → exports `GCSFileManager`.
- After editing, run a manual smoke check from the activated
  venv (see Test Specification below).

**NOT in scope**:
- Editing `parrot/tools/filemanager.py` (TASK-852).
- Writing the new shim tests (TASK-853).
- Editing existing tests under `tests/storage/` or
  `tests/test_video_reel_storage.py` (TASK-854 — only if they
  fail).
- Touching `pyproject.toml` (TASK-850 already did).
- Adopting `FileServingExtension` (out of scope — see spec §1
  Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` | MODIFY | Replace local re-exports with re-exports from `navigator.utils.file`; keep lazy `__getattr__` for S3/GCS. |
| `packages/ai-parrot/src/parrot/interfaces/file/abstract.py` | MODIFY | One-purpose re-export of `FileManagerInterface`, `FileMetadata`. |
| `packages/ai-parrot/src/parrot/interfaces/file/local.py` | MODIFY | One-purpose re-export of `LocalFileManager`. |
| `packages/ai-parrot/src/parrot/interfaces/file/tmp.py` | MODIFY | One-purpose re-export of `TempFileManager`. |
| `packages/ai-parrot/src/parrot/interfaces/file/s3.py` | MODIFY | One-purpose re-export of `S3FileManager`. |
| `packages/ai-parrot/src/parrot/interfaces/file/gcs.py` | MODIFY | One-purpose re-export of `GCSFileManager`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (the SOURCES this shim re-exports from)

```python
# navigator/utils/file/__init__.py — lazy SDK pattern (reference for our shim)
from navigator.utils.file.abstract import FileManagerInterface, FileMetadata
from navigator.utils.file.local import LocalFileManager
from navigator.utils.file.tmp import TempFileManager
from navigator.utils.file.s3 import S3FileManager      # heavy: aioboto3
from navigator.utils.file.gcs import GCSFileManager    # heavy: google-cloud-storage
```

### Verified Imports (the CONSUMERS that must keep working)

```python
# parrot/storage/overflow.py:17
from parrot.interfaces.file.abstract import FileManagerInterface

# parrot/handlers/stores/handler.py:16
from parrot.interfaces.file.tmp import TempFileManager

# parrot/storage/s3_overflow.py:13
from parrot.interfaces.file.s3 import S3FileManager

# parrot/storage/backends/__init__.py:133, 146, 149, 154
from parrot.interfaces.file.local import LocalFileManager
from parrot.interfaces.file.s3 import S3FileManager
from parrot.interfaces.file.gcs import GCSFileManager
from parrot.interfaces.file.tmp import TempFileManager

# parrot/handlers/video_reel.py:27 ; parrot/clients/google/generation.py:52
from parrot.interfaces.file import FileManagerInterface

# parrot/interfaces/__init__.py:13
from .file import FileManagerInterface, FileMetadata

# parrot/tools/filemanager.py:14
from parrot.interfaces.file import FileManagerInterface, LocalFileManager, TempFileManager

# packages/ai-parrot-tools/src/parrot_tools/file/__init__.py:2
from parrot.interfaces.file import FileManagerInterface, FileMetadata, LocalFileManager, TempFileManager
```

### Existing Signatures (current `__init__.py` to be replaced)

```python
# parrot/interfaces/file/__init__.py — current (lines 1–35) — reference
from .abstract import FileManagerInterface, FileMetadata
from .local import LocalFileManager
from .tmp import TempFileManager

__all__ = (
    "FileManagerInterface",
    "FileMetadata",
    "LocalFileManager",
    "TempFileManager",
    "S3FileManager",
    "GCSFileManager",
)

_LAZY_MANAGERS = {
    "S3FileManager": ".s3",
    "GCSFileManager": ".gcs",
}

def __getattr__(name: str):
    if name in _LAZY_MANAGERS:
        mod = importlib.import_module(_LAZY_MANAGERS[name], __name__)
        obj = getattr(mod, name)
        setattr(sys.modules[__name__], name, obj)
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

The new shim must keep the same `__all__` tuple and the same
lazy contract; only the source of the symbols changes (from
local `.abstract` / `.local` / `.tmp` to
`navigator.utils.file.*`).

### Does NOT Exist

- ~~`navigator.utils.file.find_files`~~ as a top-level export —
  `find_files` is a method on `FileManagerInterface`, not a
  module-level function. Do not try to re-export it.
- ~~`navigator.utils.file.abstract.LocalFileManager`~~ — concrete
  managers live in their own submodules
  (`navigator.utils.file.local`, etc.), not in `abstract`.
- ~~`from navigator.utils.file import *`~~ as a shim shortcut —
  upstream's `__init__.py` uses lazy `__getattr__` for S3/GCS,
  so a star import would NOT pull them in. The shim must
  explicitly handle the lazy names; do not rely on `*`.
- ~~`__future__ import annotations` is required~~ — it isn't.
  The current shim file does not use it; do not add it
  speculatively.
- ~~`navigator.utils.file.LocalFileManager.create_from_bytes`
  override returning `FileMetadata`~~ — upstream does NOT
  override `create_from_bytes` in `local.py`; it inherits the
  abstract default that returns `bool`. This is intentional and
  is exactly the API change `_create_file` (TASK-852) adapts
  to. Do not "fix" the shim to restore the old return type.

---

## Implementation Notes

### Pattern to Follow — `__init__.py`

```python
"""File manager interfaces — re-exported from navigator.utils.file.

This module is a backward-compat shim. The single source of truth
is navigator.utils.file (navigator-api ≥ 2.14.1). New code SHOULD
import directly from navigator.utils.file; existing code that
uses parrot.interfaces.file continues to work via this shim.

Eager re-exports: FileManagerInterface, FileMetadata,
                  LocalFileManager, TempFileManager.
Lazy re-exports:  S3FileManager, GCSFileManager — loaded on first
                  access via __getattr__ so importing this package
                  does not pull in aioboto3 or
                  google-cloud-storage.
"""
import importlib
import sys

from navigator.utils.file import (
    FileManagerInterface,
    FileMetadata,
    LocalFileManager,
    TempFileManager,
)

__all__ = (
    "FileManagerInterface",
    "FileMetadata",
    "LocalFileManager",
    "TempFileManager",
    "S3FileManager",
    "GCSFileManager",
)

_LAZY_MANAGERS = {
    "S3FileManager": "navigator.utils.file.s3",
    "GCSFileManager": "navigator.utils.file.gcs",
}


def __getattr__(name: str):
    if name in _LAZY_MANAGERS:
        mod = importlib.import_module(_LAZY_MANAGERS[name])
        obj = getattr(mod, name)
        setattr(sys.modules[__name__], name, obj)
        return obj
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

### Pattern to Follow — `abstract.py`

```python
"""Re-export of navigator.utils.file.abstract for backward compat."""
from navigator.utils.file.abstract import FileManagerInterface, FileMetadata

__all__ = ("FileManagerInterface", "FileMetadata")
```

### Pattern to Follow — `local.py` / `tmp.py` / `s3.py` / `gcs.py`

```python
"""Re-export of navigator.utils.file.<sub> for backward compat."""
from navigator.utils.file.<sub> import <ManagerClass>

__all__ = ("<ManagerClass>",)
```

Concretely:
- `local.py` → `from navigator.utils.file.local import LocalFileManager`
- `tmp.py`   → `from navigator.utils.file.tmp import TempFileManager`
- `s3.py`    → `from navigator.utils.file.s3 import S3FileManager`
- `gcs.py`   → `from navigator.utils.file.gcs import GCSFileManager`

### Key Constraints

- **Identity**: after the shim, `parrot.interfaces.file.X is navigator.utils.file.X`
  must hold for every public symbol. This is the strongest
  proof that the duplicate is gone.
- **Lazy**: simply importing `parrot.interfaces.file` must NOT
  import `aioboto3` or `google.cloud.storage`. Confirm with
  `python -c "import parrot.interfaces.file; import sys; print('aioboto3' in sys.modules, 'google.cloud.storage' in sys.modules)"`
  → both `False`.
- **No new behaviour**: this task is purely structural. Do not
  add new public symbols, do not change `__all__` membership,
  do not introduce new helpers.
- Use `self.logger`-style logging only if you need to debug;
  shims should not log on import.
- Do not add `from __future__ import annotations` unless the
  upstream module uses it — keep imports minimal.

### References in Codebase

- `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` — current shape with lazy `__getattr__`; reuse as a template.
- `~/proyectos/navigator/navigator/navigator/utils/file/__init__.py` — upstream's lazy pattern (informative only; do not import from here).
- `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py` — already a re-export shim from `parrot.interfaces.file`; useful style reference.

---

## Acceptance Criteria

- [ ] `parrot/interfaces/file/__init__.py` re-exports the four
      eager symbols from `navigator.utils.file` and keeps the
      `__all__` tuple unchanged in name and order.
- [ ] `parrot/interfaces/file/{abstract,local,tmp,s3,gcs}.py`
      each contain only a docstring, a single
      `from navigator.utils.file.<sub> import <X>` line, and an
      `__all__` tuple. No class definitions, no method bodies,
      no helper functions.
- [ ] `grep -rn "class FileManagerInterface\|class FileMetadata\|class LocalFileManager\|class TempFileManager\|class S3FileManager\|class GCSFileManager" packages/ai-parrot/src/parrot/`
      returns **zero matches**.
- [ ] `python -c "import parrot.interfaces.file as p, navigator.utils.file as n; assert p.FileManagerInterface is n.FileManagerInterface; assert p.FileMetadata is n.FileMetadata; assert p.LocalFileManager is n.LocalFileManager; assert p.TempFileManager is n.TempFileManager; print('ok')"`
      prints `ok`.
- [ ] `python -c "import parrot.interfaces.file as p, navigator.utils.file as n; assert p.S3FileManager is n.S3FileManager; assert p.GCSFileManager is n.GCSFileManager; print('lazy ok')"`
      prints `lazy ok` (proves lazy `__getattr__` resolves to the
      same upstream class).
- [ ] `python -c "import parrot.interfaces.file; import sys; assert 'aioboto3' not in sys.modules; assert 'google.cloud.storage' not in sys.modules; print('lazy preserved')"`
      prints `lazy preserved` (proves cloud SDKs are NOT pulled
      in by the bare package import).
- [ ] All consumers verified in the Codebase Contract still
      import successfully:
      ```
      python -c "
      from parrot.interfaces.file.abstract import FileManagerInterface
      from parrot.interfaces.file.tmp import TempFileManager
      from parrot.interfaces.file.local import LocalFileManager
      from parrot.interfaces.file import FileManagerInterface, FileMetadata, LocalFileManager, TempFileManager
      print('consumers ok')
      "
      ```
- [ ] No linting errors:
      `ruff check packages/ai-parrot/src/parrot/interfaces/file/`.

---

## Test Specification

The dedicated regression test file lives in TASK-853. This task's
verification is the bash smoke checks in the acceptance criteria.

```bash
source .venv/bin/activate

# 1. Identity check
python - <<'PY'
import parrot.interfaces.file as p
import navigator.utils.file as n
for sym in ("FileManagerInterface", "FileMetadata",
            "LocalFileManager", "TempFileManager"):
    assert getattr(p, sym) is getattr(n, sym), sym
# Lazy attribute access:
for sym in ("S3FileManager", "GCSFileManager"):
    assert getattr(p, sym) is getattr(n, sym), sym
print("identity ok")
PY

# 2. Lazy SDK preserved
python - <<'PY'
import sys
import parrot.interfaces.file  # noqa
assert "aioboto3" not in sys.modules, "aioboto3 leaked into import"
assert "google.cloud.storage" not in sys.modules, "google-cloud-storage leaked"
print("lazy ok")
PY

# 3. Submodule paths still resolve
python - <<'PY'
from parrot.interfaces.file.abstract import FileManagerInterface, FileMetadata  # noqa
from parrot.interfaces.file.tmp import TempFileManager  # noqa
from parrot.interfaces.file.local import LocalFileManager  # noqa
from parrot.interfaces.file.s3 import S3FileManager  # noqa
from parrot.interfaces.file.gcs import GCSFileManager  # noqa
print("submodules ok")
PY
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** — TASK-850 must be in
   `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read the current
   `parrot/interfaces/file/__init__.py` and the upstream
   `navigator.utils.file.__init__` before editing. If the
   upstream has changed (e.g., added a new public symbol), call
   it out in the completion note but do **not** add it to the
   shim's `__all__` in this task — that's a separate change.
4. **Update status** in `sdd/tasks/.index.json` →
   `"in-progress"` with your session ID.
5. **Implement** the six file rewrites following the patterns
   in this task.
6. **Verify** all acceptance criteria, including the three
   smoke checks above.
7. **Move this file** to
   `sdd/tasks/completed/TASK-851-shim-parrot-interfaces-file.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
