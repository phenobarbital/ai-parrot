# Feature Specification: VideoReel Handler — Reference Image Upload per Scene

**Feature ID**: FEAT-029
**Date**: 2026-03-06
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Depends on**: FEAT-007 (REST API — Generate Video Reel)

---

## 1. Motivation & Business Requirements

### Problem Statement

`VideoReelHandler` currently accepts a JSON body only. There is no mechanism to attach
user-provided images to individual scenes. The background generation step in
`_process_scene` always starts from a text-to-image generation; users cannot seed a
scene with their own visual reference.

The `generate_image` method in the generation mixin already accepts
`reference_images: Optional[List[Union[str, Path, Image.Image]]]`, but nothing in the
pipeline wires a per-scene image to that parameter.

### Goals

1. Add `reference_image: Optional[str]` to `VideoReelScene` Pydantic model.
2. Thread `scene.reference_image` through `_generate_video_reel` → `_process_scene` →
   `generate_image(reference_images=[...])`.
3. Extend `VideoReelHandler.post()` to accept `multipart/form-data`, extract uploaded
   images, and assign them to scenes in order (image 1 → scene 1, image 2 → scene 2, …).

### Non-Goals

- Image validation / resize (passed as-is to `generate_image`).
- Supporting more than one reference image per scene.
- Changing the GET or job-polling endpoints.
- Changes to `video_generation` (Veo) step — reference images apply to background image
  generation only.

---

## 2. Architectural Design

### Overview

```
POST /api/v1/google/generation/video_reel
  Content-Type: multipart/form-data

  Part: request (text/plain or application/json)  ← existing JSON payload
  Part: image_0  (image/*)                        ← reference for scene 0
  Part: image_1  (image/*)                        ← reference for scene 1
  …

VideoReelHandler.post()
  ├── parse multipart: extract JSON + image bytes
  ├── save images to temp dir  →  list of Paths [img0, img1, ...]
  ├── build VideoReelRequest from JSON
  ├── if scenes provided: assign image[i] → scenes[i].reference_image
  │    (if no scenes yet, store images on request for later assignment in
  │     _generate_video_reel after _breakdown_prompt_to_scenes)
  └── dispatch background job as before

_generate_video_reel()
  ├── after scenes are resolved (auto or user-provided):
  │     if request.reference_images:
  │         for i, scene in enumerate(scenes):
  │             if i < len(request.reference_images):
  │                 scene.reference_image = request.reference_images[i]
  └── _process_scene(scene, …)  ← scene.reference_image already set

_process_scene()
  └── generate_image(
          prompt=scene.background_prompt,
          reference_images=[Path(scene.reference_image)] if scene.reference_image else None,
          …
      )
```

### Integration Points

| Component | Change Type | Notes |
|-----------|-------------|-------|
| `parrot/models/google.py` — `VideoReelScene` | modify | Add `reference_image: Optional[str]` field |
| `parrot/models/google.py` — `VideoReelRequest` | modify | Add `reference_images: Optional[List[str]]` field for handler→client transport |
| `parrot/handlers/video_reel.py` — `VideoReelHandler.post()` | modify | Detect multipart, extract images, assign to request |
| `parrot/clients/google/generation.py` — `_generate_video_reel()` | modify | Apply `request.reference_images` onto scenes after breakdown |
| `parrot/clients/google/generation.py` — `_process_scene()` | modify | Pass `scene.reference_image` to `generate_image()` |

### 2.1 Model Changes — `VideoReelScene`

```python
class VideoReelScene(BaseModel):
    background_prompt: str = Field(...)
    foreground_prompt: Optional[str] = Field(None, ...)
    video_prompt: str = Field(...)
    narration_text: Optional[str] = Field(None, ...)
    duration: float = Field(5.0, ...)
    reference_image: Optional[str] = Field(
        None,
        description=(
            "Path to a reference image for background generation. "
            "When provided, passed to generate_image(reference_images=[...]) "
            "to guide the background visual style."
        )
    )
```

### 2.2 Model Changes — `VideoReelRequest`

Add a transport field (not user-settable in JSON, populated by handler):

