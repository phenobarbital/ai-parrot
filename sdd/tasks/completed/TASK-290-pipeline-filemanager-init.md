# TASK-290 — Add FileManager Initialization to generate_video_reel()

**Feature**: FEAT-043 (Configurable Persistency for Video Reel Generation)
**Spec**: `sdd/specs/persistency-videos-generate-reel-videos.spec.md`
**Status**: done
**Completed**: 2026-03-11
**Verification**: verified
**Priority**: high
**Effort**: M
**Depends on**: TASK-289
**Parallel**: false
**Parallelism notes**: Modifies `generation.py` which is also modified by TASK-291, TASK-292, TASK-293.

---

## Objective

Refactor `generate_video_reel()` to accept an optional `FileManagerInterface` parameter,
initialize it from `VideoReelRequest.storage_backend` when not provided, and generate a
unique job prefix for organizing artifacts in storage.

## Files to Modify

- `parrot/clients/google/generation.py` — `generate_video_reel()` method

## Implementation Details

1. Add `file_manager: Optional[FileManagerInterface] = None` parameter to `generate_video_reel()`.
2. If `file_manager is None`, create one using `FileManagerFactory.create()`:
   - For `"fs"` backend: use `output_directory` or default `BASE_DIR/static/generated_reels` as `base_path`.
   - For other backends: pass `storage_config` kwargs directly.
3. Generate a unique `job_prefix = f"reels/{uuid.uuid4().hex}"` for organizing this reel's artifacts.
4. Pass `file_manager` and `job_prefix` to `_process_scene()`, `_generate_reel_music()`, and `_create_reel_assembly()` (signature changes only in this task; actual usage in subsequent tasks).
5. After assembly, use `file_manager.get_file_url()` for the response URL.
6. Import `FileManagerInterface` from `parrot.tools.file.abstract` and `FileManagerFactory` from `parrot.tools.file.tool`.

## Acceptance Criteria

- [ ] `generate_video_reel()` accepts optional `file_manager` parameter
- [ ] When `file_manager=None` and `storage_backend="fs"`, a `LocalFileManager` is created with the correct base path
- [ ] When `file_manager` is explicitly provided, it is used directly (no factory call)
- [ ] `job_prefix` is generated and passed to helper methods
- [ ] `AIMessage.files` contains URL from `file_manager.get_file_url()` instead of raw `Path`
- [ ] Backward compatible: calling without `file_manager` produces same behavior as before

## Tests

```python
@pytest.mark.asyncio
async def test_generate_reel_creates_local_fm_by_default(mock_client):
    """Without file_manager, LocalFileManager is created."""
    # Mock FileManagerFactory.create, verify called with "fs"

@pytest.mark.asyncio
async def test_generate_reel_uses_provided_fm(mock_client):
    """Explicit file_manager bypasses factory."""
    fm = AsyncMock(spec=FileManagerInterface)
    # Verify factory.create NOT called

@pytest.mark.asyncio
async def test_response_contains_url(mock_client):
    """AIMessage.files has URL from get_file_url()."""
    fm = AsyncMock(spec=FileManagerInterface)
    fm.get_file_url.return_value = "file:///tmp/reel.mp4"
    # Verify AIMessage.files[0] == "file:///tmp/reel.mp4"
```
