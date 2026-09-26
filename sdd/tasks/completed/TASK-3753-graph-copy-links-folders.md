# TASK-3753: GraphDriveFileManager — async copy + monitor, sharing links, get_file_url, folders, rename/move

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3752
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1** (fifth of six `graph.py` tasks), AC6 (copy polling + timeout), AC7 (sharing links; exact
`get_file_url` signature), AC21 (copy POST never retried; monitor URL validated) and design research **S3** / **S5** /
**S6**. After this task every abstract method of `FileManagerInterface` is implemented (AC1).

**Copy needs the raw response.** Graph answers `POST …/copy` with `202 Accepted` and a `Location` monitor header and no
body; `CopyRequestBuilder.post` would return `None` and lose the header. The call therefore passes
`RequestConfiguration(options=[ResponseHandlerOption(NativeResponseHandler())])`, which makes kiota return the native
HTTP response (verified below) so the manager can read `.status_code` and `.headers["Location"]`.

**Task-time decision (deviation from the spec §3 M1 docstring of `rename_folder`)**: a rename that also changes the
parent is done with ONE `PATCH` carrying `name` and `parentReference` — Graph's documented in-drive move — instead of
copy + delete. Reason: PATCH is atomic and transfers no bytes; copy + delete is neither. Same-parent renames PATCH `name`
only. Record this under "Deviations from spec" in the Completion Note.

---

## Scope

- Append to `GraphDriveFileManager`: `copy_file`, `_poll_copy_monitor`, `create_sharing_link`, `get_file_url`,
  `create_folder`, `remove_folder`, `rename_file`, `rename_folder`, `_move_or_rename`.
- Append tests to `test_graph_filemanager.py`, including the AC1 signature-parity test.

**NOT in scope**: batch engine and serving (3754).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/graph.py` | MODIFY | copy, links, folders, rename |
| `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` | MODIFY | append tests + AC1 parity test |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`, msgraph-sdk 1.63.0, kiota (abstractions/http) in the venv.

### Verified Imports
```python
from datetime import timedelta                                          # stdlib (timezone already imported by TASK-3750)
from kiota_abstractions.base_request_configuration import RequestConfiguration   # verified: base_request_configuration.py:17 (fields headers/options/query_parameters :22-26)
from kiota_abstractions.native_response_handler import NativeResponseHandler      # verified: native_response_handler.py:10
from kiota_http.middleware.options.response_handler_option import ResponseHandlerOption   # verified: response_handler_option.py:7 (__init__(response_handler))
from msgraph.generated.drives.item.items.item.copy.copy_post_request_body import CopyPostRequestBody   # verified: copy_post_request_body.py:12 (name :23, parent_reference :25)
from msgraph.generated.drives.item.items.item.create_link.create_link_post_request_body import CreateLinkPostRequestBody   # verified: create_link_post_request_body.py:13 (expiration_date_time :24, scope :32, type :34)
from msgraph.generated.models.item_reference import ItemReference      # verified: msgraph/generated/models/item_reference.py
```

### Existing Signatures to Use
```python
# …/msgraph/generated/drives/item/items/item/
copy/copy_request_builder.py:               async def post(self, body: CopyPostRequestBody, request_configuration=None) -> Optional[DriveItem]   # :34
create_link/create_link_request_builder.py: async def post(self, body: CreateLinkPostRequestBody, request_configuration=None) -> Optional[Permission]   # :34
drive_item_item_request_builder.py:         async def patch(self, body: DriveItem, request_configuration=None) -> Optional[DriveItem]   # :133
                                            async def delete(self, request_configuration=None) -> None                                 # :65
# Permission.link.web_url -> the sharing URL
# Copy monitor (GET, pre-authenticated): JSON {"status": "notStarted"|"inProgress"|"completed"|"failed", "resourceId": "<new item id>"}

# FileManagerInterface (abstract.py) — exact signatures:
async def get_file_url(self, path: str, expiry: int = 3600) -> str                        # :67
async def copy_file(self, source: str, destination: str) -> FileMetadata                  # :107
async def create_folder(self, folder_name: str) -> None                                   # :170
async def remove_folder(self, folder_name: str) -> None                                   # :183
async def rename_folder(self, old_folder_name: str, new_folder_name: str) -> None         # :196
async def rename_file(self, old_file_name: str, new_file_name: str) -> None               # :212
# From TASK-3750..3752: _ready, _prefixed, _drive, _get_item, _get_item_by_id, _ensure_parent, _retrying, _map_error,
#   _status_code_of, _validate_graph_url, _http_session, _sleep, _RawHTTPError, _make_metadata, link_type, link_scope
```

