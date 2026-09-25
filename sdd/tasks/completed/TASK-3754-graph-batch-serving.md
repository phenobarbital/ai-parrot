# TASK-3754: GraphDriveFileManager — batch upload/download engine and size-guarded HTTP serving

**Feature**: FEAT-603 — SharePoint & OneDrive FileManager
**Spec**: `sdd/specs/sharepoint-filemanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3753
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 1** (last of six `graph.py` tasks), AC8 (batch semantics), AC9 (`setup` mounts
`FileServingExtension`), AC22 (serving size guard) and design research **S7** (the extension buffers whole objects) and
**S10** (explicit batch states, identity, cancellation, shared-stream rejection). The toolkit's native batch path
(TASK-3759) calls `upload_files` / `download_files` directly and wraps the result in `BatchSummary`.

**Attempt counting.** `BatchItemResult.attempts` must report real tries including retries, but the public single-item
methods do not return an attempt count. This task adds a module-level `ContextVar` that `_retrying` (TASK-3750)
increments on every retry; each batch worker runs in its own `asyncio` task (which copies the context), sets a fresh
counter, and reads it after the item finishes. No public signature changes.

---

## Scope

- Add the `_RETRY_COUNTER` context variable and a two-line hook in `_retrying` that increments it on each retry.
- Append to `GraphDriveFileManager`: `upload_files`, `download_files`, `_run_batch`, `_classify`, `setup`, `handle_file`.
- Add the module-level `_GuardedFileServingExtension(FileServingExtension)`.
- Append tests to `test_graph_filemanager.py`.

**NOT in scope**: toolkit batch tools (TASK-3759); a streaming serving path (spec §8 Q4, open).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/graph.py` | MODIFY | batch engine, retry counter hook, serving guard |
| `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` | MODIFY | append batch/serving tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified 2026-09-25 against `dev` at `8da1f45c3`.

### Verified Imports
```python
import contextvars                                                  # stdlib
from typing import Sequence                                         # stdlib
from aiohttp import web                                             # aiohttp 3.14.3
from navigator.utils.file.web import FileServingExtension           # verified: .venv/lib/python3.12/site-packages/navigator/utils/file/web.py:28
```

### Existing Signatures to Use
```python
# navigator/utils/file/web.py
class FileServingExtension(BaseExtension):                                         # :28
    def __init__(self, manager: FileManagerInterface, route: str = "/data", manager_name: Optional[str] = None, **kwargs)   # :48
    def setup(self, app: WebApp) -> WebApp                                         # :78 — registers GET route + "/{filepath:.*}" -> self.handle_file (:106-107); returns the raw app
    async def handle_file(self, request: web.Request) -> web.StreamResponse        # :150 — reads request.match_info["filepath"],
        # sanitises it, manager.exists / get_file_metadata, then download_file(safe_path, io.BytesIO()) for BOTH the Range
        # branch (:229-232) and the full branch (:257-259)  <- whole object buffered in memory (S7)
# S3 parity: navigator/utils/file/s3.py:613 setup(app, route="/data", base_url=None) -> ext.setup(app); :635 handle_file(request)

# From TASK-3749..3753 (same file): BatchItemResult, BatchErrorCode, _retrying, _status_code_of, _prefixed,
#   upload_file, download_file, get_file_metadata, max_concurrency, SERVING_MAX_BYTES, manager_name
```

### Does NOT Exist
- ~~a streaming/seekable download interface on `FileServingExtension`~~ — it always buffers; do not describe `setup()`
  as streaming (spec §6 Does NOT Exist).
- ~~`S3FileManager.upload_files` / `.download_files`~~ — no upstream batch API; these are Graph-manager extensions.

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

