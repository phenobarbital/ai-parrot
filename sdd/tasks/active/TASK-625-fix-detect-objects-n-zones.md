# TASK-625: Fix `detect_objects` — N zones from config + wire illumination check

**Feature**: endcap-no-shelves-promotional-fix
**Spec**: `sdd/specs/endcap-no-shelves-promotional-fix.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-624
**Assigned-to**: unassigned

---

## Context

`EndcapNoShelvesPromotional.detect_objects` currently returns `([], [])` unconditionally.
This means `check_planogram_compliance` receives an empty product list, the illumination
check loop never runs, and `illumination_state` defaults to `"ON"` — so endcaps with
the backlight OFF score as 100% compliant.

This task rewrites `detect_objects` to:
1. Read zones from `config.planogram_config["shelves"]`
2. Call `_check_illumination` for zones that require it
3. Return a populated `List[IdentifiedProduct]`

Implements **Module 2** of FEAT-090.

---

## Scope

- Rewrite `detect_objects` in `endcap_no_shelves_promotional.py`
- Read zones from `config.planogram_config["shelves"]` (same structure as `graphic_panel_display`)
- For each zone: if `illumination_status` appears in `visual_features` config → call
  `await self._check_illumination(img, roi, planogram_description)` and attach result
- Zones without `illumination_status` in config → skip illumination check entirely
- Return `(List[IdentifiedProduct], List[ShelfRegion])` — one `IdentifiedProduct` per zone

**NOT in scope**: compliance scoring logic (that's TASK-626). This task only builds
the `IdentifiedProduct` list.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` | MODIFY | Rewrite `detect_objects` method |

---

## Implementation Notes

### Pattern to follow

Mirror how `graphic_panel_display.py:detect_objects` builds `IdentifiedProduct` per zone
(lines ~200–397). Key differences for endcap:
- No `_enrich_zone` call needed — identity is determined by the zone label from config
- Illumination is checked via `_check_illumination` (dedicated call), not `_enrich_zone`
- `confidence` should be `0.5` when zone is considered present (same floor as graphic_panel_display)

### Illumination check logic

```python
# Only check illumination when the zone config declares it
zone_has_illum = any(
    f.lower().startswith("illumination_status:")
    for f in (prod_cfg.visual_features or [])
)

if zone_has_illum:
    illum_state = await self._check_illumination(img, roi, planogram_description)
    visual_features = [illum_state]  # seed first so _extract_illumination_state first-matches
else:
    visual_features = []
```

### Reading zones from config

```python
shelves = (
    (self.config.planogram_config or {}).get("shelves", [])
    or [
        # fallback for legacy 2-zone configs that don't use shelves structure
        {"level": "backlit_panel", "products": [{"name": "backlit_panel", ...}]},
        {"level": "lower_poster",  "products": [{"name": "lower_poster", ...}]},
    ]
)
```

### Key Constraints

- `detect_objects` is `async def` — all calls inside must use `await`
- Use `self.logger.debug(...)` to log illumination state per zone
- `_check_illumination` is called at most once per image (cache result if multiple
  zones need it — same pattern as `graphic_panel_display` `roi_illumination` variable)

### References in Codebase

- `graphic_panel_display.py` lines 200–397 — detect_objects pattern to mirror
- `endcap_no_shelves_promotional.py` lines 334–408 — existing `_check_illumination`
- `abstract.py` — `_extract_illumination_state` (after TASK-624)

---

## Acceptance Criteria

- [ ] `detect_objects` no longer returns `([], [])`
- [ ] Returns one `IdentifiedProduct` per zone defined in `planogram_config["shelves"]`
- [ ] Zones with `illumination_status` in config call `_check_illumination`
- [ ] Zones without `illumination_status` do NOT call `_check_illumination`
- [ ] `illumination_status: ON/OFF` appears as first item in `visual_features` when applicable
- [ ] Legacy 2-zone config (no shelves structure) still works via fallback

## Test Specification

```python
@pytest.mark.asyncio
async def test_detect_objects_returns_products(mock_pipeline, three_zone_config):
    """detect_objects returns one IdentifiedProduct per zone."""
    type_ = EndcapNoShelvesPromotional(mock_pipeline, mock_config(three_zone_config))
    products, shelves = await type_.detect_objects(mock_img(), mock_roi(), [])
    assert len(products) == 3

@pytest.mark.asyncio
async def test_illumination_check_called_for_backlit_zone(mock_pipeline, three_zone_config):
    """_check_illumination is called only for zones with illumination_status."""
    type_ = EndcapNoShelvesPromotional(mock_pipeline, mock_config(three_zone_config))
    with patch.object(type_, '_check_illumination', return_value='illumination_status: ON') as mock_check:
        await type_.detect_objects(mock_img(), mock_roi(), [])
        assert mock_check.call_count == 1  # only header zone has illumination_status

@pytest.mark.asyncio
async def test_no_illumination_config_skips_check(mock_pipeline):
    """Zones without illumination_status in config skip the check."""
    config = {"shelves": [{"level": "poster", "products": [
        {"name": "Poster", "visual_features": ["large graphic"]}
    ]}]}
    type_ = EndcapNoShelvesPromotional(mock_pipeline, mock_config(config))
    with patch.object(type_, '_check_illumination') as mock_check:
        await type_.detect_objects(mock_img(), mock_roi(), [])
        mock_check.assert_not_called()
```

---

## Agent Instructions

1. Read `detect_objects` in `endcap_no_shelves_promotional.py` (current stub)
2. Read `detect_objects` in `graphic_panel_display.py` lines 200–397 for the pattern
3. Rewrite `detect_objects` per scope above
4. Run unit tests
5. Move this file to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
