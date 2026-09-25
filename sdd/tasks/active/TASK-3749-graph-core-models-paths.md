# TASK-3749: GraphDriveFileManager core — batch models, errors, class shell, path model, metadata mapping

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3748
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1** (first of six tasks that build `parrot/interfaces/file/graph.py`, serialized because they all
edit that file: 3749 → 3750 → 3751 → 3752 → 3753 → 3754) and §2 **Data Models**. This task creates the module with
everything that does no network I/O: the Pydantic models every later task and the toolkit (TASK-3759) import, the error
type, the abstract class with its constructor and hooks, the S3-parity path model and the `DriveItem` → `FileMetadata` /
`DriveEntry` mapping. The class stays abstract; the `FileManagerInterface` methods arrive in 3751–3753.

**Task-time decision (deviation from spec §3 M1 file layout): batch models live in `parrot/interfaces/file/batch.py`.**
`msgraph-sdk` is an *optional* dependency of `ai-parrot` (it is only in the `agents` extra, `pyproject.toml:440-442`, and
the new `msgraph` extra of TASK-3765), and `graph.py` imports msgraph through `parrot.interfaces.o365`. The toolkit's
generic batch fallback (TASK-3759) must work on `fs` / `temp` / `s3` / `gcs` backends WITHOUT msgraph installed, so
`BatchState`, `BatchErrorCode`, `BatchItemResult` and `BatchSummary` go into a msgraph-free `batch.py`, and `graph.py`
re-exports them — every import path the spec names (`from parrot.interfaces.file.graph import BatchItemResult, …`)
keeps working. `DriveEntry` stays in `graph.py` (Graph-only).

---

## Scope

- Create `packages/ai-parrot/src/parrot/interfaces/file/batch.py` (msgraph-free): `BatchState`, `BatchErrorCode`,
  `BatchItemResult`, `BatchSummary`.
- Create `packages/ai-parrot/src/parrot/interfaces/file/graph.py` with: the type aliases, the re-export of the batch
  models, `DriveEntry`, `GraphFileManagerError`, and `GraphDriveFileManager` containing the class constants,
  `__init__`, the abstract hooks `_build_client` / `_resolve_drive_id`, `client_class`, `_prefixed`, `_unprefixed`,
  `_item_ref`, `_item_path`, `_make_metadata`, `_make_entry`, and the `client` / `drive_id` properties.
- Create `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` with the tests of this task (later tasks append).

