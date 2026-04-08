# Feature Specification: Fix endcap_no_shelves_promotional

**Feature ID**: FEAT-090
**Date**: 2026-04-07
**Author**: Juan2coder
**Status**: approved
**Target version**: 0.21.0
**Proposal**: flowtask `sdd/proposals/endcap-no-shelves-promotional-fix.proposal.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

`endcap_no_shelves_promotional` is the semantically correct pipeline type for Epson
EcoTank endcap displays and any retail endcap that has:
- No physical products on shelves
- A backlit illuminated header graphic
- One or more promotional graphic zones below

However, the current implementation has three bugs that make it unusable in production:

1. **`_check_illumination` is never called** — the method exists but is not wired into
   the compliance flow. The pipeline always defaults `illumination_state = "ON"`, meaning
   endcaps with the backlight OFF are silently scored as compliant.

2. **Only 2 hardcoded zones** — `backlit_panel` and `lower_poster` are fixed constants.
   Real displays have 3+ zones (header backlit, middle graphic, base panel). The YAML
   config cannot define additional zones.

3. **`ComplianceStatus.MISSING` used incorrectly** — when a zone is found but its
   illumination is wrong, the status is `MISSING` instead of `NON_COMPLIANT`, producing
   misleading reports.

### Goals

- Wire `_check_illumination` into the compliance flow — only for zones that declare
  `illumination_status` in their `visual_features`. Zones without it are not checked
  (supports non-backlit endcaps).
- Support N configurable zones from `planogram_config.shelves` (same YAML structure
  as `graphic_panel_display`), with per-zone text requirements and visual features.
- Fix `ComplianceStatus.MISSING` → `NON_COMPLIANT` when zone is found but light wrong.
- Per-zone mandatory/optional via existing `mandatory` flag and `compliance_threshold`.
- Move `_extract_illumination_state` from `graphic_panel_display.py` to
  `AbstractPlanogramType` so both types share it.
- Zero YAML changes: existing `graphic_panel_display` endcap configs migrate by
  changing only `planogram_type`.

### Non-Goals

- No changes to `graphic_panel_display`, `product_on_shelves`, or `product_counter`.
- No changes to `plan.py`.
- No deprecation of `graphic_panel_display`.
- `detect_objects_roi` hardcoded prompt is out of scope (follow-up).

---

## 2. Architectural Design

### Overview

Changes span two files in `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/`:

1. `abstract.py` — move `_extract_illumination_state` here
2. `endcap_no_shelves_promotional.py` — all compliance logic fixes

**Critical design decision — always use `_check_illumination`, never `ERROR_*` labels:**

`graphic_panel_display` supports two illumination detection paths:
- **Path A (`ERROR_*` label)**: LLM returns `ERROR_LIGHT_IS_OFF` → `confidence=0.0` →
  `zone_found=False` → skips text requirements AND illumination penalty. Zone appears
  as `MISSING` even though the graphic is physically present.
- **Path B (`_check_illumination`)**: dedicated LLM call → zone still `found`
  (confidence=0.5) → illumination penalty applied → text requirements still checked →
  status `NON_COMPLIANT` with human-readable reason.

**`endcap_no_shelves_promotional` MUST use Path B exclusively.** The
`object_identification_prompt` for this type must NOT use `ERROR_LIGHT_IS_OFF`.

**Identity check vs illumination check are orthogonal:**
- Identity: LLM identifies the graphic and verifies `visual_features` ("is the correct
  graphic here?")
- Illumination: `_check_illumination` answers "is the backlight ON or OFF?" — only
  fires when `illumination_status` is in zone's `visual_features` config.

### Component Diagram

```
PlanogramCompliance (plan.py) — unchanged
        │
        └──→ EndcapNoShelvesPromotional — MODIFIED
                    ├── compute_roi()              — unchanged
                    ├── detect_objects_roi()       — unchanged
                    ├── detect_objects()           — FIXED: reads config.shelves,
                    │                                calls _check_illumination per zone
                    │                                (only if illumination_status in
                    │                                visual_features), returns populated
                    │                                List[IdentifiedProduct]
                    ├── _check_illumination()      — unchanged
                    └── check_planogram_compliance() — FIXED: N zones, correct status,
                                                       mandatory/threshold per zone

AbstractPlanogramType (abstract.py) — MODIFIED
        └── _extract_illumination_state()  — MOVED here from graphic_panel_display.py
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractPlanogramType` | inherits + modifies | `_extract_illumination_state` moved here |
| `GraphicPanelDisplay` | sibling | Inherits helper from base — no behavior change |
| `PlanogramCompliance` (plan.py) | called by | No changes |
| `PlanogramConfig.planogram_config["shelves"]` | reads | Same YAML structure, zero config changes |
| `ComplianceResult` / `ComplianceStatus` | uses | NON_COMPLIANT now used correctly |
| `IdentifiedProduct` | produces | `detect_objects` returns populated list |

---

## 3. Module Breakdown

### Module 1: Move `_extract_illumination_state` to `AbstractPlanogramType`

- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py`
- **Responsibility**:
  - Move static method `_extract_illumination_state(features: List[str]) -> Optional[str]`
    from `graphic_panel_display.py` line 849 to `AbstractPlanogramType`
  - Remove from `graphic_panel_display.py` — it inherits from base, zero behavior change
