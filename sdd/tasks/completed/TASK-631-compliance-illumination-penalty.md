# TASK-631: Add Illumination Penalty to `ProductOnShelves.check_planogram_compliance()`

**Feature**: FEAT-091 — Product-On-Shelves Illumination Support
**Spec**: `sdd/specs/product-on-shelves-illumination.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-628, TASK-630, TASK-633
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-091. After `plan.py` Step 3.5 (TASK-630) seeds
`visual_features` with the illumination status, the compliance checker must
read it and apply a configurable penalty when the detected state mismatches
the expected state from the raw config.

Default penalty for `ProductOnShelves` is **0.5** (different from endcap's 1.0).
This means a header graphic with the backlight OFF scores 50% of its presence
contribution — presence is still counted, illumination halves the result.

**Dependency on TASK-633**: this task reuses the insertion-index-capture
pattern introduced by TASK-633 (Module 6 Bug 2 fix) for updating the
`found_readable` label on illumination mismatches. Do not start until
TASK-633 is complete.

Spec section: §3 Module 4, §2 Component Diagram.

---

## Scope

In `check_planogram_compliance()`, within the per-shelf product matching loop
(lines 490-513):

1. After a match is found (inside `if match_result:`), read `illumination_required`
   and `illumination_penalty` from the raw product config dict.
2. Call `self._extract_illumination_state(identified_product.visual_features)` to
   get the detected state.
3. If `illumination_required` is set AND detected state is not None AND states
   mismatch: record an illumination penalty multiplier for this match.
4. After the shelf's matching loop completes, apply the penalty by reducing
   `basic_score` proportionally (one product's penalty = `(1.0 - penalty) / len(expected)`
   subtracted from what a full match would contribute).
5. Update `missing` list to include: `"{name} — backlight {detected} (required: {expected})"`.
6. Update the found product label in `found_readable` to reflect the actual
   illumination state: `"{original_label} (LIGHT_{detected.upper()})"`.
7. Log: `self.logger.info("Illumination check for %s: expected=%s detected=%s", name, expected, detected)`

**NOT in scope**: The `detect_objects()` enrichment (TASK-630). Unit tests (TASK-632).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | Add illumination penalty in `check_planogram_compliance()` matching loop |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# product_on_shelves.py already imports everything needed.
# No new imports required for this task.
# AbstractPlanogramType._extract_illumination_state is a @staticmethod — call as:
#   self._extract_illumination_state(features)   OR
#   AbstractPlanogramType._extract_illumination_state(features)
```

### Existing Signatures to Use

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
@staticmethod
def _extract_illumination_state(features: List[str]) -> Optional[str]:  # line 126
    # Returns "on" or "off" (lowercase) or None if no illumination_status entry

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py

# Per-shelf matching loop structure (lines 486-513):
matched = [False] * len(expected)          # line 486
consumed = [False] * len(found_keys)       # line 487
visual_feature_scores = []                 # line 488

for i, ek in enumerate(expected):          # line 490
    for j, fk in enumerate(found_keys):    # line 491
        if matched[i] or consumed[j]:
            continue
        match_result = _matches(ek, fk)
        if match_result:
            matched[i] = True
            consumed[j] = True
            globally_matched_keys.add(fk)
            shelf_product = expected_products[i]        # ShelfProduct Pydantic
            identified_product = found_products[j]      # IdentifiedProduct
            if hasattr(shelf_product, 'visual_features') and shelf_product.visual_features:
                detected_features = getattr(identified_product, 'visual_features', []) or []
                if detected_features:
                    vf_score = self._calculate_visual_feature_match(...)
                    visual_feature_scores.append(vf_score)
            break

# After the matching loop:
missing = [expected_readable[i] for i, ok in enumerate(matched) if not ok]  # line 520

# found_readable built at lines 515-518:
found_readable = []
for (used, (f_ptype, f_base), (_, _, original_label)) in zip(consumed, found_keys, found_lookup):
    found_readable.append(original_label)