**NOT in scope**: authentication, retries, URL validation (TASK-3750); any Graph call (3751+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/batch.py` | CREATE | msgraph-free batch models (see Context) |
| `packages/ai-parrot/src/parrot/interfaces/file/graph.py` | CREATE | module, DriveEntry, class shell, path model, mapping |
| `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` | CREATE | unit tests (extended by 3750–3754) |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
from navigator.utils.file import FileManagerInterface, FileMetadata   # verified: .venv/lib/python3.12/site-packages/navigator/utils/file/__init__.py (__all__ :43); abstract.py:36, :16
from parrot.interfaces.o365 import O365Client                         # verified: packages/ai-parrot/src/parrot/interfaces/o365.py:115
from pydantic import BaseModel, ConfigDict, Field                     # pydantic v2
from ._graph_fakes import FakeDrive, FakeDriveItem, FakeGraphClient, make_probe   # tests only; created by TASK-3748
```

### Existing Signatures to Use
```python
# navigator/utils/file/abstract.py (navigator-api 4.0.0)
@dataclass
class FileMetadata:                          # :16
    name: str; path: str; size: int          # :28-30
    content_type: Optional[str]; modified_at: Optional[datetime]; url: Optional[str]   # :31-33
class FileManagerInterface(ABC):             # :36 — 9 abstract async methods (:53-155); see spec §6

# navigator/utils/file/s3.py — parity model for the path helpers
class S3FileManager(FileManagerInterface):   # :35
    manager_name: str = "s3file"             # :49
    def _prefixed(self, key: str) -> str     # :120
    def _unprefixed(self, key: str) -> str   # :124

# packages/ai-parrot/src/parrot/interfaces/sharepoint.py
def _to_colon_id(self, directory: str, name: str) -> str:   # :556 — per-segment quote, "root:/<segs>:" (the rule _item_ref reproduces)
# SharepointClient.small_file_threshold = 4 MiB (:56); chunk_size = 10 MiB (:57)

# Graph DriveItem attributes read by the mapping (msgraph-sdk 1.63 models.drive_item.DriveItem):
#   id, name, size, web_url, folder, file.mime_type, last_modified_date_time, parent_reference.path
#   parent_reference.path looks like "/drive/root:" or "/drives/<id>/root:/a/b"
```

### Does NOT Exist
- ~~`parrot.interfaces.file.graph`~~ / ~~`parrot.interfaces.file.batch`~~ — created by this task.
- ~~`msgraph` as a core dependency of `ai-parrot`~~ — it is optional (`agents` extra); nothing msgraph-free may import
  `graph.py` (hence `batch.py`).
- ~~`FileMetadata.is_folder`~~ / ~~`FileMetadata.id`~~ — the dataclass has only the six fields above; folder/id live on
  the new `DriveEntry` model (spec §2, design research S8).
- ~~`GraphDriveFileManager.connect` / `adopt_client` / `_retrying`~~ — TASK-3750, not here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/batch.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/graph.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/interfaces/test_graph_filemanager.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/o365.py#O365Client",
    "sym:packages/ai-parrot/src/parrot/interfaces/sharepoint.py#SharepointClient._to_colon_id"
  ]
}
```

---

## Implementation Notes

- **Prefix normalisation** (S3 parity): `prefix` becomes `"a/b/"` (no leading slash, exactly one trailing slash) or `""`.
- **Path model**: `_prefixed(key)` → normalise `\\` to `/`, strip leading `/`, raise `ValueError` if any segment is `..`,
  return `prefix + key` (for `key == ""` return `prefix.rstrip("/")`). `_unprefixed(full)` strips the prefix when present.
- **Item refs**: `_item_ref(full_path)` → `"root"` for an empty path, else `"root:/" + "/".join(quote(seg, safe=""))
  + ":"`. `quote(..., safe="")` turns `a b/c#d.txt` into `root:/a%20b/c%23d.txt:` (spec §4).
- **`_item_path(item)`**: drive-relative path from `parent_reference.path` (take the text after the first `"root:"`,
  strip slashes) joined with `item.name`; `None` when `parent_reference.path` is missing (search results often omit it —
  TASK-3751 resolves those by id).
- The constants on the class are the spec's §3 M1 skeleton values; do not rename them — later tasks and tests read them.

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
1. Write `batch.py`, then the `graph.py` header, aliases, re-export and `DriveEntry` — *why*: TASK-3759 imports the
   batch models msgraph-free, and TASK-3761/3763 build responses from `DriveEntry`; names and fields are the spec §2
   contract.
2. Write `GraphFileManagerError` and the class shell with `__init__` and the hooks — *why*: every later task adds
   methods to this exact class.
3. Write the path helpers and the mapping — *why*: every Graph call in 3751+ goes through `_item_ref`, and every
   returned item goes through `_make_metadata` / `_make_entry`.
4. Write the tests.