### Does NOT Exist
- ~~a Location header on `CopyRequestBuilder.post`'s return value~~ — only via the native response handler (Context).
- ~~`GraphDriveFileManager.get_file_url(path, expiry, scope=..., link_type=...)`~~ — options live ONLY on
  `create_sharing_link`; `get_file_url` keeps the exact interface signature (S3, AC7).
- ~~a Graph "rename" endpoint~~ — rename/move is `PATCH` on the item.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/graph.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_graph_filemanager.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- **`copy_file(source, destination)`**: source item via `_get_item`; destination parent via `_ensure_parent`;
  `CopyPostRequestBody(name=<dest name>, parent_reference=ItemReference(drive_id=self.drive_id, id=parent.id))`;
  POST through `_retrying(..., label="copy", idempotent=False)` with the native-handler configuration; a status other than
  202 or a missing `Location` → `GraphFileManagerError`. Then `_poll_copy_monitor(location)` → new item id →
  `_get_item_by_id` → `_make_metadata(item, full_path=dest_full)`.
- **`_poll_copy_monitor(url)`**: validate with `purpose="copy monitor"`; loop GET (no auth header,
  `allow_redirects=False`, each GET inside `_retrying(label="copy-monitor")`) until `status == "completed"` (return
  `resourceId`), `status == "failed"` (`GraphFileManagerError`) or elapsed ≥ `COPY_TIMEOUT_S` (`TimeoutError` — message
  names the source path, not the URL). Sleep `min(1.0 * 2 ** n, 5.0)` between polls via `self._sleep`; measure time with
  `asyncio.get_running_loop().time()`.
