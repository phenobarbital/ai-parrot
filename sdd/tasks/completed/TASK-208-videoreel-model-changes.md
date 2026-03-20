# TASK-208: Model Changes — VideoReelScene.reference_image + VideoReelRequest.reference_images

**Feature**: VideoReel Handler — Reference Image Upload per Scene (FEAT-029)
**Spec**: `sdd/specs/videoreelhandler-upload-images.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (30min)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

`VideoReelScene` has no field to carry a reference image path. `VideoReelRequest` has no
field to transport the list of uploaded image paths from the handler to the generation
client. This task adds both fields so the rest of the pipeline can use them.

---

## Scope

- Add `reference_image: Optional[str]` to `VideoReelScene`
- Add `reference_images: Optional[List[str]]` to `VideoReelRequest`

**NOT in scope**: handler changes, generation changes, tests.

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/models/google.py` | modify | Add fields to `VideoReelScene` and `VideoReelRequest` |

---

## Implementation Details

### `VideoReelScene` — add field at the end of the model

```python
reference_image: Optional[str] = Field(
    None,
    description=(
        "Path to a reference image for background generation. "
        "When provided, passed to generate_image(reference_images=[...]) "
        "to guide the background visual style."
    )
)
```

### `VideoReelRequest` — add field at the end of the model

```python
reference_images: Optional[List[str]] = Field(
    None,
    description=(
        "Ordered list of file paths to reference images, one per scene. "
        "Populated by VideoReelHandler from multipart uploads. "
        "Image i is assigned to scene i."
    )
)
```

Make sure `List` is imported from `typing` if not already present.

---

## Acceptance Criteria

- [ ] `VideoReelScene` has `reference_image: Optional[str] = None`
- [ ] `VideoReelRequest` has `reference_images: Optional[List[str]] = None`
- [ ] Both fields default to `None` — existing JSON payloads without these fields are unaffected
- [ ] `ruff check parrot/models/google.py` passes

---

## Agent Instructions

1. Read `parrot/models/google.py`, locate `VideoReelScene` and `VideoReelRequest`
2. Add the two fields as specified above
3. Verify existing fields are untouched
4. Run linter:
   ```bash
   source .venv/bin/activate
   ruff check parrot/models/google.py
   ```
5. Quick smoke test:
   ```bash
   python -c "
   from parrot.models.google import VideoReelScene, VideoReelRequest
   s = VideoReelScene(background_prompt='x', video_prompt='y', duration=5.0)
   assert s.reference_image is None
   r = VideoReelRequest(prompt='test')
   assert r.reference_images is None
   print('OK')
   "
   ```