### `packages/ai-parrot/src/parrot/interfaces/file/batch.py` (CREATE)
```python
"""Batch result models shared by the Graph managers and FileManagerToolkit (FEAT-603).

Deliberately msgraph-free: FileManagerToolkit's generic batch fallback imports this on fs/temp/s3/gcs backends.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from navigator.utils.file import FileMetadata
from pydantic import BaseModel, ConfigDict, Field

BatchState = Literal["succeeded", "failed", "skipped"]
BatchErrorCode = Literal[
    "not_found", "permission_denied", "throttled", "timeout", "auth", "conflict", "invalid_path", "io", "unknown"
]


class BatchItemResult(BaseModel):
    """Outcome of one item inside ``upload_files`` / ``download_files``.

    A batch never raises for a single item: failures are reported here. ``attempts`` counts tries including
    retries on 429/503/504; a skipped item has ``attempts=0``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    index: int
    source: str
    destination: str
    state: BatchState
    ok: bool
    metadata: Optional[FileMetadata] = None
    error: Optional[str] = None
    error_code: Optional[BatchErrorCode] = None
    status_code: Optional[int] = None
    attempts: int = Field(default=1, ge=0)


class BatchSummary(BaseModel):
    """Aggregate returned by the toolkit's batch tools (agent-facing)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")
    total: int
    succeeded: int
    failed: int
    skipped: int
    aborted: bool = False
    items: List[BatchItemResult]

    @classmethod
    def from_items(cls, items: List[BatchItemResult], *, aborted: bool = False) -> "BatchSummary":
        """Build the counters from ``items`` (used by the toolkit for native and looped batches)."""
        # FILL IN: counts by state; aborted = aborted or any(i.state == "skipped" for i in items)
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (CREATE) — part 1: header, aliases, DriveEntry, error
```python
"""FileManagerInterface over Microsoft Graph drives (SharePoint libraries and OneDrive) — FEAT-603.

Import lazily (``parrot.interfaces.file`` resolves it on first attribute access): this module imports msgraph.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from urllib.parse import quote

from navigator.utils.file import FileManagerInterface, FileMetadata
from pydantic import BaseModel, ConfigDict

from parrot.interfaces.o365 import O365Client

from .batch import BatchErrorCode, BatchItemResult, BatchState, BatchSummary

__all__ = (
    "BatchErrorCode", "BatchItemResult", "BatchState", "BatchSummary", "DriveEntry", "GraphDriveFileManager",
    "GraphFileManagerError",
)

ConflictBehavior = Literal["replace", "fail", "rename"]
LinkType = Literal["view", "edit"]
LinkScope = Literal["organization", "anonymous", "users"]
AuthMode = Literal["direct", "on_behalf_of", "delegated", "cached"]


class DriveEntry(BaseModel):
    """One child of a folder, including folders (``list_entries`` extension)."""

    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    path: str
    is_folder: bool
    size: int = 0
    modified_at: Optional[datetime] = None
    web_url: Optional[str] = None
    content_type: Optional[str] = None


class GraphFileManagerError(RuntimeError):
    """Base error for Graph file-manager failures; carries ``status_code`` when known."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (CREATE) — part 2: class shell, hooks, constructor