- **Batch engine `_run_batch(items, run_one)`**: `run_one(index, source, destination)` is an async callable performing
  one transfer and returning `FileMetadata`. For each item start a task that: waits on
  `asyncio.Semaphore(max_concurrency)`; if the shared `abort` event is set, returns a `skipped` result
  (`attempts=0`, `error="aborted after authentication failure"`, `error_code="auth"`); otherwise sets
  `_RETRY_COUNTER` to `[0]`, runs `run_one`, and builds a `succeeded` or `failed` result with
  `attempts = 1 + counter[0]`. `asyncio.CancelledError` is NEVER caught (it propagates — S10). `await asyncio.gather(*tasks)`
  (no `return_exceptions`) and return the results sorted by `index` (input order).
- **`_classify(exc)`** → `(error_code, status_code)`: `PermissionError` → `"auth"` (and sets `abort`);
  `FileNotFoundError` → `"not_found"`; `FileExistsError` → `"conflict"`; `TimeoutError` → `"timeout"`; `ValueError` →
  `"invalid_path"`; `GraphFileManagerError` with status 429/503/504 → `"throttled"`; other `OSError` → `"io"`; anything
  else → `"unknown"`. `status_code` from `getattr(exc, "status_code", None)` or `_status_code_of(exc)`.
- **Shared streams (S10)**: before starting, if the same stream object (`id()` of a non-`Path`/`str`/`bytes` source or
  destination) appears twice → `ValueError("the same stream object appears more than once in the batch")`. Duplicate
  *destinations* are allowed and processed in order (last write wins under `replace`).
- **Labels in results**: `source`/`destination` are the path strings; `bytes` sources show `"<bytes>"`, stream
  sources/destinations show `"<stream>"`. `bytes` sources are wrapped in `io.BytesIO` before `upload_file`.
- **Serving guard (S7, AC22)**: `_GuardedFileServingExtension.handle_file(request)`: read `request.match_info
  .get("filepath", "")`; try `meta = await self.manager.get_file_metadata(path)`; if `meta.size > self.max_bytes` return
  `web.Response(status=413, text=f"File exceeds the serving limit of {self.max_bytes} bytes")`; on any exception or
  otherwise delegate to `super().handle_file(request)` (which does its own sanitising / 403 / 404). `setup()` builds one,
  calls `ext.setup(app)`, stores it on `self._serving_ext` and RETURNS THE EXTENSION (spec §3 M1 signature).

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
1. Add imports and `_RETRY_COUNTER` — *why*: engine + counter hook.
2. Hook `_retrying` — *why*: the only way per-item attempt counts can be measured without changing public signatures.
3. Add `_GuardedFileServingExtension` at module level (after the class) and append the batch/serving methods.
4. Append the tests.

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — imports + context var
```python
# occurrences: 1 (expected after TASK-3753; verify: grep -c '^from msgraph.generated.models.item_reference import ItemReference$' graph.py)
# AFTER — insert below `from msgraph.generated.models.item_reference import ItemReference`
import contextvars
from typing import Sequence

from aiohttp import web
from navigator.utils.file.web import FileServingExtension

# Incremented by GraphDriveFileManager._retrying on every retry; set per batch item (TASK-3754).
_RETRY_COUNTER: contextvars.ContextVar[Optional[List[int]]] = contextvars.ContextVar("_graph_retry_counter", default=None)
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — `_retrying` hook
```python
# occurrences: 1 (expected after TASK-3750; verify: grep -c 'async def _retrying(' graph.py)
# FILL IN: disambiguate — inside `_retrying`, at the point where a retry is decided (immediately BEFORE
#          `await self._sleep(delay)`), insert:
                counter = _RETRY_COUNTER.get()
                if counter is not None:
                    counter[0] += 1
