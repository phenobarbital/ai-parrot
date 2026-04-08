# TASK-626: Fix `check_planogram_compliance` — N zones, correct status, text/visual

**Feature**: endcap-no-shelves-promotional-fix
**Spec**: `sdd/specs/endcap-no-shelves-promotional-fix.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-625
**Assigned-to**: unassigned

---

## Context

`check_planogram_compliance` currently iterates over the hardcoded 2-element list
`_EXPECTED_ELEMENTS = ["backlit_panel", "lower_poster"]` and reads illumination from
`identified_products` visual_features — but since `detect_objects` returns `[]`,
those features are never populated. The illumination state defaults to `"ON"` always.

After TASK-625, `detect_objects` returns a populated `IdentifiedProduct` list with
correct illumination states. This task rewrites `check_planogram_compliance` to consume
that list correctly, producing accurate per-zone scores and compliance statuses.

Implements **Module 3** of FEAT-090.

---

## Scope

- Rewrite `check_planogram_compliance` in `endcap_no_shelves_promotional.py`
- Iterate over `planogram_config["shelves"]` — one `ComplianceResult` per shelf level
- For each zone:
  - Not found (no matching `IdentifiedProduct` or confidence=0) → `MISSING`
  - Found, illumination wrong → `NON_COMPLIANT` + reason in `missing_products`
  - Found, illumination correct (or no illumination config) → `COMPLIANT`
- Apply `mandatory` flag and `compliance_threshold` per zone from config
- Verify `text_requirements` from config (same `TextMatcher` as `graphic_panel_display`)
- `missing_products` must include human-readable reason when illumination fails:
  `"Epson_Top_Backlit_ON — backlight OFF (required: ON)"`

**NOT in scope**: `detect_objects` changes (TASK-625). This task only changes the
compliance scoring method.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` | MODIFY | Rewrite `check_planogram_compliance` method |

---

## Implementation Notes

### Pattern to follow

Mirror `graphic_panel_display.py:check_planogram_compliance` lines 412–560.
Key logic to replicate:

```python
# Zone found check (confidence > 0)
zone_found = detected is not None and detected.confidence > 0.0

# Illumination mismatch → NON_COMPLIANT + reason
if zone_found and expected_illum and detected_illum != expected_illum:
    penalty = self._get_illumination_penalty(shelf_cfg)
    zone_score *= (1.0 - penalty)
    missing.append(
        f"{prod_cfg.name} — backlight {detected_illum.upper()} "
        f"(required: {expected_illum.upper()})"
    )

# Status decision
if combined_score >= threshold:
    status = ComplianceStatus.COMPLIANT
elif combined_score == 0.0 and not zone_found:
    status = ComplianceStatus.MISSING     # zone truly absent
else:
    status = ComplianceStatus.NON_COMPLIANT  # found but wrong state
```

### Status rules (critical fix)

| Condition | Status |
|---|---|
| Zone not in image at all | `MISSING` |
| Zone found, light wrong | `NON_COMPLIANT` |
| Zone found, light correct | `COMPLIANT` |

**The old code used `MISSING` for all score=0 cases — this is wrong.**

### Key Constraints

- Use `self._extract_illumination_state(features)` (now in base class after TASK-624)
- Use `TextMatcher.check_text_requirement` for `text_requirements` verification
- Return `List[ComplianceResult]` — one per shelf level
- `_get_illumination_penalty` already exists in `graphic_panel_display` — check if it's
  in `AbstractPlanogramType` or needs to be accessed differently

### References in Codebase

- `graphic_panel_display.py` lines 412–560 — exact pattern to mirror
- `parrot/models/compliance.py` — `ComplianceResult`, `ComplianceStatus`

---

## Acceptance Criteria

- [ ] `check_planogram_compliance` iterates `planogram_config["shelves"]`
- [ ] Returns one `ComplianceResult` per shelf level
- [ ] Zone found, light OFF → `NON_COMPLIANT` (not `MISSING`)
- [ ] Zone absent → `MISSING`
- [ ] `missing_products` includes reason when illumination fails
- [ ] `text_requirements` verified per zone
- [ ] `mandatory: False` zone absent → does not fail overall compliance
- [ ] `compliance_threshold` per shelf respected

## Test Specification

```python
def test_illumination_off_noncompliant(three_zone_config):
    """Zone found with light OFF → NON_COMPLIANT, score 0."""
    products = [
        IdentifiedProduct(product_model="Epson_Top_Backlit_ON",
                          confidence=0.5,
                          visual_features=["illumination_status: OFF"],
                          shelf_location="header"),
        ...
    ]
    type_ = EndcapNoShelvesPromotional(mock_pipeline, mock_config(three_zone_config))
    results = type_.check_planogram_compliance(products, mock_planogram())
    header = next(r for r in results if r.shelf_level == "header")
    assert header.compliance_status == ComplianceStatus.NON_COMPLIANT
    assert header.compliance_score == 0.0
    assert any("backlight OFF" in m for m in header.missing_products)

def test_zone_not_found_missing(three_zone_config):
    """Zone absent from products list → MISSING."""
    type_ = EndcapNoShelvesPromotional(mock_pipeline, mock_config(three_zone_config))
    results = type_.check_planogram_compliance([], mock_planogram())
    assert all(r.compliance_status == ComplianceStatus.MISSING for r in results)

def test_status_not_missing_when_found():
    """found=['X'] + light OFF → NON_COMPLIANT, not MISSING."""
    # Regression: old code used MISSING for all score=0 cases
    ...
    assert result.compliance_status == ComplianceStatus.NON_COMPLIANT
    assert "Epson_Top_Backlit_ON" in result.found_products

def test_mandatory_false_zone_missing_still_compliant():
    """Optional zone absent → overall COMPLIANT."""
    ...
```

---

## Agent Instructions

1. Read current `check_planogram_compliance` in `endcap_no_shelves_promotional.py`
2. Read `check_planogram_compliance` in `graphic_panel_display.py` lines 412–560
3. Rewrite the method per scope and status rules above
4. Run all unit tests
5. Move this file to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Sonnet 4.6
**Date**: 2026-04-08
**Notes**: Rewrote method to iterate planogram_config["shelves"] (N zones), correct status logic (NON_COMPLIANT vs MISSING), illumination penalty per zone, optional zone support, text_requirements via TextMatcher. Added TextMatcher/TextComplianceResult imports. 7/7 acceptance criteria verified.
**Deviations from spec**: none
