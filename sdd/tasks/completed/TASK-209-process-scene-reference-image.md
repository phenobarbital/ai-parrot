# TASK-209: _process_scene() — Pass reference_image to generate_image()

**Feature**: VideoReel Handler — Reference Image Upload per Scene (FEAT-029)
**Spec**: `sdd/specs/videoreelhandler-upload-images.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (30min)
**Depends-on**: TASK-208
**Assigned-to**: null

---

## Context

`_process_scene()` currently calls `generate_image()` for the background without any
reference images. Now that `VideoReelScene` carries `reference_image`, this method must
thread it through to `generate_image(reference_images=[...])`.

`generate_image()` already accepts:
```python
reference_images: Optional[List[Union[str, Path, Image.Image]]] = None
```
No changes to `generate_image()` are needed.

---

## Scope

- Modify the background `generate_image()` call inside `_process_scene()` to pass
  `reference_images` when `scene.reference_image` is set.

**NOT in scope**: foreground image generation, video generation step, or handler changes.

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `parrot/clients/google/generation.py` | modify | Update background `generate_image()` call in `_process_scene()` |

---

## Implementation Details

Locate `_process_scene()` in `generation.py`. Find the background generation block (Step 1):

```python
# BEFORE
bg_message = await self.generate_image(
    prompt=scene.background_prompt,
    aspect_ratio=aspect_ratio,
    output_directory=str(output_dir)
)
```

Replace with:

```python
# AFTER
ref_images = [Path(scene.reference_image)] if scene.reference_image else None
bg_message = await self.generate_image(
    prompt=scene.background_prompt,
    reference_images=ref_images,
    aspect_ratio=aspect_ratio,
    output_directory=str(output_dir),
)
```

`Path` is already imported in the file. Confirm before adding a duplicate import.

---

## Acceptance Criteria

- [ ] `_process_scene()` passes `reference_images=[Path(scene.reference_image)]` when `scene.reference_image` is not None
- [ ] `_process_scene()` passes `reference_images=None` when `scene.reference_image` is None
- [ ] All other `generate_image()` calls in `_process_scene()` (foreground) are untouched
- [ ] `ruff check parrot/clients/google/generation.py` passes

---

## Agent Instructions

1. Read `parrot/clients/google/generation.py`, locate `_process_scene()`
2. Find the background `generate_image()` call (look for `scene.background_prompt`)
3. Apply the change above
4. Verify `Path` is already imported (it is — used elsewhere in the file)
5. Run linter:
   ```bash
   source .venv/bin/activate
   ruff check parrot/clients/google/generation.py
   ```
