# TASK-212: Tests — VideoReel Reference Image Upload

**Feature**: VideoReel Handler — Reference Image Upload per Scene (FEAT-029)
**Spec**: `sdd/specs/videoreelhandler-upload-images.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2h)
**Depends-on**: TASK-208, TASK-209, TASK-210, TASK-211
**Assigned-to**: claude-sonnet-4-6

---

## Context

After all implementation tasks are done, extend the existing test files with unit and
integration tests covering the new reference image upload behaviour.

---

## Scope

- Extend `tests/test_video_reel_handler.py` — model field tests + handler multipart tests
- Extend `tests/test_google_reel.py` — `_process_scene` reference image wiring tests

**NOT in scope**: end-to-end tests that call real Google APIs.

---

## Files to Modify / Create

| File | Action | Description |
|------|--------|-------------|
| `tests/test_video_reel_handler.py` | modify | Add model + handler multipart tests |
| `tests/test_google_reel.py` | modify | Add `_process_scene` reference image tests |

---

## Test Cases

### Model Tests (add to `tests/test_video_reel_handler.py`)

```python
def test_videoreelscene_has_reference_image_field():
    """VideoReelScene should accept reference_image."""
    from parrot.models.google import VideoReelScene
    scene = VideoReelScene(
        background_prompt="A sunny beach",
        video_prompt="Slow pan",
        duration=5.0,
        reference_image="/tmp/ref.jpg"
    )
    assert scene.reference_image == "/tmp/ref.jpg"

def test_videoreelscene_reference_image_defaults_none():
    from parrot.models.google import VideoReelScene
    scene = VideoReelScene(background_prompt="x", video_prompt="y", duration=5.0)
    assert scene.reference_image is None

def test_videoreelrequest_has_reference_images_field():
    from parrot.models.google import VideoReelRequest
    req = VideoReelRequest(prompt="test")
    assert req.reference_images is None

def test_videoreelrequest_reference_images_can_be_set():
    from parrot.models.google import VideoReelRequest
    req = VideoReelRequest(prompt="test", reference_images=["/tmp/a.jpg", "/tmp/b.jpg"])
    assert req.reference_images == ["/tmp/a.jpg", "/tmp/b.jpg"]
```

### Handler Multipart Tests (add to `tests/test_video_reel_handler.py`)

Look at the existing test file structure to understand how aiohttp test clients are set
up. Key scenarios:

```python
async def test_post_json_body_no_regression(client):
    """Plain JSON POST must still work — no reference images."""
    payload = {
        "prompt": "A scenic mountain reel",
        "scenes": [
            {"background_prompt": "Mountains", "video_prompt": "Pan", "duration": 5.0}
        ]
    }
    resp = await client.post(
        "/api/v1/google/generation/video_reel",
        json=payload,
    )
    assert resp.status == 202
    body = await resp.json()
    assert "job_id" in body


async def test_post_multipart_single_image(client, tmp_path):
    """Multipart POST with one image assigns it to reference_images."""
    import aiohttp
    img = tmp_path / "ref.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0")  # minimal JPEG header

    form = aiohttp.FormData()
    form.add_field("request",
                   '{"prompt": "test reel"}',
                   content_type="application/json")
    form.add_field("image_0",
                   img.read_bytes(),
                   filename="ref.jpg",
                   content_type="image/jpeg")

    resp = await client.post("/api/v1/google/generation/video_reel", data=form)
    assert resp.status == 202


async def test_post_multipart_images_sorted_by_name(client, tmp_path):
    """Images are sorted by part name regardless of insertion order."""
    import aiohttp
    form = aiohttp.FormData()
    form.add_field("request", '{"prompt": "test"}', content_type="application/json")
    # Add image_1 before image_0 intentionally
    form.add_field("image_1", b"FAKE1", filename="b.jpg", content_type="image/jpeg")
    form.add_field("image_0", b"FAKE0", filename="a.jpg", content_type="image/jpeg")

    resp = await client.post("/api/v1/google/generation/video_reel", data=form)
    assert resp.status == 202
    # Verifying internal order requires inspecting req.reference_images in the job,
    # which can be done by mocking GoogleGenAIClient and capturing the request arg.
