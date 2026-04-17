# TASK-628: Promote `_check_illumination()` to AbstractPlanogramType

**Feature**: product-on-shelves-illumination
**Spec**: `sdd/specs/product-on-shelves-illumination.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-091. `_check_illumination()` currently lives only in
`EndcapNoShelvesPromotional` (line 454). For `ProductOnShelves` to reuse it,
it must be promoted to `AbstractPlanogramType`. This task does only the
promotion — it does NOT modify the endcap or ProductOnShelves yet.

Spec section: §3 Module 1, §2 "New Public Interfaces".

---

## Scope

- Add `_DEFAULT_ILLUMINATION_PENALTY: float = 1.0` module-level constant to
  `abstract.py` (it currently only exists in the endcap and graphic_panel files).
- Add `async def _check_illumination(...)` to `AbstractPlanogramType` with the
  adapted signature below (copied from endcap lines 454-558, signature adapted).
- Method must retain identical LLM prompt, image-crop logic, and return format.
- Return type changes from `str` → `Optional[str]`: return `None` on LLM
  failure instead of defaulting to ON (allows callers to skip penalty on failure).

**NOT in scope**: Removing the duplicate from endcap (TASK-629). Calling the
method from ProductOnShelves (TASK-630). Any test files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` | MODIFY | Add `_DEFAULT_ILLUMINATION_PENALTY` constant + `_check_illumination()` method |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# abstract.py already has these — do NOT re-import:
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING
from PIL import Image
from parrot.models.detections import Detection, IdentifiedProduct, ShelfRegion
from parrot.models.compliance import ComplianceResult
# NEW — needs to be added for the LLM call in _check_illumination:
from parrot.models.google import GoogleModel   # verified: parrot/models/google.py:12
```

### Existing Signatures to Use

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
_ILLUMINATION_FEATURE_PREFIX = "illumination_status:"  # line 7  ← already exists

class AbstractPlanogramType(ABC):  # line 24
    @staticmethod
    def _extract_illumination_state(features: List[str]) -> Optional[str]:  # line 126
        # Parses "illumination_status: ON/OFF" → "on"/"off" or None

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py
# REFERENCE ONLY — copy the body of this method to abstract.py (with sig changes):
async def _check_illumination(          # line 454
    self,
    img: Image.Image,
    roi: Any,                           # used as fallback crop
    planogram_description: Any,         # used only for brand hint in prompt
    illum_zone_bbox: Optional[Any] = None,  # pixel bbox of zone to crop
) -> str:  # endcap returns str; base class returns Optional[str]
    ...
    # Uses: self.pipeline._downscale_image(roi_crop, max_side=800, quality=82)
    # Uses: self.pipeline.roi_client (async context manager)
    # Uses: await client.ask_to_image(image, prompt, model, no_memory, max_tokens)
    # Uses: GoogleModel.GEMINI_3_FLASH_PREVIEW
```

### New signature for `AbstractPlanogramType._check_illumination()`

```python
async def _check_illumination(
    self,
    img: Image.Image,
    zone_bbox: Optional[Any] = None,          # pixel bbox (x1,y1,x2,y2 attrs)
    roi: Optional[Any] = None,                 # Detection with .bbox (fractional) — fallback
    planogram_description: Optional[Any] = None,  # for brand hint only, may be None
) -> Optional[str]:
    """Check illumination state via LLM vision call on a cropped zone.

    Promoted from EndcapNoShelvesPromotional. Crops ``zone_bbox`` if provided,
    falls back to ROI bbox (fractional → pixel), then full image.

    Args:
        img: Full input PIL image.
        zone_bbox: Optional pixel-coordinate bbox of the illuminated zone.
            Must have ``.x1``, ``.y1``, ``.x2``, ``.y2`` float attributes.
        roi: Optional Detection with a ``.bbox`` attribute (fractional coords).
            Used as fallback when ``zone_bbox`` is None.
        planogram_description: Optional planogram description; used only to
            extract brand name for the LLM prompt.

    Returns:
        ``'illumination_status: ON'``, ``'illumination_status: OFF'``, or
        ``None`` on LLM failure (caller decides how to handle).
    """
```

**Key change**: on LLM failure, return `None` instead of defaulting to ON.
The `except` block must `return None` (not `return "illumination_status: ON"`).