- **`create_sharing_link(path, *, link_type, scope, expiry)`**: body `CreateLinkPostRequestBody(type=link_type,
  scope=scope, expiration_date_time=now_utc + timedelta(seconds=expiry) if expiry > 0 else None)`; not retried on 4xx.
  On status 400 **with** an expiration set: log a WARNING ("tenant rejected link expiration; creating a non-expiring
  link") and retry once without it. On 403, or a 400 whose message mentions the scope, → `PermissionError`. Return
  `permission.link.web_url`. Side effect documented: it creates a sharing permission on the item.
- **`get_file_url(path, expiry=3600)`** → `await self.create_sharing_link(path, link_type=self.link_type,
  scope=self.link_scope, expiry=expiry)`.
- **Folders**: `create_folder(name)` creates the full chain (reuse `_ensure_parent(f"{full}/.")`-style logic or a
  dedicated walk — FILL IN, bounded by "idempotent: an existing folder is not an error"); `remove_folder(name)` deletes
  the folder item (recycle bin); missing → `FileNotFoundError`.
- **`_move_or_rename(old_full, new_full)`**: same parent → `PATCH DriveItem(name=new_name)`; different parent →
  `_ensure_parent(new_full)` then `PATCH DriveItem(name=new_name, parent_reference=ItemReference(id=new_parent.id))`.
  `rename_file` / `rename_folder` both call it (retried: PATCH to a fixed target is idempotent).

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
1. Add the imports — *why*: copy/link bodies, `ItemReference`, native handler.
2. Append the copy methods, then links, then folders/rename — *why*: TASK-3754 appends after them.
3. Append the tests, including the AC1 parity test (all interface methods exist now).

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — imports
```python
# occurrences: 1 (expected after TASK-3752; verify: grep -c '^from msgraph.generated.models.folder import Folder$' graph.py)
# AFTER — insert below `from msgraph.generated.models.folder import Folder`
from datetime import timedelta

from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.native_response_handler import NativeResponseHandler
from kiota_http.middleware.options.response_handler_option import ResponseHandlerOption
from msgraph.generated.drives.item.items.item.copy.copy_post_request_body import CopyPostRequestBody
from msgraph.generated.drives.item.items.item.create_link.create_link_post_request_body import CreateLinkPostRequestBody
from msgraph.generated.models.item_reference import ItemReference
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — copy (append)
```python
# occurrences: 1 (expected after TASK-3752; verify: grep -c '    async def download_file(self, source: str, destination' graph.py)
# AFTER — append at the end of the class body (after `download_file`)
    async def copy_file(self, source: str, destination: str) -> FileMetadata:
        """POST copy (202 + Location; never retried), then poll the validated monitor (AC6, AC21)."""
        await self._ready()
        src_full, dest_full = self._prefixed(source), self._prefixed(destination)
        try:
            src = await self._get_item(src_full)
            parent = await self._ensure_parent(dest_full)
            body = CopyPostRequestBody(
                name=dest_full.rsplit("/", 1)[-1],
                parent_reference=ItemReference(drive_id=self.drive_id, id=parent.id),
            )
            config = RequestConfiguration(options=[ResponseHandlerOption(NativeResponseHandler())])
            resp, _ = await self._retrying(
                lambda: self._drive().items.by_drive_item_id(src.id).copy.post(body, request_configuration=config),
                label="copy",
                idempotent=False,
            )
            # FILL IN: status 202 + Location check; new_id = await self._poll_copy_monitor(location, source=source);
            #          return self._make_metadata(await self._get_item_by_id(new_id), full_path=dest_full)
        except Exception as exc:
            raise self._map_error(exc, path=source) from exc

    async def _poll_copy_monitor(self, url: str, *, source: str) -> str:
        """Poll the copy monitor until completed; return the new item id (TimeoutError after COPY_TIMEOUT_S)."""
        # FILL IN: rule in Implementation Notes
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — links, folders, rename (append)
```python
# AFTER — append below `_poll_copy_monitor` (added by the previous block of this task)
    async def create_sharing_link(
        self, path: str, *, link_type: LinkType = "view", scope: LinkScope = "organization", expiry: int = 3600
    ) -> str:
        """POST createLink; creates a sharing permission (S3). See Implementation Notes for policy fallbacks."""
        # FILL IN: rule in Implementation Notes (AC7)

    async def get_file_url(self, path: str, expiry: int = 3600) -> str:
        """Exact FileManagerInterface signature (abstract.py:67); wraps create_sharing_link with the defaults."""
        return await self.create_sharing_link(path, link_type=self.link_type, scope=self.link_scope, expiry=expiry)

    async def create_folder(self, folder_name: str) -> None:
        """Create ``folder_name`` (and missing parents); an existing folder is not an error."""
        # FILL IN

    async def remove_folder(self, folder_name: str) -> None:
        """Delete a folder and its contents (recycle bin); FileNotFoundError when missing."""
        # FILL IN

    async def rename_file(self, old_file_name: str, new_file_name: str) -> None:
        """Rename and/or move a file within the drive (single PATCH)."""
        await self._move_or_rename(old_file_name, new_file_name)

    async def rename_folder(self, old_folder_name: str, new_folder_name: str) -> None:
        """Rename and/or move a folder within the drive (single PATCH; task-time deviation, see Context)."""
        await self._move_or_rename(old_folder_name, new_folder_name)

    async def _move_or_rename(self, old: str, new: str) -> None:
        # FILL IN: rule in Implementation Notes; public-boundary try/map
```
**Why this shape**: `copy_file` is written out because the native-handler configuration and `idempotent=False` are the
two easy-to-get-wrong parts; `get_file_url` is one line on purpose — it must keep the interface signature (S3).

### `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` (MODIFY)
```python
# AFTER — append at end of file
import inspect

from navigator.utils.file import FileManagerInterface


def _shape(fn):
    # Names, kinds and defaults only: graph.py uses `from __future__ import annotations`, so annotation objects
    # would compare as strings vs typing objects and fail spuriously.
    return [(p.name, p.kind, p.default) for p in inspect.signature(fn).parameters.values()]


def test_all_interface_methods_implemented_with_exact_signatures():
    """AC1: no abstract interface method left; parameter shapes equal navigator's."""
    names = {n for n in FileManagerInterface.__abstractmethods__}
    assert not (names & GraphDriveFileManager.__abstractmethods__)
    for name in names | {"create_folder", "remove_folder", "rename_folder", "rename_file", "find_files"}:
        assert _shape(getattr(GraphDriveFileManager, name)) == _shape(getattr(FileManagerInterface, name)), name


async def test_copy_polls_monitor_until_completed(xfer_manager):
    # FILL IN: copy_polls_before_done=2 -> two inProgress polls then completed; returned metadata path == destination


async def test_copy_post_never_retried(xfer_manager):
    # FILL IN: fail_next(503, op="copy") -> GraphFileManagerError after exactly one "copy" call


async def test_copy_timeout(xfer_manager, monkeypatch):
    # FILL IN: COPY_TIMEOUT_S tiny + monitor never completes -> TimeoutError (message has no URL)


async def test_get_file_url_createlink_defaults_and_expiry(xfer_manager):
    # FILL IN: type=view, scope=organization, expiration set for expiry>0, None for expiry=0 (fake.link_bodies)


async def test_create_sharing_link_expiry_rejected_falls_back_and_anonymous_forbidden(xfer_manager, caplog):
    # FILL IN: fail_next(400, op="create_link") with expiry -> warning + second call without expiry;
    #          fail_next(403, op="create_link") with scope="anonymous" -> PermissionError


async def test_folders_create_remove(xfer_manager):
    # FILL IN


async def test_rename_same_parent_and_move(xfer_manager):
    # FILL IN: one "patch" call each; moved item under the new parent
```

### FILL IN checklist
- [ ] `copy_file` status/Location handling; `_poll_copy_monitor`
- [ ] `create_sharing_link` incl. both policy fallbacks
- [ ] `create_folder`, `remove_folder`, `_move_or_rename`
- [ ] test bodies

---

## Acceptance Criteria

- [ ] Every abstract method of `FileManagerInterface` is implemented with the exact upstream signature (spec AC1).
- [ ] Copy: one non-retried POST, validated monitor URL polled without auth/redirects, `TimeoutError` after
      `COPY_TIMEOUT_S` (spec AC6, AC21).
- [ ] `get_file_url(path, expiry=3600)` wraps `create_sharing_link`; defaults view/organization; expiry rules and both
      policy fallbacks behave as specified (spec AC7).
- [ ] Rename/move is a single PATCH; the deviation is recorded in the Completion Note.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_graph_filemanager.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_all_interface_methods_implemented_with_exact_signatures` | AC1 |
| `test_copy_polls_monitor_until_completed` / `test_copy_post_never_retried` / `test_copy_timeout` | AC6, AC21 |
| `test_get_file_url_createlink_defaults_and_expiry` / `test_create_sharing_link_expiry_rejected_...` | AC7 |
| `test_folders_create_remove` / `test_rename_same_parent_and_move` | optional hooks |

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


- Task: TASK-3753
- Feature: sharepoint-filemanager
- Implementation SHA: b534138ff23651b9baaf1d793cf6448bbdfd8048
- Closed at (UTC): 2026-09-25T20:08:07+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 326.5s · Tokens: n/a |
| validation_note | Directory-wide merge-tier run (packages/ai-parrot/tests/interfaces) reported outcome=failed, but the collection error is in tests/interfaces/test_file_shim.py (pre-existing ImportError on 'FileManagerTool', unrelated to this task's files) and is reproducible identically at the pre-TASK-3753 commit (f7fbb4ec5) in an isolated worktree, before this task's changes existed. TASK-3753's own declared test file was run in isolation as manual verification: `pytest packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` -> 48 passed, 8 warnings. Filed as a ledger issue for separate remediation; not attributable to this task's diff. |
