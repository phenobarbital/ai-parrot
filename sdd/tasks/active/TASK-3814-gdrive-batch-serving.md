# TASK-3814: `gdrive.py` batch engine + HTTP serving

**Feature**: FEAT-608 — Google Drive FileManager
**Spec**: `sdd/specs/google-drive-interface.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3813
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (batch + serving half; AC8, AC22). Re-implements the FEAT-603 AC8 batch
contract (`graph.py:1014-1111`) in `gdrive.py` — no shared engine (spec Non-Goals, §8 Q3) —
and mounts the relocated `GuardedFileServingExtension`. After this task every abstract
method is implemented, so the `_concrete` autouse fixture in the test module is removed.

---

## Scope

Add `upload_files`, `download_files`, `_reject_shared_streams`, `_run_batch`, `_classify`,
`setup`, `handle_file`. Remove the `_concrete` `__abstractmethods__` fixture from
`test_gdrive_filemanager.py` and add `test_class_is_concrete`. Append batch/serving tests.

**NOT in scope**: extracting a `BatchRunnerMixin`; changing `batch.py` or `graph.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/file/gdrive.py` | MODIFY | Batch + serving |
| `packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py` | MODIFY | Tests; drop `_concrete` fixture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .batch import BatchErrorCode, BatchItemResult, BatchState, BatchSummary    # verified: batch.py:14-71 (already imported by TASK-3810)
from .entries import GuardedFileServingExtension                                # TASK-3808 (already imported)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/file/batch.py
BatchErrorCode = Literal["not_found", "throttled", "timeout", "auth", "conflict", "invalid_path", "io", "unknown"]   # :18
class BatchItemResult(BaseModel): index, source, destination, state, ok, metadata, error, error_code, status_code, attempts   # :21-38

# packages/ai-parrot/src/parrot/interfaces/file/graph.py — reference implementation to copy
upload_files :992 · download_files :1002 · _reject_shared_streams :1014-1022 · _run_batch :1024-1093 · _classify :1095-1111
setup :1113-1125 · handle_file :1127-1132

# GuardedFileServingExtension(manager=, route=, manager_name=, max_bytes=) ; .setup(app)   # entries.py (TASK-3808); web.py:48-60, :78
# gdrive.py: _RETRY_COUNTER, _status_code_of, upload_file, download_file, serving_max_bytes, max_concurrency,
#   GoogleDriveFileManagerError, _is_rate_limited_403
```

### Does NOT Exist
- ~~`BatchRunnerMixin`~~ / shared engine — re-implement; do not import from `graph.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/interfaces/file/gdrive.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/file/graph.py#GraphDriveFileManager._run_batch",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/graph.py#GraphDriveFileManager._classify",
    "sym:packages/ai-parrot/src/parrot/interfaces/file/graph.py#GraphDriveFileManager.setup"
  ]
}
```

---

## Implementation Notes

- Copy `graph.py:992-1111` semantics exactly: `Semaphore(self.max_concurrency)`, results in
  input order, never raise per item, first `auth` failure sets an `asyncio.Event` that marks
  pending items `skipped` (`attempts=0`), per-item `_RETRY_COUNTER.set([0])` for `attempts`,
  outer cancellation propagates (plain `gather`, not `return_exceptions` swallowing
  `CancelledError`).
- `upload_files(items)`: each `(src, dst)`; `src` may be `Path`, `BinaryIO` or `bytes` (bytes →
  `io.BytesIO`); `_reject_shared_streams([src ...])` first (ValueError).
  `download_files(items)`: each `(src_path, dest)`; reject shared destination streams.
  `run_one` for downloads returns `await self.get_file_metadata(src)` after downloading.
- `_classify`: as graph but `GoogleDriveFileManagerError` with status in `{429, 500, 502, 503, 504}`
  or a rate-limited 403 → `"throttled"`.
- `setup(app, route="gdrive", base_url=None)` per spec §3 M4; store `self._serving_ext`;
  `handle_file` falls back to a fresh extension like graph `:1127-1132`.
- Refactor duplicated `source`/`destination` label code into a small `_label(obj)` helper — allowed.

---

## Implementation Blueprint

### Steps (in order)
1. Append batch methods — *why*: AC8.
2. Append `setup` / `handle_file` — *why*: AC22.
3. Drop the `_concrete` fixture; add `test_class_is_concrete`; append tests.