```
**Why**: the counter is `None` outside a batch, so single-item calls are unaffected.

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — batch + serving methods (append to class)
```python
# occurrences: 1 (expected after TASK-3753; verify: grep -c '    async def _move_or_rename(self, old: str, new: str) -> None:' graph.py)
# AFTER — append at the end of the class body (after `_move_or_rename`)
    async def upload_files(
        self, items: Sequence[Tuple[Union[Path, BinaryIO, bytes], str]]
    ) -> List[BatchItemResult]:
        """Batch upload (AC8): bounded concurrency, per-item results in input order, never raises for an item."""
        self._reject_shared_streams([src for src, _ in items])

        async def run_one(index: int, src: Any, dst: str) -> FileMetadata:
            source = io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src
            return await self.upload_file(source, dst)

        return await self._run_batch(list(items), run_one)

    async def download_files(self, items: Sequence[Tuple[str, Union[Path, BinaryIO]]]) -> List[BatchItemResult]:
        """Batch download with the same semantics as ``upload_files``."""
        self._reject_shared_streams([dst for _, dst in items])

        async def run_one(index: int, src: str, dst: Any) -> FileMetadata:
            await self.download_file(src, dst)
            return await self.get_file_metadata(src)

        return await self._run_batch(list(items), run_one)

    def _reject_shared_streams(self, objs: List[Any]) -> None:
        # FILL IN: rule in Implementation Notes (Path / str / bytes are never "shared streams")

    async def _run_batch(
        self, items: List[Tuple[Any, Any]], run_one: Callable[[int, Any, Any], Awaitable[FileMetadata]]
    ) -> List[BatchItemResult]:
        # FILL IN: engine in Implementation Notes

    def _classify(self, exc: BaseException) -> Tuple[str, Optional[int]]:
        # FILL IN: mapping in Implementation Notes

    def setup(
        self, app: Any, route: str = "/data", base_url: Optional[str] = None, *, serving_max_bytes: Optional[int] = None
    ) -> FileServingExtension:
        """Mount a size-guarded FileServingExtension (buffers whole objects — S7; guard AC22). Returns the extension."""
        ext = _GuardedFileServingExtension(
            manager=self, route=route, manager_name=self.manager_name,
            max_bytes=serving_max_bytes or self.SERVING_MAX_BYTES,
        )
        ext.setup(app)
        self._serving_ext = ext
        return ext

    async def handle_file(self, request: Any) -> Any:
        """Size guard then the extension's buffered handler (S3 parity with s3.py:635)."""
        ext = getattr(self, "_serving_ext", None) or _GuardedFileServingExtension(
            manager=self, manager_name=self.manager_name, max_bytes=self.SERVING_MAX_BYTES
        )
        return await ext.handle_file(request)
