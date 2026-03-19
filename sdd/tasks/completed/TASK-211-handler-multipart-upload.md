# TASK-211: VideoReelHandler — Multipart Upload + Temp File Cleanup

**Feature**: VideoReel Handler — Reference Image Upload per Scene (FEAT-029)
**Spec**: `sdd/specs/videoreelhandler-upload-images.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2h)
**Depends-on**: TASK-208
**Assigned-to**: claude-sonnet-4-6

---

## Context

`VideoReelHandler.post()` currently only accepts `application/json`. This task adds
multipart/form-data support so clients can upload reference images alongside the JSON
request payload. Uploaded images are saved to a temp directory, assigned to
`request.reference_images`, and the temp directory is cleaned up after the job completes.

Open question resolution (from spec §7):
- **Cleanup**: Yes — register a cleanup callback after the job completes.
- **Image ordering**: Sort by part name (`image_0`, `image_1`, …).

---

## Scope

- Add `_parse_multipart()` helper method to `VideoReelHandler`
- Update `post()` to detect `multipart/form-data` and branch to `_parse_multipart()`
- Register a temp directory cleanup callback on job completion

**NOT in scope**: `generate_image()` changes, model changes (TASK-208), generation pipeline
changes (TASK-209/210).

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/handlers/video_reel.py` | modify | Add `_parse_multipart()` + update `post()` |

---

## Implementation Details

### Imports to add

```python
import json
import shutil
import tempfile
```

(`json` may already be imported — check first.)

### `_parse_multipart()` helper

```python
async def _parse_multipart(self) -> tuple[dict, list[Path]]:
    """Read multipart body: one 'request' JSON part + zero or more 'image_*' parts.

    Returns:
        Tuple of (parsed JSON dict, list of saved image Paths sorted by part name).
    """
    reader = await self.request.multipart()
    data: dict = {}
    image_parts: list[tuple[str, Path]] = []  # (part_name, path)
    tmp_dir = Path(tempfile.mkdtemp(prefix="videoreel_upload_"))

    async for part in reader:
        if part.name == "request":
            raw = await part.read(decode=True)
            data = json.loads(raw)
        elif part.name and part.name.startswith("image"):
            filename = part.filename or f"{part.name}.bin"
            dest = tmp_dir / filename
            dest.write_bytes(await part.read(decode=True))
            image_parts.append((part.name, dest))

    # Sort by part name to guarantee order (image_0 < image_1 < image_2 …)
    image_parts.sort(key=lambda x: x[0])
    image_paths = [p for _, p in image_parts]
    return data, image_paths
```

### Updated `post()` method

```python
async def post(self) -> web.Response:
    """Submit a video reel generation job and return immediately."""
    content_type = self.request.content_type or ""
    image_paths: list[Path] = []
    tmp_dir: Optional[Path] = None

    try:
        if "multipart" in content_type:
            data, image_paths = await self._parse_multipart()
            # Derive temp dir from first image path (all images share the same tmp_dir)
            if image_paths:
                tmp_dir = image_paths[0].parent
        else:
            data = await self.request.json()
    except Exception:
        return self.error("Invalid request body.", status=400)

    # Extract control keys before Pydantic validation (existing behaviour)
    model = data.pop("model", GoogleModel.GEMINI_3_FLASH_PREVIEW.value)
    output_directory: Optional[str] = data.pop("output_directory", None)
    user_id: Optional[str] = data.pop("user_id", None)
    session_id: Optional[str] = data.pop("session_id", None)

    try:
        req = VideoReelRequest(**data)
    except ValidationError as exc:
        return self.error(str(exc), status=400)

    if image_paths:
        req.reference_images = [str(p) for p in image_paths]

    output_path = Path(output_directory) if output_directory else None

    job_id = str(uuid.uuid4())
    job = self.job_manager.create_job(
        job_id=job_id,
        obj_id="video_reel",
        query=req.prompt,
        user_id=user_id,
        session_id=session_id,
        execution_mode="video_reel",
    )

    # Capture for closure
    _tmp_dir = tmp_dir

    async def run_logic():
        try:
            client = GoogleGenAIClient(model=model)
            async with client:
                result = await client.generate_video_reel(
                    request=req,
                    output_directory=output_path,
                    user_id=user_id,
                    session_id=session_id,
                )
                if hasattr(result, 'model_dump'):
                    return result.model_dump()
                if hasattr(result, 'to_dict'):
                    return result.to_dict()
                return result
        finally:
            # Cleanup temp directory after job completes (success or failure)
            if _tmp_dir and _tmp_dir.exists():
                shutil.rmtree(_tmp_dir, ignore_errors=True)

    await self.job_manager.execute_job(job.job_id, run_logic)

    return self.json_response(
        {
            "job_id": job.job_id,
            "status": job.status.value,
            "message": "Video reel generation started",
            "created_at": job.created_at.isoformat(),
        },
        status=202,
    )
```

Key changes from the original `post()`:
1. Content-type detection at the top
2. `_parse_multipart()` call when multipart detected
3. `req.reference_images` assignment when images present
4. `finally` block inside `run_logic` cleans up `tmp_dir`

---

## Acceptance Criteria

- [ ] `VideoReelHandler` has `_parse_multipart()` method
- [ ] `post()` detects `multipart/form-data` via `content_type`
- [ ] Multipart images are saved to `tempfile.mkdtemp(prefix="videoreel_upload_")`
- [ ] Image parts sorted by part name before path list is built
- [ ] `req.reference_images` is set to list of string paths when images present
- [ ] Plain JSON `POST` is unaffected (no regression)
- [ ] Temp directory is deleted via `shutil.rmtree()` in `finally` after job completes
- [ ] `ruff check parrot/handlers/video_reel.py` passes

---

## Agent Instructions

1. Read `parrot/handlers/video_reel.py` fully
2. Add `import json, import shutil, import tempfile` (check if `json` already present)
3. Add `_parse_multipart()` as a new method on `VideoReelHandler`
4. Replace `post()` body with the updated version above (preserve all existing behaviour)
5. Run linter:
   ```bash
   source .venv/bin/activate
   ruff check parrot/handlers/video_reel.py
   ```
6. Manually verify the original JSON path still works by tracing through the new `post()` logic