### `gdrive.py` (MODIFY — appended after TASK-3813's `get_file_url`)
```python
    # ---- batch & serving (TASK-3814) -------------------------------------
    async def upload_files(self, items: Sequence[Tuple[Union[Path, BinaryIO, bytes], str]]) -> List[BatchItemResult]:
        """Upload many items; per-item results in input order; never raises per item (AC8)."""
        items = list(items)
        self._reject_shared_streams([src for src, _ in items])

        async def run_one(index: int, src: Any, dst: str) -> FileMetadata:
            return await self.upload_file(io.BytesIO(src) if isinstance(src, bytes) else src, dst)

        return await self._run_batch(items, run_one)

    async def download_files(self, items: Sequence[Tuple[str, Union[Path, BinaryIO]]]) -> List[BatchItemResult]:
        # FILL IN: mirror upload_files for downloads (reject shared destination streams) — bounded by AC8
        raise NotImplementedError

    def _reject_shared_streams(self, objs: List[Any]) -> None:
        # FILL IN: verbatim logic of graph.py:1014-1022
        raise NotImplementedError

    @staticmethod
    def _label(obj: Any) -> str:
        return str(obj) if isinstance(obj, (Path, str)) else ("<bytes>" if isinstance(obj, bytes) else "<stream>")

    async def _run_batch(self, items: List[Tuple[Any, Any]],
                         run_one: Callable[[int, Any, Any], Awaitable[FileMetadata]]) -> List[BatchItemResult]:
        # FILL IN: port graph.py:1024-1093 using _label; succeeded/failed/skipped results — bounded by AC8
        raise NotImplementedError

    def _classify(self, exc: BaseException) -> Tuple[BatchErrorCode, Optional[int]]:
        # FILL IN: graph.py:1095-1111 order, with the throttled rule from Implementation Notes
        raise NotImplementedError

    def setup(self, app: Any, route: str = "gdrive", base_url: Optional[str] = None) -> Any:
        """Mount a size-guarded FileServingExtension (413 above ``serving_max_bytes``)."""
        ext = GuardedFileServingExtension(manager=self, route=route, manager_name=self.manager_name,
                                          max_bytes=self.serving_max_bytes)
        ext.setup(app)
        self._serving_ext = ext
        return ext

    async def handle_file(self, request: Any) -> Any:
        ext = getattr(self, "_serving_ext", None) or GuardedFileServingExtension(
            manager=self, manager_name=self.manager_name, max_bytes=self.serving_max_bytes
        )
        return await ext.handle_file(request)
```

### `test_gdrive_filemanager.py` (MODIFY)
```python
# DELETE the `_concrete` autouse fixture added by TASK-3810 (occurrences: 1 — grep -c 'def _concrete' test_gdrive_filemanager.py)
# APPEND:
def test_class_is_concrete():
    assert not GoogleDriveFileManager.__abstractmethods__

async def test_upload_files_per_item_results_order_and_no_raise(manager): ...
async def test_batch_retries_429_with_retry_after_then_succeeds(manager): ...
async def test_batch_auth_failure_skips_remaining(manager): ...
async def test_batch_concurrency_bounded(manager): ...
async def test_batch_rejects_shared_binaryio(manager): ...
async def test_batch_cancellation_propagates(manager): ...
async def test_download_files_results(manager, tmp_path): ...
async def test_setup_mounts_guarded_extension_and_413_over_limit(manager, aiohttp_client): ...
    # if pytest-aiohttp's aiohttp_client is unavailable, call handle_file with a mocked request (make_mocked_request)
```

### FILL IN checklist
- [ ] `download_files`, `_reject_shared_streams`, `_run_batch`, `_classify`.
- [ ] Remove `_concrete`; 9 tests.

---

## Acceptance Criteria

- [ ] AC8, AC22; `GoogleDriveFileManager` is concrete (AC1 prerequisite).
- [ ] All earlier tests in the module pass without the `_concrete` fixture.

## Validation Commands
- `pytest packages/ai-parrot/tests/interfaces/test_gdrive_filemanager.py -q`

---

## Agent Instructions
Standard. `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` inside the worktree.

---

## Completion Note

*(Agent fills this in when done)*
