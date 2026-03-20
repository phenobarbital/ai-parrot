# Feature Specification: Configurable Persistency for Video Reel Generation

**Feature ID**: FEAT-043
**Date**: 2026-03-11
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Depends on**: FEAT-008 (REST API — Generate Video Reel), FEAT-029 (VideoReel Handler — Upload Images)

---

## 1. Motivation & Business Requirements

### Problem Statement

`generate_video_reel()` and its helpers (`_process_scene`, `_create_reel_assembly`,
`_generate_reel_music`, `_save_image`, `_save_audio_file`) write all intermediate and
final artifacts directly to the local filesystem using `Path` objects and
`output_directory` parameters. This hardcodes a **local-only** persistence strategy:

- Default output: `BASE_DIR/static/generated_reels`
- Intermediate files (scene images, videos, narration audio, music) written to
  subdirectories of `output_directory`
- Final assembled reel written as `final_reel_{uuid}.{format}` in `output_directory`
- `VideoReelHandler` saves uploaded reference images to `tempfile.mkdtemp()`

This approach fails in production scenarios:
1. **Cloud deployments**: Containers are ephemeral; files disappear on restart.
2. **Multi-node**: Generated files are not accessible across instances.
3. **Cost**: Storing large video files on expensive compute disks vs. cheap object storage.
4. **Serving**: No signed URL generation for secure, time-limited access.

### Goals

1. **Replace direct filesystem operations** in the video reel pipeline with the
   existing `FileManagerInterface` abstraction (`parrot/tools/file/abstract.py`).
2. **Make persistence configurable** via a storage backend parameter (using
   `FileManagerFactory`: `"fs"`, `"temp"`, `"s3"`, `"gcs"`).
3. **Return accessible URLs** (signed URLs for cloud backends, `file://` for local)
   in the `AIMessage` response instead of raw filesystem paths.
4. **Preserve local-first default**: When no backend is configured, behavior
   remains identical to today (local filesystem).

### Non-Goals

- Modifying the video generation pipeline itself (scene breakdown, image/video generation, MoviePy assembly).
- Adding new FileManager implementations — all four already exist.
- Streaming or chunked upload of video files.
- Cleanup/lifecycle policies for stored files (future feature).
- Modifying `_save_image()` or `_save_audio_file()` on `base.py` for non-video-reel use cases.

---

## 2. Architectural Design

### Overview

```
VideoReelHandler / generate_video_reel()
  │
  │  storage_backend: "fs" | "temp" | "s3" | "gcs" (default: "fs")
  │  storage_config: dict (bucket, credentials, base_path, etc.)
  │
  ├── FileManagerFactory.create(storage_backend, **storage_config)
  │       → FileManagerInterface instance
  │
  ├── _process_scene(scene, ..., file_manager)
  │     ├── generate background image → bytes
  │     ├── file_manager.create_from_bytes("scenes/scene_{i}_bg.jpeg", img_bytes)
  │     ├── generate video → bytes
  │     ├── file_manager.create_from_bytes("scenes/scene_{i}_video.mp4", vid_bytes)
  │     ├── generate narration → bytes
  │     └── file_manager.create_from_bytes("scenes/scene_{i}_narration.wav", audio_bytes)
  │
  ├── _generate_reel_music(request, file_manager)
  │     └── file_manager.create_from_bytes("music/bg_music.mp3", music_bytes)
  │
  ├── _create_reel_assembly(scene_outputs, music_path, file_manager, ...)
  │     ├── file_manager.download_file() → temp local paths (for MoviePy)
  │     ├── MoviePy assembly → local temp file
  │     └── file_manager.upload_file(local_temp, "final/final_reel_{uuid}.mp4")
  │
  └── Return AIMessage with file_manager.get_file_url() URLs
```

### Key Design Decision: Hybrid Approach for MoviePy

MoviePy requires local filesystem paths for video processing. The strategy is:

1. **Intermediate artifacts** (scene images, videos, audio): Written via FileManager.
2. **Assembly step**: Downloads intermediate files to a temporary local directory,
   runs MoviePy, then uploads the final result via FileManager.
3. **Cleanup**: Temporary local files used for assembly are cleaned up after upload.

This ensures cloud backends work correctly while MoviePy remains unchanged.

### Integration Points

