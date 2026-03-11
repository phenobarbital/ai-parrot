# TASK-293 — Refactor _create_reel_assembly() with Hybrid Storage Pattern

**Feature**: FEAT-043 (Configurable Persistency for Video Reel Generation)
**Spec**: `sdd/specs/persistency-videos-generate-reel-videos.spec.md`
**Status**: done
**Completed**: 2026-03-11
**Verification**: verified
**Priority**: high
**Effort**: L
**Depends on**: TASK-291, TASK-292
**Parallel**: false
**Parallelism notes**: Depends on TASK-291/292 outputs (storage keys). Modifies same file.

---

## Objective

Refactor `_create_reel_assembly()` to implement the hybrid download→assemble→upload pattern:
download intermediate files from storage to a temporary local directory for MoviePy processing,
then upload the final assembled video back to storage.

## Files to Modify

- `parrot/clients/google/generation.py` — `_create_reel_assembly()` method

## Implementation Details

1. Change signature to accept:
   - `scene_outputs: List[tuple[str, Optional[str]]]` (storage keys instead of Paths)
   - `music_key: Optional[str]` (storage key instead of Path)
   - `file_manager: FileManagerInterface`
   - `job_prefix: str`
   - `transition: str`
   - `output_format: str`

2. Use `tempfile.TemporaryDirectory(prefix="reel_assembly_")` context manager:
   - Download all scene videos from storage: `file_manager.download_file(video_key, local_path)`
   - Download all narration audio from storage (if present)
   - Download music from storage (if present)

3. Run MoviePy assembly on local temp files (existing blocking logic in thread).
   - Extract the MoviePy logic into a private `_moviepy_assemble()` method if not already separate.

4. Upload the final assembled video: `file_manager.upload_file(local_output, final_key)`.

5. Return the final storage key (string).

6. Temp directory is automatically cleaned up by context manager, even on failure.

## Acceptance Criteria

- [ ] `_create_reel_assembly()` accepts storage keys and `file_manager` instead of `Path` objects
- [ ] Downloads scene videos, narrations, and music from storage to temp directory
- [ ] MoviePy assembly runs on local temp files (no change to assembly logic)
- [ ] Final video uploaded to storage via `file_manager.upload_file()`
- [ ] Temp directory cleaned up after assembly (context manager)
- [ ] Returns storage key (string) for the final video
- [ ] Handles case where `storage_backend="fs"` efficiently (LocalFileManager download is essentially a copy)

## Tests

```python
@pytest.mark.asyncio
async def test_assembly_downloads_scenes():
    fm = AsyncMock(spec=FileManagerInterface)
    scene_outputs = [("reels/abc/scenes/s0_video.mp4", "reels/abc/scenes/s0_narr.wav")]
    await client._create_reel_assembly(scene_outputs, None, fm, "reels/abc", "cut", "mp4")
    # Verify download_file called for video and narration
    assert fm.download_file.call_count >= 2

@pytest.mark.asyncio
async def test_assembly_uploads_final():
    fm = AsyncMock(spec=FileManagerInterface)
    result = await client._create_reel_assembly(...)
    fm.upload_file.assert_called_once()
    assert result.startswith("reels/abc/final/")

@pytest.mark.asyncio
async def test_assembly_cleans_up_temp():
    """No temp files left after assembly."""
    # Verify TemporaryDirectory context manager is used
```
