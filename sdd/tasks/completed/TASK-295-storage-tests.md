# TASK-295 — Unit and Integration Tests for Video Reel Storage

**Feature**: FEAT-043 (Configurable Persistency for Video Reel Generation)
**Spec**: `sdd/specs/persistency-videos-generate-reel-videos.spec.md`
**Status**: done
**Completed**: 2026-03-11
**Verification**: verified
**Priority**: medium
**Effort**: M
**Depends on**: TASK-289, TASK-290, TASK-291, TASK-292, TASK-293, TASK-294
**Parallel**: false
**Parallelism notes**: Tests all prior tasks; must run after all pipeline changes are complete.

---

## Objective

Create comprehensive test suite for the configurable storage feature, covering model changes,
FileManager integration, assembly hybrid pattern, handler configuration, and backward compatibility.

## Files to Create/Modify

- `tests/test_video_reel_storage.py` — new test file

## Implementation Details

### Unit Tests

1. **Model field tests**: Verify `storage_backend` and `storage_config` defaults and validation.
2. **FileManager factory integration**: Verify correct FileManager type created for each backend.
3. **Invalid backend rejection**: Verify `ValidationError` on invalid `storage_backend`.

### Integration Tests (mocked generation)

4. **Local FileManager pipeline**: Mock generation methods, verify `LocalFileManager.create_from_bytes()` called for scene artifacts.
5. **Temp FileManager pipeline**: Same with `TempFileManager`.
6. **Assembly download pattern**: Verify `download_file()` called for each scene before MoviePy.
7. **Assembly upload pattern**: Verify `upload_file()` called for final result.
8. **Assembly temp cleanup**: Verify no leftover temp files.
9. **URL response**: Verify `AIMessage.files` contains URLs from `get_file_url()`.

### Backward Compatibility Tests

10. **Default behavior**: Without storage fields, output matches current behavior.
11. **output_directory override**: Still works with `storage_backend="fs"`.
12. **JSON-only POST**: Handler works without storage fields in request body.

### Handler Tests

13. **Default handler config**: No env vars → LocalFileManager.
14. **GCS handler config**: With env vars → GCSFileManager.
15. **S3 handler config**: With env vars → S3FileManager.

## Acceptance Criteria

- [ ] All unit tests pass
- [ ] All integration tests pass with mocked generation methods
- [ ] Backward compatibility tests confirm no regression
- [ ] Test coverage for all four storage backends (fs, temp, s3, gcs)
- [ ] Handler env var configuration tested