```python
class GraphDriveFileManager(FileManagerInterface, ABC):
    """FileManagerInterface over one Microsoft Graph drive (SharePoint library or OneDrive).

    Paths are drive-relative and prefixed with ``prefix`` exactly like S3's ``prefix + key``.
    Subclasses implement ``_build_client`` and ``_resolve_drive_id`` only.
    """

    manager_name: str = "graphfile"
    client_class: type = O365Client
    SMALL_FILE_THRESHOLD: int = 4 * 1024 * 1024
    CHUNK_SIZE: int = 10 * 1024 * 1024
    MAX_CONCURRENCY: int = 5
    MAX_RETRIES: int = 3
    COPY_TIMEOUT_S: float = 120.0
    RETRYABLE_STATUS: frozenset = frozenset({429, 503, 504})
    SERVING_MAX_BYTES: int = 64 * 1024 * 1024
    ALLOWED_ORIGINS: tuple = (
        "https://graph.microsoft.com", "https://graph.microsoft.us", "https://dod-graph.microsoft.us",
        "https://microsoftgraph.chinacloudapi.cn", "https://graph.microsoft.de",
    )
    ALLOWED_HOST_SUFFIXES: tuple = (".sharepoint.com", ".sharepoint-df.com", ".files.1drv.com")

    def __init__(
        self,
        *,
        prefix: str = "",
        credentials: Optional[Dict[str, Any]] = None,
        auth_mode: AuthMode = "direct",
        user_assertion: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        conflict_behavior: ConflictBehavior = "replace",
        link_type: LinkType = "view",
        link_scope: LinkScope = "organization",
        max_concurrency: Optional[int] = None,
        max_retries: Optional[int] = None,
        chunk_size: Optional[int] = None,
        small_file_threshold: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """Store configuration; performs no network I/O.

        Args:
            prefix: Drive-relative folder every path is resolved under ("" = drive root).
            credentials: O365 credential dict (client_id, client_secret, tenant_id, tenant, username, password ...).
            auth_mode: ``direct`` | ``on_behalf_of`` | ``delegated`` | ``cached`` (O365AuthMode strings).
            user_assertion: Incoming user token for ``on_behalf_of``.
            scopes: Graph scopes; ``None`` uses the client defaults.
            conflict_behavior: Upload conflict rule (``replace`` default, S3 parity).
            link_type: Default sharing-link type for ``get_file_url``.
            link_scope: Default sharing-link scope for ``get_file_url``.
            max_concurrency: Batch concurrency (default ``MAX_CONCURRENCY``).
            max_retries: Retry budget for 429/503/504 (default ``MAX_RETRIES``).
            chunk_size: Upload-session chunk size (default ``CHUNK_SIZE``; Graph requires multiples of 320 KiB).
            small_file_threshold: Single-PUT threshold (default ``SMALL_FILE_THRESHOLD``).
            **kwargs: Ignored extra keys (factory/toolkit pass-through), logged at DEBUG.
        """
        self.logger = logging.getLogger(__name__)
        # FILL IN: normalise and store every argument on self (prefix rule in Implementation Notes; credentials copied,
        #          with "assertion" added when user_assertion is given); defaults from the class constants;
        #          initialise self._client = None, self._drive_id = None, self._owns_client = False,
        #          self._adopted = None; log unknown kwargs at DEBUG — bounded by spec §3 M1 skeleton

    @abstractmethod
    def _build_client(self) -> O365Client:
        """Return the (not yet authenticated) O365Client subclass for this drive kind."""

    @abstractmethod
    async def _resolve_drive_id(self) -> str:
        """Resolve and return the Graph drive id (the base caches it in ``self._drive_id``)."""

    @property
    def client(self) -> O365Client:
        """Authenticated client; raises GraphFileManagerError if neither ``connect()`` nor ``adopt_client()`` ran."""
        # FILL IN

    @property
    def drive_id(self) -> str:
        """Resolved drive id; raises GraphFileManagerError before resolution."""
        # FILL IN
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (CREATE) — part 3: path model and mapping (inside the class)
```python
    def _prefixed(self, key: str) -> str:
        """Return ``prefix + key`` (S3 parity); ``..`` segments raise ValueError."""
        # FILL IN: rule in Implementation Notes

    def _unprefixed(self, key: str) -> str:
        """Strip ``prefix`` from a drive-relative path when present."""
        # FILL IN

    def _item_ref(self, full_path: str) -> str:
        """``"root"`` for the drive root, else ``"root:/<per-segment quoted path>:"``."""
        segments = [s for s in (full_path or "").strip("/").split("/") if s]
        if not segments:
            return "root"
        return "root:/" + "/".join(quote(seg, safe="") for seg in segments) + ":"

    def _item_path(self, item: Any) -> Optional[str]:
        """Drive-relative path of ``item`` from ``parent_reference.path``; None when Graph omitted it."""
        # FILL IN: rule in Implementation Notes

    def _make_metadata(self, item: Any, *, full_path: Optional[str] = None) -> FileMetadata:
        """Map a DriveItem to FileMetadata (path unprefixed; folders get size 0 and content_type None)."""
        # FILL IN: path = self._unprefixed(full_path or self._item_path(item) or item.name);
        #          size = 0 if item.folder else (item.size or 0); content_type = item.file.mime_type when item.file;
        #          modified_at = item.last_modified_date_time; url = item.web_url

    def _make_entry(self, item: Any, *, full_path: Optional[str] = None) -> DriveEntry:
        """Map a DriveItem to DriveEntry (folders included)."""
        # FILL IN: same path rule; is_folder = item.folder is not None