```python
class VideoReelRequest(BaseModel):
    # … existing fields …
    reference_images: Optional[List[str]] = Field(
        None,
        description=(
            "Ordered list of file paths to reference images, one per scene. "
            "Populated by VideoReelHandler from multipart uploads. "
            "Image i is assigned to scene i."
        )
    )
```

### 2.3 Handler — Multipart Detection

`VideoReelHandler.post()` must handle both content types:

```python
async def post(self) -> web.Response:
    content_type = self.request.content_type or ""

    if "multipart" in content_type:
        data, image_paths = await self._parse_multipart()
    else:
        data = await self.request.json()
        image_paths = []

    # … existing key extraction …
    req = VideoReelRequest(**data)
    if image_paths:
        req.reference_images = [str(p) for p in image_paths]
    # … existing job dispatch …
```

`_parse_multipart()` helper:

```python
async def _parse_multipart(self) -> tuple[dict, list[Path]]:
    """Read multipart body: one JSON part + zero or more image parts."""
    reader = await self.request.multipart()
    data = {}
    image_paths: list[Path] = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="videoreel_upload_"))

    async for part in reader:
        if part.name == "request":
            raw = await part.read(decode=True)
            data = json.loads(raw)
        elif part.name and part.name.startswith("image"):
            filename = part.filename or f"{part.name}.jpg"
            dest = tmp_dir / filename
            dest.write_bytes(await part.read(decode=True))
            image_paths.append(dest)

    # Sort images by part name (image_0, image_1, …) to guarantee order
    image_paths.sort(key=lambda p: p.name)
    return data, image_paths
```

### 2.4 Generation — `_generate_video_reel()`

After scenes are resolved (step 1 or user-provided), apply reference images:

```python
# After scenes are established (auto-breakdown or user-provided)
if request.reference_images:
    for i, scene in enumerate(request.scenes):
        if i < len(request.reference_images):
            scene.reference_image = request.reference_images[i]
```

This mirrors the existing `speech` injection pattern (lines 1910–1920).

### 2.5 Generation — `_process_scene()`

```python
# Step 1. Generate Background
ref_images = [Path(scene.reference_image)] if scene.reference_image else None
bg_message = await self.generate_image(
    prompt=scene.background_prompt,
    reference_images=ref_images,
    aspect_ratio=aspect_ratio,
    output_directory=str(output_dir),
)
```

---

## 3. Acceptance Criteria

### Required

- [ ] `VideoReelScene.reference_image` field exists as `Optional[str]`, default `None`
- [ ] `VideoReelRequest.reference_images` field exists as `Optional[List[str]]`, default `None`
- [ ] `VideoReelHandler.post()` detects `multipart/form-data` and extracts images
- [ ] Images are saved to a temp directory; paths returned as ordered list
- [ ] Handler assigns image paths to `request.reference_images` in order
- [ ] `_generate_video_reel()` applies `request.reference_images[i]` → `scenes[i].reference_image` after scenes are resolved
- [ ] `_process_scene()` passes `reference_images=[Path(scene.reference_image)]` to `generate_image()` when `scene.reference_image` is set
- [ ] Plain JSON `POST` (no images) continues to work unchanged
- [ ] If fewer images are uploaded than scenes, remaining scenes get `reference_image=None`

### Verification

- [ ] `POST` with JSON body only → existing behaviour (no regression)
- [ ] `POST` with multipart (3 images, 3 scenes) → each scene gets its reference image
- [ ] `POST` with multipart (1 image, 3 scenes) → only scene 0 has a reference image

---

## 4. Test Specification

### Unit Tests (`tests/test_video_reel_handler.py` — extend existing)

```python
def test_videoreelscene_has_reference_image_field():
    """VideoReelScene should accept reference_image."""
    scene = VideoReelScene(
        background_prompt="A sunny beach",
        video_prompt="Slow pan",
        duration=5.0,
        reference_image="/tmp/ref.jpg"
    )
    assert scene.reference_image == "/tmp/ref.jpg"

def test_videoreelscene_reference_image_defaults_none():
    scene = VideoReelScene(background_prompt="x", video_prompt="y", duration=5.0)
    assert scene.reference_image is None

def test_videoreelrequest_has_reference_images_field():
    req = VideoReelRequest(prompt="test")
    assert req.reference_images is None
```

