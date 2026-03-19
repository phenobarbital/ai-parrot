# TASK-210: _generate_video_reel() — Apply reference_images onto scenes

**Feature**: VideoReel Handler — Reference Image Upload per Scene (FEAT-029)
**Spec**: `sdd/specs/videoreelhandler-upload-images.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (30min)
**Depends-on**: TASK-208
**Assigned-to**: claude-sonnet-4-6

---

## Context

After scenes are resolved (either from `request.scenes` or from `_breakdown_prompt_to_scenes()`),
`_generate_video_reel()` must assign `request.reference_images[i]` to `scenes[i].reference_image`
for each scene that has a corresponding uploaded image.

This mirrors the existing pattern used for `speech`:
```python
# Existing speech injection (lines ~1910-1920)
if request.speech:
    for i, scene in enumerate(request.scenes):
        if i < len(request.speech):
            scene.narration_text = request.speech[i]
        else:
            scene.narration_text = None
```

---

## Scope

- Add a reference image injection block to `_generate_video_reel()`, after scene
  resolution and after the speech injection block.

**NOT in scope**: cleanup of temp files (TASK-211), handler changes, or `_process_scene()`.

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/clients/google/generation.py` | modify | Add reference image assignment block in `_generate_video_reel()` |

---

## Implementation Details

In `_generate_video_reel()`, locate the block after speech injection (around line 1920).
Add the following block immediately after it:

```python
# Apply reference images to scenes (one image per scene, by index)
if request.reference_images:
    for i, scene in enumerate(request.scenes):
        if i < len(request.reference_images):
            scene.reference_image = request.reference_images[i]
        # If no image for this scene, leave scene.reference_image as None (already default)
```

The placement must be **after** scene breakdown (step 1) and **after** speech injection
so all scenes are fully resolved before images are applied.

---

## Acceptance Criteria

- [ ] `_generate_video_reel()` assigns `request.reference_images[i]` to `scenes[i].reference_image` when `request.reference_images` is set
- [ ] Scenes beyond the length of `request.reference_images` keep `reference_image=None`
- [ ] When `request.reference_images` is `None`, no assignment is made (existing behaviour preserved)
- [ ] Assignment happens after `_breakdown_prompt_to_scenes()` and after speech injection
- [ ] `ruff check parrot/clients/google/generation.py` passes

---

## Agent Instructions

1. Read `parrot/clients/google/generation.py`, locate `_generate_video_reel()`
2. Find the speech injection block (search for `request.speech`)
3. Add the reference images injection block immediately after the speech block
4. Run linter:
   ```bash
   source .venv/bin/activate
   ruff check parrot/clients/google/generation.py
   ```
