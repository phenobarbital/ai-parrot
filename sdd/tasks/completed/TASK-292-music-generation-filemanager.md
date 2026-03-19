# TASK-292 — Refactor _generate_reel_music() to Use FileManager

**Feature**: FEAT-043 (Configurable Persistency for Video Reel Generation)
**Spec**: `sdd/specs/persistency-videos-generate-reel-videos.spec.md`
**Status**: done
**Completed**: 2026-03-11
**Verification**: verified
**Priority**: high
**Effort**: S
**Depends on**: TASK-290
**Parallel**: false
**Parallelism notes**: Modifies `_generate_reel_music()` in `generation.py`, same file as TASK-290/291/293.

---

## Objective

Refactor `_generate_reel_music()` to save the generated music file via `FileManagerInterface`
instead of direct filesystem writes.

## Files to Modify

- `parrot/clients/google/generation.py` — `_generate_reel_music()` method

## Implementation Details

1. Change signature to accept `file_manager: FileManagerInterface` and `job_prefix: str` instead of `output_directory: Path`.
2. After generating music, extract bytes and save via `file_manager.create_from_bytes(f"{job_prefix}/music/bg_music.mp3", music_bytes)`.
3. Return the storage key (string) instead of a `Path` object.
4. Return `None` if music generation is skipped or fails (preserve existing error handling).

## Acceptance Criteria

- [ ] `_generate_reel_music()` accepts `file_manager` and `job_prefix` parameters
- [ ] Music file saved via `file_manager.create_from_bytes()`
- [ ] Returns storage key (string) instead of `Path`
- [ ] No direct filesystem writes in this method

## Tests

```python
@pytest.mark.asyncio
async def test_reel_music_saves_via_filemanager():
    fm = AsyncMock(spec=FileManagerInterface)
    fm.create_from_bytes.return_value = True
    result = await client._generate_reel_music(request, fm, "reels/abc123")
    fm.create_from_bytes.assert_called_once()
    assert isinstance(result, str)
    assert "music" in result
```
