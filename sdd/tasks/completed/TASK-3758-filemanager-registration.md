# TASK-3758: Registration — lazy shim exports, parrot-native factory keys, manager_type literals

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3756, TASK-3757
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 5**, AC10 (lazy imports, no msgraph leak) and AC11 (factory + literals), design research S11. The two
managers become discoverable everywhere a file manager is: `from parrot.interfaces.file import SharePointFileManager`,
the `parrot_tools.file` parity shim, `FileManagerFactory.create("sharepoint" | "onedrive")`, and the
`manager_type` literals of `FileManagerTool` / `FileManagerToolkit`.

These managers are **parrot-native** (not navigator-api re-exports), so the factory resolves them from a local
`_PARROT_NATIVE` map with `importlib` and never forwards them upstream (the upstream factory would raise `ValueError`).

This task is the first of three edits to `parrot/tools/filemanager.py` (then TASK-3759, TASK-3760 — serialized).

---

## Scope

- `parrot/interfaces/file/__init__.py`: add both names to `__all__` and `_LAZY_MANAGERS` (module targets
  `parrot.interfaces.file.sharepoint` / `.onedrive`).
- `parrot_tools/file/__init__.py`: add both names to `__all__` and widen the lazy branch.
- `parrot/tools/filemanager.py`: `import importlib`; module-level `ManagerType` alias; `_PARROT_NATIVE` map and the new
  `create` body; replace the three `Literal["fs", "temp", "s3", "gcs"]` annotations with `ManagerType`; update the
  tool description string and the toolkit's "Supported backends" docstring.
- `test_file_shim.py`: extend the lazy/leak/factory tests.

**NOT in scope**: the `find` / `batch_*` operations (TASK-3759, TASK-3760); `_create_manager` bodies (their `else:`
branch already forwards `**kwargs` unchanged — `filemanager.py:237`, `:644`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` | MODIFY | lazy exports |
| `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py` | MODIFY | parity shim |
| `packages/ai-parrot/src/parrot/tools/filemanager.py` | MODIFY | factory + literals + description |
| `packages/ai-parrot/tests/interfaces/test_file_shim.py` | MODIFY | extended shim/factory tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
from parrot.interfaces.file.sharepoint import SharePointFileManager   # created by TASK-3756
from parrot.interfaces.file.onedrive import OneDriveFileManager       # created by TASK-3757
import importlib                                                     # stdlib (not yet imported by filemanager.py)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/file/__init__.py
__all__ = (... "S3FileManager", "GCSFileManager",)                 # :25-32
_LAZY_MANAGERS = {"S3FileManager": "navigator.utils.file.s3", "GCSFileManager": "navigator.utils.file.gcs"}   # :34-37
def __getattr__(name: str)                                           # :40-46 — importlib.import_module(_LAZY_MANAGERS[name]); setattr cache

# packages/ai-parrot-tools/src/parrot_tools/file/__init__.py
__all__ = (..., "GCSFileManager",)                                   # :9-16
def __getattr__(name: str):                                          # :19
    if name in ("S3FileManager", "GCSFileManager"):                  # :21
        from parrot.interfaces import file as _file; return getattr(_file, name)

# packages/ai-parrot/src/parrot/tools/filemanager.py
from io import BytesIO                                               # :12
import logging                                                       # :13
class FileManagerFactory:                                            # :22
    _PARROT_TO_UPSTREAM = {"fs": "local", "temp": "temp", "s3": "s3", "gcs": "gcs"}   # :30-35
    @staticmethod
    def create(manager_type: Literal["fs", "temp", "s3", "gcs"], **kwargs: Any) -> FileManagerInterface:   # :37-62
        # try: upstream_key = FileManagerFactory._PARROT_TO_UPSTREAM[manager_type]  (:56)
        # except KeyError: raise ValueError(f"Unknown manager type: {manager_type}. Available: {sorted(...)}")  (:58-61)
        # return _UpstreamFileManagerFactory.create(upstream_key, **kwargs)  (:62)
    description: str = "Manage files across different storage backends (local, S3, GCS, temp)"   # :169 (FileManagerTool)
    manager_type: Literal["fs", "temp", "s3", "gcs"] = "fs",         # :174 (FileManagerTool.__init__) and :551 (FileManagerToolkit.__init__)
    # FileManagerToolkit docstring "Supported backends:" block :533-537 (last line :537 is the gcs bullet)
    # FileManagerToolkit.__init__ docstring: "manager_type: Storage backend — one of ``"fs"``, ``"temp"``," (:561)

# packages/ai-parrot/tests/interfaces/test_file_shim.py
def test_no_cloud_sdk_leak_on_import():                              # :29 — reload(shim); asserts aioboto3/gcs not in sys.modules
def test_lazy_identity():                                            # :42
def test_factory_unknown_type_raises_valueerror():                   # :90 — asserts "xyz" in msg or "Unknown" in msg
```

### Does NOT Exist
- ~~`navigator.utils.file.FileManagerFactory.create("sharepoint")`~~ — upstream raises ValueError; never forward these.
- ~~`FileManagerFactory._LAZY_MANAGERS`~~ on the parrot-side class — the new map is `_PARROT_NATIVE`.
- ~~`parrot.interfaces.file.SharePointFileManager` as an eager import~~ — must stay lazy (AC10).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/file/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/tools/filemanager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_file_shim.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerFactory.create",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerTool.__init__",
    "sym:packages/ai-parrot/src/parrot/tools/filemanager.py#FileManagerToolkit.__init__"
  ]
}
```

---

## Implementation Notes

- The `ValueError` for an unknown key lists ALL six keys: `sorted({**_PARROT_TO_UPSTREAM, **_PARROT_NATIVE})` (AC11).
  Keep the `"Unknown manager type: …"` prefix — the existing test matches on it.
- Keep `create(manager_type, **kwargs)` as a `@staticmethod` with that exact parameter shape:
  `tests/tools/test_filemanager_toolkit.py:68` monkeypatches it with `def create(manager_type: str, **kwargs)`.
- The `msgraph` leak test mirrors `test_no_cloud_sdk_leak_on_import`: skip when `msgraph` is already in `sys.modules`
  (another test imported it), otherwise `importlib.reload(shim)` and assert `"msgraph"` and
  `"parrot.interfaces.file.graph"` are absent. Name it so it sorts/defines BEFORE any test touching the new managers.

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
1. Core shim, then the tools shim — *why*: `parrot_tools.file` delegates to the core shim.
2. `filemanager.py`: import, alias, factory, literals, strings — *why*: TASK-3759/3760 build on `ManagerType`.
3. Tests.

### `packages/ai-parrot/src/parrot/interfaces/file/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "GCSFileManager",' parrot/interfaces/file/__init__.py) — line :31, inside __all__
# AFTER — insert below `    "GCSFileManager",` (verified: file/__init__.py:31)
    "SharePointFileManager",
    "OneDriveFileManager",

