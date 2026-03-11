# TASK-294 — Update VideoReelHandler for Storage Configuration

**Feature**: FEAT-043 (Configurable Persistency for Video Reel Generation)
**Spec**: `sdd/specs/persistency-videos-generate-reel-videos.spec.md`
**Status**: done
**Priority**: high
**Effort**: M
**Depends on**: TASK-290
**Parallel**: false
**Parallelism notes**: Modifies `video_reel.py` handler which dispatches to the pipeline modified in TASK-290.

---

## Objective

Update `VideoReelHandler.post()` to read storage configuration (server-side, from environment
or app config) and create the appropriate `FileManagerInterface` instance to pass to the
`generate_video_reel()` pipeline.

## Files to Modify

- `parrot/handlers/video_reel.py` — `VideoReelHandler.post()` and related dispatch logic

## Implementation Details

1. Read storage backend configuration from **server-side config** (per open question decision):
   - Environment variable `VIDEO_REEL_STORAGE_BACKEND` (default: `"fs"`)
   - Environment variable `VIDEO_REEL_STORAGE_BUCKET` (for S3/GCS)
   - Environment variable `VIDEO_REEL_STORAGE_PREFIX` (for S3/GCS path prefix)
   - Or from app config / navconfig settings.

2. Create `FileManagerInterface` instance using `FileManagerFactory.create()` with the resolved config.

3. Pass `file_manager` to the `generate_video_reel()` call.

4. The handler response should include the accessible URL from `AIMessage.files` (which now contains URLs from `get_file_url()`).

5. Ensure the existing `output_directory` logic is preserved when `storage_backend="fs"`.

6. Cleanup of temp uploaded reference images (from `_parse_multipart`) should still happen via `shutil.rmtree`.

## Acceptance Criteria

- [ ] `VideoReelHandler` reads storage config from server-side configuration (env vars or navconfig)
- [ ] Creates appropriate `FileManagerInterface` via `FileManagerFactory`
- [ ] Passes `file_manager` to `generate_video_reel()`
- [ ] Default behavior (no env vars set) uses local filesystem — no regression
- [ ] Response includes accessible URLs for the generated video
- [ ] Reference image temp cleanup still works

## Tests

```python
@pytest.mark.asyncio
async def test_handler_creates_local_fm_by_default(aiohttp_client, app):
    """Without storage env vars, handler uses local filesystem."""
    # POST request, verify LocalFileManager used

@pytest.mark.asyncio
async def test_handler_creates_gcs_fm_from_env(aiohttp_client, app, monkeypatch):
    """With GCS env vars, handler creates GCSFileManager."""
    monkeypatch.setenv("VIDEO_REEL_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("VIDEO_REEL_STORAGE_BUCKET", "my-bucket")
    # Verify GCSFileManager created

@pytest.mark.asyncio
async def test_handler_response_includes_url(aiohttp_client, app):
    """Response body includes URL to generated video."""
    resp = await client.post("/api/v1/google/generation/video_reel", json={...})
    body = await resp.json()
    # Verify URL is present in response
```