```

### `packages/ai-parrot/src/parrot/interfaces/file/graph.py` (MODIFY) — guarded extension (end of module)
```python
# AFTER — append at the very end of the module (after the GraphDriveFileManager class)
class _GuardedFileServingExtension(FileServingExtension):
    """FileServingExtension that refuses (413) files larger than ``max_bytes`` before buffering them (S7, AC22)."""

    def __init__(self, *args: Any, max_bytes: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_bytes = max_bytes

    async def handle_file(self, request: web.Request) -> web.StreamResponse:
        # FILL IN: rule in Implementation Notes
        return await super().handle_file(request)
```
**Why this shape**: `upload_files` / `download_files` / `setup` are written out so the public surface cannot drift from
spec §3; the engine and classifier are FILL IN because their branches are fully specified above and asserted by tests.

### `packages/ai-parrot/tests/interfaces/test_graph_filemanager.py` (MODIFY)
```python
# AFTER — append at end of file
import asyncio
import io


async def test_upload_files_per_item_results_order_and_no_raise(xfer_manager):
    # FILL IN: 3 items, the second fails (fail_next 500 on its content put) -> states succeeded/failed/succeeded, index 0..2


async def test_batch_retries_429_with_retry_after_then_succeeds(xfer_manager):
    # FILL IN: fail_next(429, retry_after=1, op="content_put") -> attempts == 2, slept 1


async def test_batch_auth_failure_skips_remaining(xfer_manager):
    # FILL IN: max_concurrency=1, first item 401 -> failed/"auth", rest skipped with attempts == 0; no exception


async def test_batch_concurrency_bounded(xfer_manager, monkeypatch):
    # FILL IN: instrument upload_file with an in-flight counter; never exceeds max_concurrency


async def test_batch_rejects_shared_binaryio(xfer_manager):
    # FILL IN: same BytesIO twice -> ValueError before any call


async def test_batch_duplicate_destinations_last_write_wins(xfer_manager):
    # FILL IN


async def test_batch_cancellation_propagates(xfer_manager):
    # FILL IN: cancel the outer task while an item is in flight -> asyncio.CancelledError raised


async def test_setup_mounts_guarded_extension(xfer_manager):
    # FILL IN: aiohttp web.Application(); ext = m.setup(app, route="/sp"); isinstance FileServingExtension;
    #          ext.manager is m; manager_name == m.manager_name; a GET route "/sp/{filepath:.*}" exists


async def test_handle_file_413_over_serving_max_bytes(xfer_manager, aiohttp_client=None):
    # FILL IN: file larger than serving_max_bytes -> 413 before any download request (session.requests empty)
```

### FILL IN checklist
- [ ] `_retrying` hook placement
- [ ] `_reject_shared_streams`, `_run_batch`, `_classify`
- [ ] `_GuardedFileServingExtension.handle_file`
- [ ] test bodies (use `aiohttp.test_utils` `make_mocked_request` for the 413 test — no server needed)

---

## Acceptance Criteria

- [ ] `upload_files` / `download_files` return `List[BatchItemResult]` in input order with `index`, `state`,
      `error_code`, real `attempts`; never raise for an item; bounded by `max_concurrency`; 401/403 marks the rest
      `skipped`; a reused stream → `ValueError`; outer cancellation propagates (spec AC8, S10).
- [ ] `setup(app, route, base_url, *, serving_max_bytes)` mounts the guarded `FileServingExtension` with
      `manager=self`, `manager_name=self.manager_name` and returns it (spec AC9).
- [ ] Files above `serving_max_bytes` (default 64 MiB) get HTTP 413 before any download (spec AC22).
- [ ] Single-item calls are unaffected by the counter hook (existing tests still pass); `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/interfaces/test_graph_filemanager.py -q`

---

## Test Specification

| Test | Asserts |
|---|---|
| `test_upload_files_per_item_results_order_and_no_raise` | AC8 |
| `test_batch_retries_429_with_retry_after_then_succeeds` | attempts counting |
| `test_batch_auth_failure_skips_remaining` | S10 skipped state |
| `test_batch_concurrency_bounded` | semaphore |
| `test_batch_rejects_shared_binaryio` / `test_batch_duplicate_destinations_last_write_wins` | S10 |
| `test_batch_cancellation_propagates` | S10 |
| `test_setup_mounts_guarded_extension` / `test_handle_file_413_over_serving_max_bytes` | AC9, AC22 |

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


- Task: TASK-3754
- Feature: sharepoint-filemanager
- Implementation SHA: 875aecb041f6015a6f2c5ab57c1f43eebfdec707
- Closed at (UTC): 2026-09-25T20:53:15+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: mistral · Backend: nova · Model: mistral.devstral-2-123b · Attempts: 1 · Duration: 526.4s · Tokens: 2734830/8228 |
| validation_note | Delivered semaphore was constructed but never acquired (unbounded concurrency) plus 4 test bugs; fixed and squashed into this commit (coder-feedback:2e518baf394b3f77c1608475). Own test file: pytest test_graph_filemanager.py -q -> 57 passed. The merge-tier validation's packages/ai-parrot/tests segment is entirely blocked at collection time (18 pre-existing errors, 0 tests run) by the same test_file_shim.py bug already ledger'd (issue:71cbc792726c) plus 17 other unrelated pre-existing import/version-drift errors; none attributable to this diff. |