# occurrences: 1 (verified: grep -c '    "GCSFileManager": "navigator.utils.file.gcs",' parrot/interfaces/file/__init__.py) — :36
# AFTER — insert below `    "GCSFileManager": "navigator.utils.file.gcs",`
    # Parrot-native Graph managers (FEAT-603) — lazy so importing this package never loads msgraph.
    "SharePointFileManager": "parrot.interfaces.file.sharepoint",
    "OneDriveFileManager": "parrot.interfaces.file.onedrive",
```
Also update the module docstring's "Lazy re-exports:" line to mention the two new managers (FILL IN: one line).

### `packages/ai-parrot-tools/src/parrot_tools/file/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "GCSFileManager",' parrot_tools/file/__init__.py) — :15
# AFTER — insert below `    "GCSFileManager",`
    "SharePointFileManager",
    "OneDriveFileManager",

# occurrences: 1 (verified: grep -c '    if name in ("S3FileManager", "GCSFileManager"):' parrot_tools/file/__init__.py) — :21
# REPLACE that line with:
    if name in ("S3FileManager", "GCSFileManager", "SharePointFileManager", "OneDriveFileManager"):
```
FILL IN: update the `__getattr__` docstring to "Lazy re-export cloud managers from core."

### `packages/ai-parrot/src/parrot/tools/filemanager.py` (MODIFY) — import, alias, factory
```python
# occurrences: 1 (verified: grep -c '^import logging$' parrot/tools/filemanager.py) — :13
# BEFORE — insert above `import logging`
import importlib

# occurrences: 1 (verified: grep -c '^class FileManagerFactory:$' parrot/tools/filemanager.py) — :22
# BEFORE — insert above `class FileManagerFactory:`
ManagerType = Literal["fs", "temp", "s3", "gcs", "sharepoint", "onedrive"]