| Component | Change Type | Notes |
|-----------|-------------|-------|
| `parrot/clients/google/generation.py` — `generate_video_reel()` | modify | Accept `file_manager` parameter; pass to helpers |
| `parrot/clients/google/generation.py` — `_process_scene()` | modify | Use `file_manager` for saving scene artifacts |
| `parrot/clients/google/generation.py` — `_create_reel_assembly()` | modify | Download from file_manager → local temp → MoviePy → upload via file_manager |
| `parrot/clients/google/generation.py` — `_generate_reel_music()` | modify | Use `file_manager` for saving music |
| `parrot/handlers/video_reel.py` — `VideoReelHandler` | modify | Read storage config, create FileManager, pass to pipeline |
| `parrot/models/google.py` — `VideoReelRequest` | modify | Add `storage_backend` and `storage_config` fields |
| `parrot/tools/file/abstract.py` — `FileManagerInterface` | no change | Existing interface is sufficient |
| `parrot/tools/file/tool.py` — `FileManagerFactory` | no change | Existing factory is sufficient |

### 2.1 Model Changes — `VideoReelRequest`

```python
class VideoReelRequest(BaseModel):
    # … existing fields …
    storage_backend: Literal["fs", "temp", "s3", "gcs"] = Field(
        default="fs",
        description=(
            "Storage backend for generated artifacts. "
            "'fs' = local filesystem (default), "
            "'temp' = temporary files (auto-cleanup), "
            "'s3' = AWS S3, 'gcs' = Google Cloud Storage."
        )
    )
    storage_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Backend-specific configuration. "
            "For 's3': {bucket, prefix, region, ...}. "
            "For 'gcs': {bucket, prefix, credentials, ...}. "
            "For 'fs': {base_path: '/path/to/output'}. "
            "For 'temp': {} (no config needed)."
        )
    )
```

### 2.2 FileManager Initialization in Pipeline

```python
async def generate_video_reel(
    self,
    request: VideoReelRequest,
    output_directory: Optional[Path] = None,
    file_manager: Optional[FileManagerInterface] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> AIMessage:
    # Create file manager if not provided
    if file_manager is None:
        storage_config = request.storage_config or {}
        if request.storage_backend == "fs":
            base_path = output_directory or BASE_DIR / 'static' / 'generated_reels'
            storage_config.setdefault("base_path", str(base_path))
        file_manager = FileManagerFactory.create(
            request.storage_backend, **storage_config
        )

    # Generate a unique job directory for this reel
    job_id = uuid.uuid4().hex
    job_prefix = f"reels/{job_id}"
    # … rest of pipeline, passing file_manager and job_prefix to helpers …
```

### 2.3 Scene Processing with FileManager

```python
async def _process_scene(
    self,
    scene: VideoReelScene,
    index: int,
    file_manager: FileManagerInterface,
    job_prefix: str,
    aspect_ratio: str = "16:9",
) -> tuple[str, Optional[str]]:
    """Process a single scene, returning (video_path, narration_path) as storage keys."""

    # Generate background image (existing logic returns PIL Image or bytes)
    bg_message = await self.generate_image(...)
    bg_image_bytes = ...  # extract bytes from response

    # Save via file_manager
    bg_key = f"{job_prefix}/scenes/scene_{index}_bg.jpeg"
    await file_manager.create_from_bytes(bg_key, bg_image_bytes)

    # Generate video (existing logic returns video bytes)
    video_bytes = ...
    video_key = f"{job_prefix}/scenes/scene_{index}_video.mp4"
    await file_manager.create_from_bytes(video_key, video_bytes)

    # Narration (optional)
    narration_key = None
    if scene.narration_text:
        audio_bytes = ...
        narration_key = f"{job_prefix}/scenes/scene_{index}_narration.wav"
        await file_manager.create_from_bytes(narration_key, audio_bytes)

    return (video_key, narration_key)
```

### 2.4 Assembly with Hybrid Local/Remote

```python
async def _create_reel_assembly(
    self,
    scene_outputs: List[tuple[str, Optional[str]]],
    music_key: Optional[str],
    file_manager: FileManagerInterface,
    job_prefix: str,
    transition: str,
    output_format: str,
) -> str:
    """Download from storage → assemble locally → upload final result."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="reel_assembly_") as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Download all scene videos and narrations to local temp
        local_scenes = []
        for video_key, narr_key in scene_outputs:
            local_video = tmp_path / Path(video_key).name
            await file_manager.download_file(video_key, local_video)
            local_narr = None
            if narr_key:
                local_narr = tmp_path / Path(narr_key).name
                await file_manager.download_file(narr_key, local_narr)
            local_scenes.append((local_video, local_narr))

        # Download music
        local_music = None
        if music_key:
            local_music = tmp_path / Path(music_key).name
            await file_manager.download_file(music_key, local_music)

        # Run MoviePy assembly (existing blocking logic in thread)
        output_filename = f"final_reel_{uuid.uuid4().hex}.{output_format}"
        local_output = tmp_path / output_filename

        await asyncio.to_thread(
            self._moviepy_assemble,
            local_scenes, local_music, local_output, transition, output_format
        )

        # Upload final result to storage
        final_key = f"{job_prefix}/final/{output_filename}"
        await file_manager.upload_file(local_output, final_key)

    return final_key
```