### Does NOT Exist

- ~~`_DEFAULT_ILLUMINATION_PENALTY` in `abstract.py`~~ — does NOT exist yet; add it at module level
- ~~`AbstractPlanogramType._check_illumination()`~~ — does NOT exist yet; this task creates it
- ~~`self.pipeline.vision_client`~~ — does NOT exist; the correct attribute is `self.pipeline.roi_client` (confirmed at endcap line 536)
- ~~`client.completion()`~~ — does NOT exist on roi_client; use `client.ask_to_image(...)` (confirmed at endcap line 537)
- ~~`self.config.get_planogram_description()`~~ — do NOT call this inside `_check_illumination`; the description is passed as a parameter

---

## Implementation Notes

### Crop logic to copy verbatim from endcap lines 479-499

```python
iw, ih = img.size
if zone_bbox is not None:
    x1 = max(0, int(zone_bbox.x1))
    y1 = max(0, int(zone_bbox.y1))
    x2 = min(iw, int(zone_bbox.x2))
    y2 = min(ih, int(zone_bbox.y2))
    roi_crop = img.crop((x1, y1, x2, y2))
elif roi is not None and hasattr(roi, "bbox"):
    x1 = int(roi.bbox.x1 * iw)
    y1 = int(roi.bbox.y1 * ih)
    x2 = int(roi.bbox.x2 * iw)
    y2 = int(roi.bbox.y2 * ih)
    roi_crop = img.crop((x1, y1, x2, y2))
else:
    roi_crop = img.copy()
```

Note the endcap uses `illum_zone_bbox` (pixel coords) and `roi.bbox` (fractional).
In the new base method, `zone_bbox` replaces `illum_zone_bbox` with pixel coords.

### Failure handling change

Endcap:
```python
except Exception as exc:
    self.logger.warning("Illumination check failed: %s — defaulting to ON", exc)
# then falls through to return "illumination_status: ON"
```

New base class:
```python
except Exception as exc:
    self.logger.warning("Illumination check failed: %s — returning None", exc)
    return None
```

### Logging: update the final `self.logger.info` to use generic wording

Replace `"Endcap illumination check →"` with `"Illumination check →"`.

### Key Constraints

- Use `GoogleModel.GEMINI_3_FLASH_PREVIEW` — do NOT hardcode model string
- Use `self.pipeline._downscale_image(roi_crop, max_side=800, quality=82)`
- Use `self.pipeline.roi_client` as async context manager
- Prompt text: copy verbatim from endcap lines 504-531 (the chain-of-thought prompt)
- Use `self.logger.info(...)` and `self.logger.warning(...)` — lazy % formatting

---

## Acceptance Criteria

- [ ] `_DEFAULT_ILLUMINATION_PENALTY = 1.0` added at module level in `abstract.py`
- [ ] `AbstractPlanogramType._check_illumination()` exists with signature above
- [ ] Method has Google-style docstring
- [ ] Returns `None` on LLM failure (not `"illumination_status: ON"`)
- [ ] `from parrot.models.google import GoogleModel` added to `abstract.py` imports
- [ ] `pytest packages/ai-parrot-pipelines/tests/ -v` passes (no regressions)

---

## Test Specification

```python
# Quick smoke test (full tests in TASK-632)
import inspect
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType, _DEFAULT_ILLUMINATION_PENALTY

def test_abstract_has_check_illumination():
    assert hasattr(AbstractPlanogramType, '_check_illumination')
    assert inspect.iscoroutinefunction(AbstractPlanogramType._check_illumination)

def test_default_illumination_penalty_constant():
    assert _DEFAULT_ILLUMINATION_PENALTY == 1.0
```

---

## Agent Instructions

1. Read `abstract.py` in full before editing.
2. Verify the `ask_to_image` call signature in endcap lines 537-543 before copying.
3. Add `from parrot.models.google import GoogleModel` to imports only if not present.
4. Place `_DEFAULT_ILLUMINATION_PENALTY` near top of file after `_ILLUMINATION_FEATURE_PREFIX`.
5. Place `_check_illumination` method in `AbstractPlanogramType` after `_extract_illumination_state` (line 143).
6. Run `pytest packages/ai-parrot-pipelines/tests/ -v` to confirm no regressions.
7. Move this file to `tasks/completed/` and update index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