# basic_score computed at lines 547-549:
basic_score = sum(1 for ok in matched if ok) / (len(expected) or 1.0)

# Raw config access (pattern already at line 360):
_pcfg = getattr(planogram_description, 'planogram_config', None) or {}
# raw_shelves = _pcfg.get("shelves", [])
```

### Raw config fields to read (NOT Pydantic)

```python
# Access raw product config to read non-Pydantic fields:
_pcfg = getattr(planogram_description, 'planogram_config', None) or {}
raw_shelves = _pcfg.get("shelves", [])
# Find raw product dict matching the current shelf index and product index:
# raw_shelves[shelf_idx]["products"][product_idx]
# OR iterate raw_shelves matching by shelf level name + product name.

# Fields to read from raw product dict:
raw_illum_required = raw_prod.get("illumination_required")   # str "on"/"off" or None
raw_illum_penalty  = raw_prod.get("illumination_penalty", 0.5)  # float, default 0.5
```

### Does NOT Exist

- ~~`ShelfProduct.illumination_required`~~ — NOT a Pydantic field; `shelf_product.illumination_required` will raise AttributeError
- ~~`ShelfProduct.illumination_penalty`~~ — NOT a Pydantic field; read from raw dict only
- ~~`found_names`~~ — this variable does NOT exist in this method; the variable is `found_readable` (built at lines 515-518)
- ~~`zone_score`~~ — this variable does NOT exist; the score variable is `basic_score` (line 547)

---

## Implementation Notes

### Strategy: track penalty during matching, apply after loop

Add a `illum_penalty_delta: float = 0.0` accumulator before the `for i, ek` loop.
Inside the `if match_result:` block, after the visual_feature scoring:

```python
# Illumination penalty (opt-in — only when raw config declares illumination_required)
raw_illum_req = _get_raw_illum_required(raw_shelves, shelf_level, shelf_product.name)
if raw_illum_req is not None:
    detected_illum = self._extract_illumination_state(
        getattr(identified_product, 'visual_features', []) or []
    )
    self.logger.info(
        "Illumination check for %s: expected=%s detected=%s",
        shelf_product.name, raw_illum_req, detected_illum
    )
    if detected_illum is not None and detected_illum != raw_illum_req.lower():
        raw_penalty = _get_raw_illum_penalty(raw_shelves, shelf_level, shelf_product.name)
        # Each matched product contributes 1/len(expected) to basic_score.
        # Apply penalty: subtract penalty_fraction * (1/len(expected)).
        illum_penalty_delta += raw_penalty * (1.0 / max(1, len(expected)))
        missing.append(...)   # wait — missing is built after the loop; use a separate list
```

**Better approach**: collect illumination mismatches in a list during the loop,
then apply all at once after `basic_score` is computed.

```python
# Before the for-i loop:
illum_mismatches: list[tuple[int, int, str, str, float]] = []
# (i_expected_idx, j_found_idx, detected_state, expected_state, penalty_float)

# Inside if match_result, after visual_feature_scores:
raw_illum_req = _find_raw_illum_required(raw_shelves, shelf_level, shelf_product.name)
if raw_illum_req is not None:
    detected_illum = self._extract_illumination_state(
        getattr(identified_product, 'visual_features', []) or []
    )
    self.logger.info(
        "Illumination check for %s: expected=%s detected=%s",
        shelf_product.name, raw_illum_req, detected_illum,
    )
    if detected_illum is not None and detected_illum != raw_illum_req.strip().lower():
        raw_penalty = _find_raw_illum_penalty(raw_shelves, shelf_level, shelf_product.name)
        illum_mismatches.append((i, j, detected_illum, raw_illum_req.strip().lower(), raw_penalty))

# After the for-i loop, before basic_score computation:
# (lines 515-549 area)

# Apply illumination penalty to basic_score:
# basic_score = sum(1 for ok in matched if ok) / (len(expected) or 1.0)
basic_score = sum(1 for ok in matched if ok) / (len(expected) or 1.0)
for (i_idx, j_idx, detected, expected_s, penalty) in illum_mismatches:
    # Reduce this product's contribution: was 1/N, becomes (1-penalty)/N
    basic_score -= penalty * (1.0 / max(1, len(expected)))
