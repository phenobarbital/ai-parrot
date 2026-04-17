# TASK-653: ShelfSection models + ShelfConfig extension

**Feature**: endcap-backlit-multitier
**Spec**: `sdd/specs/endcap-backlit-multitier.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is Module 1 of FEAT-096. The new `EndcapBacklitMultitier` planogram type requires
that shelves can declare sub-sections (regions within a shelf, each containing a specific
set of expected products). Currently `ShelfConfig` has no `sections` field.

This task adds:
- `SectionRegion` Pydantic model — x/y ratio boundaries within a shelf
- `ShelfSection` Pydantic model — a named section with region + product list
- `sections: Optional[List[ShelfSection]]` field on `ShelfConfig`
- `section_padding: Optional[float]` field on `ShelfConfig`
- `PlanogramDescriptionFactory` parsing support for the new fields

All other tasks in FEAT-096 depend on these models existing.

---

## Scope

- Add `SectionRegion(BaseModel)` with fields `x_start`, `x_end`, `y_start`, `y_end` (all `float`).
- Add `ShelfSection(BaseModel)` with fields `id: str`, `region: SectionRegion`, `products: List[str]`.
- Add `sections: Optional[List[ShelfSection]] = None` to `ShelfConfig`.
- Add `section_padding: Optional[float] = None` to `ShelfConfig`.
- Update `PlanogramDescriptionFactory.create_planogram_description()` to parse the new
  `sections` and `section_padding` fields when building `ShelfConfig` objects from the
  raw config dict. Existing shelf configs without these fields must continue to parse
  without error (both fields default to `None`).

**NOT in scope**: The `EndcapBacklitMultitier` type class (TASK-655). Tests live in TASK-658.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/detections.py` | MODIFY | Add `SectionRegion`, `ShelfSection` models; extend `ShelfConfig` |
| `packages/ai-parrot/src/parrot/models/detections.py` | MODIFY | Update `PlanogramDescriptionFactory` to parse new fields |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# detections.py already uses these — no new imports needed for the models:
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal, Tuple, Union
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/detections.py:246
class ShelfProduct(BaseModel):
    name: str = Field(description="Product name/model")
    product_type: str = Field(...)
    quantity_range: tuple[int, int] = Field(default=(1, 1))
    position_preference: Optional[Literal["left", "center", "right"]] = Field(default=None)
    mandatory: bool = Field(default=True)
    visual_features: Optional[List[str]] = Field(default=None)

# packages/ai-parrot/src/parrot/models/detections.py:255
class ShelfConfig(BaseModel):
    level: str = Field(...)
    products: List[ShelfProduct] = Field(...)
    compliance_threshold: float = Field(default=0.8)
    allow_extra_products: bool = Field(default=False)
    position_strict: bool = Field(default=False)
    height_ratio: Optional[float] = Field(default=0.30)
    y_start_ratio: Optional[float] = Field(default=None)
    is_background: bool = Field(default=False)
    product_weight: Optional[float] = Field(default=None)
    text_weight: Optional[float] = Field(default=None)
    visual_weight: Optional[float] = Field(default=None)
    # sections and section_padding DO NOT EXIST yet — add them here

# packages/ai-parrot/src/parrot/models/detections.py:351
class PlanogramDescriptionFactory:
    @staticmethod
    def create_planogram_description(config_dict: Dict[str, Any]) -> PlanogramDescription:
        ...
    # The factory builds ShelfConfig objects from raw dicts (around line 461-488).
    # Search for "ShelfConfig(" in create_planogram_description to find the shelf loop.