### 2.5 Response with Accessible URLs

```python
# In generate_video_reel(), after assembly:
final_url = await file_manager.get_file_url(final_key)

return AIMessageFactory.from_video(
    output=None,
    files=[final_url],  # URL instead of local path
    input=request.prompt,
    model="google-reel-pipeline",
    provider="google_genai",
    usage=CompletionUsage(execution_time=execution_time),
    user_id=user_id,
    session_id=session_id,
)
```

### 2.6 Handler Changes

```python
# In VideoReelHandler.post():
storage_backend = data.get("storage_backend", "fs")
storage_config = data.get("storage_config", {})

file_manager = FileManagerFactory.create(storage_backend, **storage_config)

# Pass to pipeline
result = await client.generate_video_reel(
    request=req,
    file_manager=file_manager,
    ...
)
```

---

## 3. Acceptance Criteria

### Required

- [ ] `VideoReelRequest` has `storage_backend` (default `"fs"`) and `storage_config` (default `None`) fields
- [ ] `generate_video_reel()` accepts an optional `file_manager: FileManagerInterface` parameter
- [ ] When `storage_backend="fs"` and no config, behavior is identical to current (local filesystem, same default directory)
- [ ] Intermediate scene artifacts (images, videos, audio) are saved via `FileManagerInterface`
- [ ] Music is saved via `FileManagerInterface`
- [ ] Final assembled reel is uploaded via `FileManagerInterface`
- [ ] `AIMessage.files` contains accessible URLs (signed for cloud, `file://` for local)
- [ ] Assembly step downloads intermediate files to a temp directory for MoviePy processing
- [ ] Temp assembly directory is cleaned up after upload
- [ ] `VideoReelHandler` reads `storage_backend`/`storage_config` from request and creates appropriate `FileManager`

### Backend-Specific

- [ ] `storage_backend="gcs"` with valid bucket config → files stored in GCS, signed URLs returned
- [ ] `storage_backend="s3"` with valid bucket config → files stored in S3, presigned URLs returned
- [ ] `storage_backend="temp"` → files stored in system temp directory
- [ ] `storage_backend="fs"` with custom `base_path` → files stored at specified location

### Backward Compatibility

- [ ] Existing API calls without `storage_backend` field work unchanged
- [ ] `output_directory` parameter still works as override for local storage
- [ ] No changes required to clients that currently consume `generate_video_reel()`

---

## 4. Test Specification

### Unit Tests (`tests/test_video_reel_storage.py`)

```python
def test_videoreelrequest_storage_defaults():
    """Default storage is local filesystem."""
    req = VideoReelRequest(prompt="test")
    assert req.storage_backend == "fs"
    assert req.storage_config is None

def test_videoreelrequest_storage_s3():
    """S3 backend can be configured."""
    req = VideoReelRequest(
        prompt="test",
        storage_backend="s3",
        storage_config={"bucket": "my-reels", "prefix": "videos/"}
    )
    assert req.storage_backend == "s3"

def test_videoreelrequest_storage_gcs():
    """GCS backend can be configured."""
    req = VideoReelRequest(
        prompt="test",
        storage_backend="gcs",
        storage_config={"bucket": "my-reels-bucket"}
    )
    assert req.storage_backend == "gcs"
```

### Integration Tests (`tests/test_video_reel_storage.py`)

```python
@pytest.mark.asyncio
async def test_generate_reel_with_local_file_manager():
    """Pipeline with explicit LocalFileManager produces local files."""
    fm = LocalFileManager(base_path="/tmp/test_reels")
    # Mock the generation methods, verify fm.create_from_bytes() is called
    # Verify final result is uploaded via fm.upload_file()

@pytest.mark.asyncio
async def test_generate_reel_with_temp_file_manager():
    """Pipeline with TempFileManager stores in temp directory."""
    fm = TempFileManager()
    # Verify artifacts created via TempFileManager

@pytest.mark.asyncio
async def test_assembly_downloads_before_moviepy():
    """Assembly step downloads scene files from storage before processing."""
    fm = AsyncMock(spec=FileManagerInterface)
    # Verify download_file() called for each scene video/audio
    # Verify upload_file() called for final result

@pytest.mark.asyncio
async def test_assembly_cleans_up_temp_dir():
    """Temp directory used for MoviePy assembly is cleaned up."""
    # Verify no leftover temp files after assembly completes

@pytest.mark.asyncio
async def test_response_contains_urls_not_paths():
    """AIMessage.files contains URLs from get_file_url(), not raw paths."""
    fm = AsyncMock(spec=FileManagerInterface)
    fm.get_file_url.return_value = "https://storage.example.com/signed-url"
    # Verify AIMessage.files[0] starts with "https://"
```