```
**Why this shape**: models and constants are copied verbatim from spec §2/§3 because six other tasks bind to the names.
`ALLOWED_ORIGINS` equals `DEFAULT_GRAPH_ORIGINS` in `parrot_tools/o365/delta.py:65-71` — copied, not imported, since
core must not depend on the tools distribution. `_item_ref` is written out because its exact quoting is asserted by the
spec's test table.

### `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` (CREATE)
```python
"""FEAT-603 — GraphDriveFileManager unit tests (TASK-3749 creates; TASK-3750..3754 append)."""
import datetime as dt
from types import SimpleNamespace

import pytest

from parrot.interfaces.file.graph import (
    BatchItemResult, BatchSummary, DriveEntry, GraphDriveFileManager, GraphFileManagerError,
)
from ._graph_fakes import FakeDriveItem, make_probe


def test_prefix_is_normalised():
    assert make_probe(GraphDriveFileManager, prefix="/reports/2026/").prefix == "reports/2026/"
    assert make_probe(GraphDriveFileManager).prefix == ""


def test_prefixed_unprefixed_roundtrip():
    # FILL IN: prefix "reports/"; _prefixed("q3.xlsx") == "reports/q3.xlsx"; _unprefixed of that == "q3.xlsx";
    #          backslashes normalised; _prefixed("") == "reports"


def test_rejects_parent_segments():
    with pytest.raises(ValueError):
        make_probe(GraphDriveFileManager)._prefixed("a/../b")


def test_item_ref_root_and_quoted_segments():
    m = make_probe(GraphDriveFileManager)
    assert m._item_ref("") == "root"
    assert m._item_ref("a b/c#d.txt") == "root:/a%20b/c%23d.txt:"


def test_make_metadata_maps_driveitem():
    # FILL IN: file item with parent_reference.path="/drives/d/root:/reports" -> path "reports/q3.xlsx", size, mime,
    #          modified_at, url; folder item -> size 0, content_type None; item without parent path + full_path kwarg


def test_make_entry_includes_folders():
    # FILL IN: folder -> is_folder True, file -> False; id/name/web_url copied


def test_models_validate():
    # FILL IN: BatchItemResult rejects attempts=-1 and extra fields; BatchSummary round-trips; DriveEntry defaults


def test_batch_module_is_msgraph_free():
    # FILL IN: subprocess `python -c "import parrot.interfaces.file.batch, sys; assert 'msgraph' not in sys.modules"`


def test_batch_summary_from_items():
    # FILL IN: counters and aborted flag


def test_client_before_connect_raises():
    with pytest.raises(GraphFileManagerError):
        _ = make_probe(GraphDriveFileManager).client
```

### FILL IN checklist
- [ ] `BatchSummary.from_items`
- [ ] `__init__` storage + prefix normalisation + `assertion` in credentials
- [ ] `client` / `drive_id` properties
- [ ] `_prefixed`, `_unprefixed`, `_item_path`, `_make_metadata`, `_make_entry`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] `from parrot.interfaces.file.graph import GraphDriveFileManager, BatchItemResult, BatchSummary, DriveEntry,
      GraphFileManagerError` works; the models have exactly the spec §2 fields.
- [ ] `parrot/interfaces/file/batch.py` imports nothing from msgraph / `parrot.interfaces.o365` (a test asserts that
      importing it leaves `msgraph` out of `sys.modules` when it was not loaded before).
- [ ] `_item_ref("a b/c#d.txt") == "root:/a%20b/c%23d.txt:"`; `..` raises `ValueError` (spec AC-path tests).
- [ ] Folders map to `size=0`, `content_type=None` (spec §7 gotcha).
- [ ] No network I/O in `__init__`; no `httpx` import; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_graph_filemanager.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_prefix_is_normalised` | S3-style prefix |
| `test_prefixed_unprefixed_roundtrip` / `test_rejects_parent_segments` | path model |
| `test_item_ref_root_and_quoted_segments` | colon refs, per-segment quoting |
| `test_make_metadata_maps_driveitem` / `test_make_entry_includes_folders` | mapping |
| `test_models_validate` / `test_batch_summary_from_items` | Pydantic contracts |
| `test_batch_module_is_msgraph_free` | optional-dependency layering |
| `test_client_before_connect_raises` | lifecycle guard |

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