```

### Does NOT Exist

- ~~`ShelfConfig.sections`~~ — does not exist yet. Added by THIS task.
- ~~`ShelfConfig.section_padding`~~ — does not exist yet. Added by THIS task.
- ~~`ShelfSection`~~ — does not exist yet. Created by THIS task.
- ~~`SectionRegion`~~ — does not exist yet. Created by THIS task.
- ~~`ShelfProduct.section`~~ — not a real field. Section-to-product mapping is via `ShelfSection.products`.
- ~~`ShelfProduct.tier`~~ — not a real field.

---

## Implementation Notes

### Placement in detections.py
Add `SectionRegion` and `ShelfSection` **before** `ShelfConfig` (they are referenced by it).
Place them between `ShelfProduct` (line 246) and `ShelfConfig` (line 255).

### ShelfConfig extension
Add the two new optional fields at the END of `ShelfConfig`, after `visual_weight`:

```python
sections: Optional[List["ShelfSection"]] = Field(
    default=None,
    description="Sub-sections of this shelf for per-section product detection"
)
section_padding: Optional[float] = Field(
    default=None,
    description="Fractional overlap (0.0–1.0) added to each section boundary. "
                "Overrides EndcapGeometry default when set."
)
```

### Factory update
In `PlanogramDescriptionFactory.create_planogram_description()`, find the loop that
builds `ShelfConfig` objects. When constructing each shelf, parse:

```python
raw_sections = shelf_dict.get("sections")  # None for flat shelves
sections = None
if raw_sections:
    sections = [
        ShelfSection(
            id=s["id"],
            region=SectionRegion(**s["region"]),
            products=s.get("products", []),
        )
        for s in raw_sections
    ]
shelf = ShelfConfig(
    ...existing fields...,
    sections=sections,
    section_padding=shelf_dict.get("section_padding"),
)
```

### Key Constraints
- All new models use Google-style docstrings.
- `sections=None` means flat shelf (backward compatible with all existing configs).
- `SectionRegion` fields are plain `float` with `ge=0.0, le=1.0` validators.
- Do NOT add `products` as `List[ShelfProduct]` to `ShelfSection` — it is `List[str]`
  (product names only). The full `ShelfProduct` definitions remain on `ShelfConfig`.

---

## Acceptance Criteria

- [ ] `from parrot.models.detections import ShelfSection, SectionRegion` works
- [ ] `ShelfConfig(level="top", products=[], sections=None)` parses without error
- [ ] `ShelfConfig` with sections list parses correctly
- [ ] Existing `ShelfConfig` dicts without `sections` continue to parse (None default)
- [ ] `PlanogramDescriptionFactory.create_planogram_description(config_with_sections)` returns correct `ShelfSection` objects
- [ ] `ruff check packages/ai-parrot/src/parrot/models/detections.py` — no errors

---

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/planogram/test_endcap_backlit_multitier.py
# (or a new test file — TASK-658 adds the full test suite)

# Quick smoke test:
from parrot.models.detections import ShelfConfig, ShelfSection, SectionRegion

def test_shelf_config_accepts_sections():
    cfg = ShelfConfig(
        level="top",
        products=[],
        sections=[
            ShelfSection(
                id="left",
                region=SectionRegion(x_start=0.0, x_end=0.35, y_start=0.0, y_end=1.0),
                products=["ES-60W", "ES-50"],
            )
        ],
        section_padding=0.05,
    )
    assert cfg.sections is not None
    assert len(cfg.sections) == 1
    assert cfg.section_padding == 0.05

def test_shelf_config_flat_no_sections():
    cfg = ShelfConfig(level="middle", products=[])
    assert cfg.sections is None
    assert cfg.section_padding is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/endcap-backlit-multitier.spec.md` for full context.
2. **Check dependencies** — none. This is the first task.
3. **Verify the Codebase Contract** — read `detections.py` around lines 246-380 to confirm
   current field list. Add new fields exactly as specified.
4. **Update status** in `tasks/.index.json` → `"in-progress"`.
5. **Implement** following the scope above.
6. **Run** `source .venv/bin/activate && pytest packages/ai-parrot/ -k "shelfconfig or section" -v` to verify.
7. **Move this file** to `tasks/completed/TASK-653-shelfconfig-sections-models.md`.
8. **Update index** → `"done"`.
9. **Commit** with message: `sdd: TASK-653 add ShelfSection models and ShelfConfig.sections`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