### Backward Compatibility Tests

```python
@pytest.mark.asyncio
async def test_default_backend_matches_current_behavior():
    """Without storage_backend, output goes to BASE_DIR/static/generated_reels."""
    # Verify LocalFileManager is created with default path

@pytest.mark.asyncio
async def test_output_directory_override_still_works():
    """output_directory parameter overrides default local path."""
    # Verify LocalFileManager base_path matches output_directory
```

---

## 5. Rollout Plan

### Phase 1: Model Changes
1. Add `storage_backend` and `storage_config` to `VideoReelRequest`

### Phase 2: Pipeline Refactor
1. Add `file_manager` parameter to `generate_video_reel()`
2. Refactor `_process_scene()` to use `FileManagerInterface` for saving artifacts
3. Refactor `_generate_reel_music()` to use `FileManagerInterface`
4. Refactor `_create_reel_assembly()` with download → assemble → upload pattern
5. Update response to use `get_file_url()` for accessible URLs

### Phase 3: Handler Integration
1. Update `VideoReelHandler.post()` to read storage config and create FileManager
2. Pass FileManager through to pipeline

### Phase 4: Tests
1. Unit tests for model changes
2. Integration tests for each storage backend
3. Backward compatibility tests

---

## 6. Security & Compliance

- **Credentials**: Cloud storage credentials (`storage_config`) must come from
  environment variables or secrets management, never hardcoded. The handler should
  validate that `storage_config` does not contain credentials in plaintext when
  received via API — prefer server-side credential resolution.
- **Signed URLs**: Cloud backends return time-limited signed URLs (default 1 hour).
  This prevents unauthorized access to generated content.
- **Temp cleanup**: Assembly temp directories use `tempfile.TemporaryDirectory` context
  manager for guaranteed cleanup, even on failure.
- **Path traversal**: `FileManagerInterface` implementations (especially `LocalFileManager`
  with sandbox mode) prevent path traversal attacks.
- **No new dependencies**: All FileManager implementations already exist in the codebase.

---

## 7. Worktree Strategy

- **Isolation**: `per-spec` (sequential tasks)
- **Worktree name**: `feat-043-persistency-videos`
- **Rationale**: All tasks modify the same files (`generation.py`, `video_reel.py`,
  `models/google.py`) and share imports. Sequential execution prevents conflicts.
- **Cross-feature dependencies**: None that must be merged first. FEAT-008 and FEAT-029
  are already merged/approved.

---

## 8. Open Questions

1. **Intermediate artifact retention**: Should intermediate scene files (images, individual
   videos, audio) be kept in storage or cleaned up after assembly? (Recommend: keep them
   for debugging/reuse, add lifecycle policy later.): keep it.
2. **Server-side storage config**: Should the API accept `storage_config` in the request
   body, or should it be configured server-side only (env vars)? (Recommend: server-side
   default with optional per-request override for authorized users.): server-side for now.
3. **URL expiry**: Should the signed URL expiry time be configurable per request?
   (Recommend: use FileManager defaults for now, make configurable later.)

---

## 9. References

- `parrot/tools/file/abstract.py` — `FileManagerInterface`, `FileMetadata`
- `parrot/tools/file/tool.py` — `FileManagerFactory`
- `parrot/tools/file/local.py` — `LocalFileManager`
- `parrot/tools/file/tmp.py` — `TempFileManager`
- `parrot/tools/file/gcs.py` — `GCSFileManager`
- `parrot/tools/file/s3.py` — `S3FileManager`
- `parrot/clients/google/generation.py` — `generate_video_reel()`, `_process_scene()`, `_create_reel_assembly()`
- `parrot/handlers/video_reel.py` — `VideoReelHandler`
- `parrot/models/google.py` — `VideoReelRequest`, `VideoReelScene`
- FEAT-008: `sdd/specs/rest-api-generate-video-reel.spec.md`
- FEAT-029: `sdd/specs/videoreelhandler-upload-images.spec.md`