# occurrences: 1 (verified: grep -c '    _PARROT_TO_UPSTREAM = {' parrot/tools/filemanager.py) — :30
# FILL IN: disambiguate — REPLACE the whole `create` staticmethod (:37-62, from `    @staticmethod` directly below the
#          `_PARROT_TO_UPSTREAM` dict through `return _UpstreamFileManagerFactory.create(upstream_key, **kwargs)`) with:
    # Parrot-native managers resolved locally (never forwarded upstream, which does not know them) — FEAT-603.
    _PARROT_NATIVE = {
        "sharepoint": ("parrot.interfaces.file.sharepoint", "SharePointFileManager"),
        "onedrive": ("parrot.interfaces.file.onedrive", "OneDriveFileManager"),
    }

    @staticmethod
    def create(manager_type: ManagerType, **kwargs: Any) -> FileManagerInterface:
        """Create a file manager instance.

        Args:
            manager_type: ``"fs"``, ``"temp"``, ``"s3"``, ``"gcs"`` (upstream navigator managers) or ``"sharepoint"``,
                ``"onedrive"`` (parrot-native Microsoft Graph managers, lazily imported).
            **kwargs: Forwarded to the manager constructor.

        Returns:
            A FileManagerInterface instance.

        Raises:
            ValueError: If ``manager_type`` is not recognised (the message lists every valid key).
        """
        native = FileManagerFactory._PARROT_NATIVE.get(manager_type)
        if native is not None:
            module_path, class_name = native
            return getattr(importlib.import_module(module_path), class_name)(**kwargs)
        try:
            upstream_key = FileManagerFactory._PARROT_TO_UPSTREAM[manager_type]
        except KeyError:
            available = sorted({**FileManagerFactory._PARROT_TO_UPSTREAM, **FileManagerFactory._PARROT_NATIVE})
            raise ValueError(f"Unknown manager type: {manager_type}. Available: {available}") from None
        return _UpstreamFileManagerFactory.create(upstream_key, **kwargs)
```

### `packages/ai-parrot/src/parrot/tools/filemanager.py` (MODIFY) — literals and strings
```python
# occurrences: 3 (verified: grep -c 'manager_type: Literal\["fs", "temp", "s3", "gcs"\]' parrot/tools/filemanager.py) — :39 (replaced above), :174, :551
# FILL IN: disambiguate — in `class FileManagerTool(AbstractTool):` `__init__` (:172-174) and in
#          `class FileManagerToolkit(AbstractToolkit):` `__init__` (:549-551) REPLACE
#          `manager_type: Literal["fs", "temp", "s3", "gcs"] = "fs",` with `manager_type: ManagerType = "fs",`
#          After the edit `grep -c 'Literal\["fs", "temp", "s3", "gcs"\]'` must be 0.

# occurrences: 1 (verified: grep -c 'description: str = "Manage files across different storage backends (local, S3, GCS, temp)"') — :169
# REPLACE with:
    description: str = "Manage files across different storage backends (local, S3, GCS, SharePoint, OneDrive, temp)"

# occurrences: 1 (verified: grep -c '      - ``"gcs"``  — Google Cloud Storage (requires google-cloud-storage)') — :537
# AFTER — insert below that docstring bullet (FileManagerToolkit "Supported backends:")
      - ``"sharepoint"`` — SharePoint document library (requires ai-parrot[msgraph])
      - ``"onedrive"`` — a user's OneDrive (requires ai-parrot[msgraph])
```
FILL IN: in the `FileManagerToolkit.__init__` docstring (:561-562) add ``"sharepoint"``, ``"onedrive"`` to the
`manager_type` description; same for `FileManagerTool.__init__`'s docstring.

### `packages/ai-parrot/tests/interfaces/test_file_shim.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_lazy_identity():' tests/interfaces/test_file_shim.py) — :42
# BEFORE — insert above `def test_lazy_identity():` (after test_no_cloud_sdk_leak_on_import)
def test_no_msgraph_leak_on_import():
    """Importing parrot.interfaces.file does not load msgraph or the Graph managers (FEAT-603 AC10)."""
    if "msgraph" in sys.modules or "parrot.interfaces.file.graph" in sys.modules:
        pytest.skip("msgraph already loaded by a prior test")
    importlib.reload(shim)
    assert "msgraph" not in sys.modules
    assert "parrot.interfaces.file.graph" not in sys.modules


