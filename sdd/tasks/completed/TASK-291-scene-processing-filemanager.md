# TASK-291 — Refactor _process_scene() to Use FileManager

**Feature**: FEAT-043 (Configurable Persistency for Video Reel Generation)
**Spec**: `sdd/specs/persistency-videos-generate-reel-videos.spec.md`
**Status**: done
**Completed**: 2026-03-11
**Verification**: verified
**Priority**: high
**Effort**: M
**Depends on**: TASK-290
**Parallel**: false
**Parallelism notes**: Modifies `_process_scene()` in `generation.py`, same file as TASK-290/292/293.

---

## Objective

Refactor `_process_scene()` to save all scene artifacts (background image, video, narration audio)
via `FileManagerInterface` instead of direct filesystem writes. Return storage keys instead of `Path` objects.

## Files to Modify

- `parrot/clients/google/generation.py` — `_process_scene()` method

## Implementation Details

1. Change signature to accept `file_manager: FileManagerInterface` and `job_prefix: str` instead of `output_directory: Path`.
2. After generating background image, extract bytes and save via `file_manager.create_from_bytes(f"{job_prefix}/scenes/scene_{index}_bg.jpeg", img_bytes)`.
3. After generating video, extract bytes and save via `file_manager.create_from_bytes(f"{job_prefix}/scenes/scene_{index}_video.mp4", vid_bytes)`.
4. After generating narration audio, extract bytes and save via `file_manager.create_from_bytes(f"{job_prefix}/scenes/scene_{index}_narration.wav", audio_bytes)`.
5. Return `tuple[str, Optional[str]]` (video storage key, narration storage key) instead of `tuple[Path, Optional[Path]]`.
6. Handle the case where existing `_save_image` and `_save_audio_file` methods return `Path` — extract the bytes before they're saved and use FileManager instead.

## Acceptance Criteria

- [ ] `_process_scene()` accepts `file_manager` and `job_prefix` parameters
- [ ] Background images saved via `file_manager.create_from_bytes()`
- [ ] Scene videos saved via `file_manager.create_from_bytes()`
- [ ] Narration audio saved via `file_manager.create_from_bytes()`
- [ ] Returns storage keys (strings) instead of `Path` objects
- [ ] No direct filesystem writes in `_process_scene()`

## Tests

```python
@pytest.mark.asyncio
async def test_process_scene_saves_via_filemanager():
    fm = AsyncMock(spec=FileManagerInterface)
    fm.create_from_bytes.return_value = True
    # Call _process_scene with fm
    # Verify fm.create_from_bytes called for bg image, video, and narration

@pytest.mark.asyncio
async def test_process_scene_returns_storage_keys():
    fm = AsyncMock(spec=FileManagerInterface)
    result = await client._process_scene(scene, 0, fm, "reels/abc123")
    assert isinstance(result[0], str)  # video key
    assert result[0].startswith("reels/abc123/scenes/")
```