```

### Generation Pipeline Tests (add to `tests/test_google_reel.py`)

```python
@pytest.mark.asyncio
async def test_process_scene_passes_reference_image(mock_generate_image):
    """_process_scene passes reference_images when scene.reference_image is set."""
    from unittest.mock import AsyncMock, patch
    from pathlib import Path
    from parrot.models.google import VideoReelScene, AspectRatio

    scene = VideoReelScene(
        background_prompt="beach",
        video_prompt="pan",
        duration=5.0,
        reference_image="/tmp/ref.jpg"
    )

    with patch.object(client_instance, 'generate_image', new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = mock_ai_message_with_images(["/tmp/bg.jpg"])
        # ... call _process_scene, assert:
        call_kwargs = mock_gen.call_args.kwargs
        assert call_kwargs["reference_images"] == [Path("/tmp/ref.jpg")]


@pytest.mark.asyncio
async def test_process_scene_no_reference_image(mock_generate_image):
    """_process_scene passes reference_images=None when no reference set."""
    scene = VideoReelScene(background_prompt="beach", video_prompt="pan", duration=5.0)
    # assert generate_image called with reference_images=None
    call_kwargs = mock_gen.call_args.kwargs
    assert call_kwargs.get("reference_images") is None


def test_generate_video_reel_assigns_reference_images_to_scenes():
    """_generate_video_reel assigns request.reference_images[i] to scenes[i]."""
    from parrot.models.google import VideoReelRequest, VideoReelScene

    req = VideoReelRequest(
        prompt="test",
        scenes=[
            VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0),
            VideoReelScene(background_prompt="b", video_prompt="y", duration=5.0),
        ],
        reference_images=["/tmp/img0.jpg", "/tmp/img1.jpg"]
    )
    # After assignment logic runs:
    # req.scenes[0].reference_image == "/tmp/img0.jpg"
    # req.scenes[1].reference_image == "/tmp/img1.jpg"


def test_generate_video_reel_fewer_images_than_scenes():
    """Scenes without a corresponding image keep reference_image=None."""
    req = VideoReelRequest(
        prompt="test",
        scenes=[
            VideoReelScene(background_prompt="a", video_prompt="x", duration=5.0),
            VideoReelScene(background_prompt="b", video_prompt="y", duration=5.0),
        ],
        reference_images=["/tmp/img0.jpg"]  # only 1 for 2 scenes
    )
    # scenes[0].reference_image == "/tmp/img0.jpg"
    # scenes[1].reference_image is None
```

---

## Acceptance Criteria

- [ ] All model field tests pass
- [ ] JSON-only POST regression tests pass
- [ ] Multipart upload handler tests pass (mocked backend)
- [ ] `_process_scene` reference image wiring tests pass
- [ ] `_generate_video_reel` scene assignment tests pass
- [ ] Full test suite has no regressions:
  ```bash
  source .venv/bin/activate
  pytest tests/test_video_reel_handler.py tests/test_google_reel.py -v --no-header
  ```

---

## Agent Instructions

1. Read `tests/test_video_reel_handler.py` and `tests/test_google_reel.py` to understand
   existing fixtures and patterns before adding new tests
2. Add model tests first (no mocking needed)
3. Add handler tests, using the existing aiohttp test client pattern
4. Add generation pipeline tests, adapting mocking to the existing test file patterns
5. Run tests:
   ```bash
   source .venv/bin/activate
   pytest tests/test_video_reel_handler.py tests/test_google_reel.py -v --tb=short 2>&1 | tail -40
   ```
6. Fix any failures before marking done