# occurrences: 1 (verified: grep -c 'def test_factory_unknown_type_raises_valueerror():' tests/interfaces/test_file_shim.py) — :90
# AFTER — append at the end of the file
def test_shim_exports_new_managers_lazily():
    # FILL IN: shim.SharePointFileManager / OneDriveFileManager are the classes from parrot.interfaces.file.sharepoint /
    #          .onedrive; both names in shim.__all__


def test_parrot_tools_file_shim_parity():
    # FILL IN: parrot_tools.file.SharePointFileManager is shim.SharePointFileManager (same for OneDrive)


def test_factory_sharepoint_and_onedrive_native():
    # FILL IN: FileManagerFactory.create("sharepoint", site="TeamSite") is a SharePointFileManager (no I/O at init);
    #          create("onedrive", user="me") is a OneDriveFileManager


def test_factory_unknown_lists_all_keys():
    # FILL IN: message contains all six keys


def test_toolkit_literal_accepts_new_types(monkeypatch):
    # FILL IN: FileManagerToolkit(manager_type="sharepoint", site="TeamSite") builds; tools generated; no network
```

### FILL IN checklist
- [ ] docstring touch-ups in both shims and in `filemanager.py`
- [ ] the two `Literal` replacements (disambiguated by class)
- [ ] new test bodies

---

## Acceptance Criteria

- [ ] `from parrot.interfaces.file import SharePointFileManager, OneDriveFileManager` and the `parrot_tools.file`
      parity import work; importing either shim does not load `msgraph` (spec AC10).
- [ ] `FileManagerFactory.create("sharepoint" | "onedrive", **kwargs)` resolves locally; unknown keys raise
      `ValueError` listing all six keys; both literals accept the new values (spec AC11).
- [ ] `grep -c 'Literal\["fs", "temp", "s3", "gcs"\]' parrot/tools/filemanager.py` is 0.
- [ ] Existing `test_file_shim.py` and `tests/tools/test_filemanager_toolkit.py` still pass.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_file_shim.py -q`
- `pytest tests/tools/test_filemanager_toolkit.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_no_msgraph_leak_on_import` | AC10 laziness |
| `test_shim_exports_new_managers_lazily` / `test_parrot_tools_file_shim_parity` | AC10 exports |
| `test_factory_sharepoint_and_onedrive_native` / `test_factory_unknown_lists_all_keys` | AC11 |
| `test_toolkit_literal_accepts_new_types` | AC11 literals |

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


- Task: TASK-3758
- Feature: sharepoint-filemanager
- Implementation SHA: 0da7211382fe75a037d21d494114449a7ec22f37
- Closed at (UTC): 2026-09-25T19:47:33+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| known_deviation | SharePointFileManager/OneDriveFileManager are still abstract at this point in the dependency graph (write-ops land in sibling TASK-3752/3753/3754, not in this task's depends_on). Two new tests use monkeypatch.setattr(Class, '__abstractmethods__', frozenset()) to exercise factory/toolkit dispatch without depending on unmerged siblings; auto-restoring, test-scope only, no source file touched. |
| merge_tier_gate_note | This merge-tier run escalated far wider than earlier chunks (touches shared parrot.interfaces.file / parrot_tools.file shims), sweeping most workspace distributions. All failures found are pre-existing and unrelated to this feature: the same 18 known ai-parrot collection errors, plus unrelated failures in parrot-formdesigner (venue service, slug collision, version bump), ai-parrot-client-grok (multiround usage accounting), and ai-parrot-integrations. None touch sharepoint/onedrive/graph/filemanager code. Tracked as pre-existing debt (FEAT-604 draft covers the escalation-cost side). |
| scoped_test_result | tests/tools/test_filemanager_toolkit.py: 132 passed, 1 skipped (root distribution invocation within this same merge-tier run). test_file_shim.py (this task's other declared validation command) remains uncollectable due to the same pre-existing conftest.py sys.modules-race bug already tracked (independently reproduced on plain dev with zero FEAT-603 code present); its 5 new/modified assertions were verified directly via PYTHONPATH python3 -c invocation instead, all passing (registration exports resolve, lazy, factory dispatch, unknown-key error message, toolkit tool count). |
| seat_summary | Seat: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: n/a · Tokens: n/a |