### Integration Tests (`tests/test_video_reel_handler.py` — extend existing)

```python
async def test_post_json_only_no_regression(aiohttp_client, app):
    """Plain JSON POST must still work when no images are uploaded."""
    client = await aiohttp_client(app)
    payload = {"prompt": "Test reel", "scenes": [...]}
    resp = await client.post("/api/v1/google/generation/video_reel",
                             json=payload)
    assert resp.status == 202

async def test_post_multipart_assigns_images_to_scenes(aiohttp_client, app, tmp_path):
    """Multipart POST: images are assigned to scenes in order."""
    img = tmp_path / "ref.jpg"
    img.write_bytes(b"FAKEJPEG")

    form = aiohttp.FormData()
    form.add_field("request", json.dumps({"prompt": "Test"}))
    form.add_field("image_0", img.read_bytes(),
                   filename="ref.jpg", content_type="image/jpeg")

    resp = await client.post("/api/v1/google/generation/video_reel", data=form)
    assert resp.status == 202

async def test_post_multipart_fewer_images_than_scenes(aiohttp_client, app, tmp_path):
    """Only supplied images are assigned; extra scenes get reference_image=None."""
    # Send 1 image for a 3-scene request
    ...
```

### Generation Tests (`tests/test_google_reel.py` — extend existing)

```python
def test_process_scene_passes_reference_image(mock_generate_image):
    """_process_scene should pass reference_images when scene.reference_image is set."""
    scene = VideoReelScene(
        background_prompt="beach",
        video_prompt="pan",
        duration=5.0,
        reference_image="/tmp/ref.jpg"
    )
    # Assert generate_image called with reference_images=[Path("/tmp/ref.jpg")]

def test_process_scene_no_reference_image(mock_generate_image):
    """_process_scene should pass reference_images=None when no reference set."""
    scene = VideoReelScene(background_prompt="beach", video_prompt="pan", duration=5.0)
    # Assert generate_image called with reference_images=None
```

---

## 5. Rollout Plan

### Phase 1: Model Changes
1. Add `reference_image` to `VideoReelScene`
2. Add `reference_images` to `VideoReelRequest`

### Phase 2: Generation Pipeline
1. Update `_process_scene()` to pass reference images to `generate_image()`
2. Update `_generate_video_reel()` to apply reference images to scenes

### Phase 3: Handler
1. Add `_parse_multipart()` helper to `VideoReelHandler`
2. Update `post()` to detect content type and branch accordingly

### Phase 4: Tests
1. Extend `tests/test_video_reel_handler.py`
2. Extend `tests/test_google_reel.py`

---

## 6. Security & Compliance

- Uploaded files are saved to a `tempfile.mkdtemp()` directory with a unique prefix.
- File size limits should be enforced at the aiohttp server level (`client_max_size`).
- No user-controlled path traversal risk: filenames are sanitised via `part.filename`
  and stored under a system-generated temp directory.
- Temp files are not automatically cleaned up — a follow-up cleanup task is recommended
  but out of scope for this feature.

---

## 7. Open Questions

1. **Cleanup of temp files**: Should `_parse_multipart()` register a cleanup callback to
   delete temp files after the job completes?: Yes
2. **Image ordering convention**: Should the part name be `image_0`, `image_1`, … or
   simply any `image*` part in arrival order? (Current spec: sort by part name.): sort by part name.
3. **Max images**: Should the handler enforce a maximum number of images equal to the
   number of scenes in the request? (Deferred — excess images are silently ignored.)

---

## 8. References

- FEAT-007: REST API — Generate Video Reel (`sdd/specs/rest-api-generate-video-reel.spec.md`)
- `parrot/models/google.py` — `VideoReelScene`, `VideoReelRequest`
- `parrot/handlers/video_reel.py` — `VideoReelHandler`
- `parrot/clients/google/generation.py` — `_generate_video_reel()`, `_process_scene()`, `generate_image()`
- `generate_image()` already accepts `reference_images: Optional[List[Union[str, Path, Image.Image]]]`