- **Depends on**: nothing

### Module 2: Fix `detect_objects` — wire illumination + N zones from config

- **Path**: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`
- **Responsibility**:
  - Read zones from `config.planogram_config["shelves"]` instead of `_EXPECTED_ELEMENTS`
  - For each zone with `illumination_status` in `visual_features`, call
    `await self._check_illumination(img, roi, planogram_description)` and attach result
  - Zones without `illumination_status` skip the illumination check entirely
  - Return populated `(List[IdentifiedProduct], List[ShelfRegion])` instead of `([], [])`
- **Depends on**: Module 1

### Module 3: Fix `check_planogram_compliance` — N zones + correct status + text/visual

- **Path**: same file as Module 2
- **Responsibility**:
  - Iterate over `planogram_config["shelves"]` instead of `_EXPECTED_ELEMENTS`
  - Zone absent → `MISSING`; zone found but light wrong → `NON_COMPLIANT` + reason in
    `missing_products` (e.g., `"Epson_Top_Backlit_ON — backlight OFF (required: ON)"`)
  - `mandatory` and `compliance_threshold` per shelf drive scoring weight
  - Verify `visual_features` and `text_requirements` from config (same as graphic_panel_display)
  - Return one `ComplianceResult` per shelf level
- **Depends on**: Module 2

### Module 4: Unit tests

- **Path**: `packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py`
- **Responsibility**:
  - 9 unit tests covering all compliance paths (see Section 4)
- **Depends on**: Module 1, 2, 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_extract_illumination_state_in_base` | M1 | Helper accessible from `AbstractPlanogramType` |
| `test_illumination_on_compliant` | M2+M3 | Zone detected, light ON → score 1.0, COMPLIANT |
| `test_illumination_off_noncompliant` | M2+M3 | Zone detected, light OFF → score 0.0, NON_COMPLIANT |
| `test_illumination_off_reason_in_missing` | M3 | `missing_products` contains human-readable reason |
| `test_zone_not_found_missing` | M3 | Zone absent → MISSING |
| `test_no_illumination_config_skips_check` | M2+M3 | Zone without `illumination_status` → no LLM call |
| `test_three_zone_config` | M2+M3 | header + middle + bottom scored independently |
| `test_mandatory_false_zone_missing_still_compliant` | M3 | Optional zone absent → still COMPLIANT |
| `test_status_not_missing_when_found` | M3 | `found=['X']` + light OFF → NON_COMPLIANT not MISSING |

---

## 5. Acceptance Criteria

- [ ] `_extract_illumination_state` in `AbstractPlanogramType`, removed from `graphic_panel_display.py`
- [ ] `detect_objects` returns populated `IdentifiedProduct` list (not `[]`)
- [ ] Illumination check only called for zones with `illumination_status` in `visual_features`
- [ ] Backlight OFF + `illumination_status: ON` expected → zone score = 0.0
- [ ] Status `NON_COMPLIANT` (not `MISSING`) when zone found but light wrong
- [ ] `missing_products` has human-readable reason when illumination fails
- [ ] N zones configurable via `planogram_config["shelves"]`
- [ ] Per-zone `mandatory` and `compliance_threshold` drive scoring
- [ ] All 9 unit tests pass
- [ ] No changes to `plan.py` or any other pipeline type
- [ ] `graphic_panel_display.py` behavior unchanged after helper move
- [ ] Epson EcoTank config switches from `graphic_panel_display` to
      `endcap_no_shelves_promotional` with identical compliance results

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Mirror zone-iteration logic from `graphic_panel_display.py:check_planogram_compliance`
  lines 440–560
- `_check_illumination` is already async — use `await self._check_illumination(...)`
- Logging: `self.logger.info(...)` / `self.logger.debug(...)`

### Known Risks / Gotchas

- `_check_illumination` makes one LLM call per zone with `illumination_status` in
  `visual_features`. 1 call per backlit zone (~2s), acceptable.
- **Do NOT use `ERROR_LIGHT_IS_OFF` label** in `object_identification_prompt` — sets
  `confidence=0.0`, marks zone MISSING, skips text checks. Always use Path B.
- `_extract_illumination_state` is in `graphic_panel_display.py` line 849 — must move
  to `AbstractPlanogramType`. `graphic_panel_display` inherits it, zero behavior change.

### External Dependencies

None.

---

## 7. Open Questions

All resolved — see flowtask proposal for full discussion log.

---

## Worktree Strategy

- **Isolation**: `per-spec` — 2 files, sequential dependency, single worktree
- **PR target**: `main` (ai-parrot)

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-07 | Juan2coder | Ported from flowtask FEAT-011, all questions resolved |