basic_score = max(0.0, basic_score)

# Append illumination mismatch entries to missing list:
for (i_idx, j_idx, detected, expected_s, penalty) in illum_mismatches:
    prod_name = expected_readable[i_idx]
    missing.append(
        f"{prod_name} — backlight {detected.upper()} (required: {expected_s.upper()})"
    )

# Update found_readable labels for illumination mismatch products:
# found_readable is built from found_lookup in the lines 515-518 loop.
# After that loop, patch the entries for mismatched found products:
mismatch_j_set = {j_idx: detected for (_, j_idx, detected, _, _) in illum_mismatches}
for k, (used, (f_ptype, f_base), (_, _, original_label)) in enumerate(
    zip(consumed, found_keys, found_lookup)
):
    label = original_label
    # found_keys index k maps to the k-th found product
    if k in mismatch_j_set:
        label = f"{original_label} (LIGHT_{mismatch_j_set[k].upper()})"
    found_readable.append(label)
```

### Helper: look up raw illumination fields by shelf level + product name

Implement as a local helper function inside `check_planogram_compliance` (or inline):

```python
def _find_raw_illum_required(raw_shelves, shelf_level, product_name):
    for rs in raw_shelves:
        if rs.get("level") == shelf_level:
            for rp in rs.get("products", []):
                if rp.get("name") == product_name:
                    return rp.get("illumination_required")  # None if absent
    return None

def _find_raw_illum_penalty(raw_shelves, shelf_level, product_name):
    for rs in raw_shelves:
        if rs.get("level") == shelf_level:
            for rp in rs.get("products", []):
                if rp.get("name") == product_name:
                    return float(rp.get("illumination_penalty", 0.5))
    return 0.5  # ProductOnShelves default
```

### Default penalty

`ProductOnShelves` default illumination penalty = **0.5** (not 1.0).
The endcap uses 1.0 (`_DEFAULT_ILLUMINATION_PENALTY`). Do NOT import or reuse
the endcap/abstract constant here — hardcode `0.5` as the fallback default in
`_find_raw_illum_penalty`.

### Key Constraints

- Do NOT call `_check_illumination` from this method (illumination is already in
  `visual_features` after TASK-630's enrichment in `detect_objects`)
- If `illumination_required` absent from raw config → no penalty, no mismatch entry
- If `detected_illum is None` (LLM failed) → no penalty, no mismatch entry
- Apply penalty proportionally: each of N expected products contributes `1/N` to
  `basic_score`; penalty reduces that one product's contribution by `penalty * 1/N`
- Existing configs without `illumination_required` must produce identical scores

---

## Acceptance Criteria

- [ ] Illumination penalty applied in `check_planogram_compliance()` after product matching
- [ ] Default penalty 0.5 used when `illumination_penalty` absent from config
- [ ] `missing` list includes `"{name} — backlight {detected} (required: {expected})"` on mismatch
- [ ] `found_readable` label updated to `"{label} (LIGHT_{state})"` on mismatch
- [ ] No penalty when `illumination_required` absent
- [ ] No penalty when detected state is `None`
- [ ] `self.logger.info("Illumination check for %s: expected=%s detected=%s", ...)` present
- [ ] `pytest packages/ai-parrot-pipelines/tests/ -v` passes

---

## Agent Instructions

1. Verify TASK-628, TASK-630, and TASK-633 are in `tasks/completed/` before starting.
2. Read `product_on_shelves.py` lines 344 to 677 carefully before editing.
3. Extract the raw config once at the top of the method (alongside the existing
   `_pcfg` at line 360) and pass `raw_shelves` into the per-shelf loop.
4. Add `illum_mismatches` accumulator before the matching loop.
5. After `basic_score`, apply penalties and append to `missing`/`found_readable`.
6. Run full test suite.
7. Move this file to `tasks/completed/` and update index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
