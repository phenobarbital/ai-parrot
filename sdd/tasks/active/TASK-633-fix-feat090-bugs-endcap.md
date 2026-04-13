# TASK-633: Fix FEAT-090 Latent Bugs in EndcapNoShelvesPromotional

**Feature**: product-on-shelves-illumination
**Spec**: `sdd/specs/product-on-shelves-illumination.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-629
**Assigned-to**: unassigned

---

## Context

Module 6 of FEAT-091. Two latent correctness bugs were identified in the
FEAT-090 code review but never patched. Both live in
`EndcapNoShelvesPromotional.check_planogram_compliance()` — the same method we
are already touching in TASK-629 (Module 2 removes the duplicate
`_check_illumination`). We fix them here to avoid a second round-trip over
the same code.

**Why this belongs to FEAT-091**:
- Module 4 (TASK-631) reuses the "insertion-index-capture" pattern from Bug 2's
  fix for its own `found_names`/`found_readable` label updates. Fixing both in
  the same feature keeps the pattern canonical.
- Neither bug manifests in current production configs (each Epson shelf has
  exactly one product with text_requirements) but both will surface the moment
  a config has multi-product shelves with text requirements.

Spec section: §3 Module 6.

---

## Scope

Two independent fixes in
`packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py`:

### Bug 1 — `text_score` reset inside product loop (lines 704-705)

- **Symptom**: `text_score = 1.0` and `overall_text_ok = True` are reassigned at
  the START of each product iteration inside
  `for prod_idx, prod_cfg in enumerate(products_cfg):`. Every iteration
  overwrites the shelf-level accumulators, so the final values reflect ONLY
  the last product's text check.
- **Fix**:
  - Remove the reset at lines 704-705. The shelf-level init at lines 629-630
    (`text_score = 1.0`, `overall_text_ok = True`) is already correct and must
    remain the single source of initialization.
  - Accumulate `text_results` across all products in the shelf.
  - Compute `text_score` ONCE after the product loop closes:
    ```python
    # After the for-prod_cfg loop:
    if text_results:
        text_score = (
            sum(r.confidence for r in text_results if r.found)
            / len(text_results)
        )
    ```
  - `overall_text_ok` may only flip to `False` (never back to `True`) across
    iterations. Current logic using `overall_text_ok = overall_text_ok and ...`
    is acceptable if the reset is removed.

### Bug 2 — `found_names[-1]` coupling is fragile (line 694)

- **Symptom**: The illumination-mismatch block at line 692-695 assumes
  `found_names[-1] == prod_name` to locate the entry it just appended. This
  breaks silently if loop structure or multi-product shelves are introduced.
- **Fix**: capture the insertion index at append time.
  Replace:
  ```python
  if zone_found:
      found_names.append(prod_name)
  ```
  with:
  ```python
  _found_idx: Optional[int] = None
  if zone_found:
      _found_idx = len(found_names)
      found_names.append(prod_name)
  ```
  Then at the illumination mismatch block (currently lines 692-695), replace
  the `found_names[-1] == prod_name` guard with:
  ```python
  if _found_idx is not None:
      found_names[_found_idx] = actual_label
  ```
  Remove the old `found_names[-1] == prod_name` check entirely — index
  tracking supersedes it.

**NOT in scope**:
- Any changes to `ProductOnShelves`.
- Any changes to `plan.py`.
- New tests beyond one regression test per bug (see below).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` | MODIFY | Remove lines 704-705 reset; compute text_score once after loop; switch to insertion-index-capture for found_names |

---

## Codebase Contract (Anti-Hallucination)

### Verified References

```python
# endcap_no_shelves_promotional.py — line numbers as of 2026-04-12 on dev
#
#   line 560: async def check_planogram_compliance(...)
#   line 620: for zone_idx, zone in enumerate(shelves):
#   line 629-630: text_score = 1.0; overall_text_ok = True  ← shelf-level init (KEEP)
#   line 640: text_results: List[...] = []
#   line 694: if found_names and found_names[-1] == prod_name:   ← Bug 2 anchor
#   line 700: for prod_idx, prod_cfg in enumerate(products_cfg):
#   line 704-705: text_score = 1.0; overall_text_ok = True       ← Bug 1 REMOVE
#   line 720-730: append to text_results inside the product loop
#
# The outer loop is zone/shelf; the inner loop is products inside the shelf.
# The Bug 1 reset clobbers the shelf-level init on every product iteration.
```

### Does NOT Exist

- ~~A separate Pydantic field for `found_names`~~ — `found_names` is a local `List[str]` built inside the method.
- ~~`text_results` as a class attribute~~ — it is a local variable reset per shelf.
- ~~`_found_idx` as a class attribute~~ — it is a new local variable introduced by this task.

---

## Implementation Notes

### Minimal diff shape for Bug 1

```python
# BEFORE (around line 700-705):
for prod_idx, prod_cfg in enumerate(products_cfg):
    text_score = 1.0          # ← REMOVE
    overall_text_ok = True    # ← REMOVE
    ...
    # existing product-level processing
    text_results.append(...)  # keep

# AFTER product loop ends (add):
if text_results:
    text_score = sum(r.confidence for r in text_results if r.found) / len(text_results)
# overall_text_ok is already maintained by ANDing across iterations
```

### Minimal diff shape for Bug 2

```python
# At the append site (inside the product loop):
_found_idx: Optional[int] = None
if zone_found:
    _found_idx = len(found_names)
    found_names.append(prod_name)

# At the illumination mismatch block (replace lines 692-695):
# OLD:
#   if found_names and found_names[-1] == prod_name:
#       found_names[-1] = actual_label
# NEW:
if _found_idx is not None:
    found_names[_found_idx] = actual_label
```

### Key Constraints

- Do NOT alter any existing test snapshots for endcap that rely on single-product
  shelves — the behaviour in those cases must be byte-identical.
- Do NOT change the method signature or return type.
- Use `Optional[int]` for `_found_idx` (import from `typing` if not already present).
- Keep `self.logger.info(...)` statements intact.

### Regression tests (add to existing endcap test file)

Add two tests in
`packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py`:

1. `test_multi_product_shelf_text_score_accumulates`
   Shelf with 2 products, both with `text_requirements`. Product A fails text
   (confidence 0.2), product B passes (confidence 0.9). Expected `text_score`
   ≈ 0.55 (or whatever the averaging formula produces), NOT 0.9 (the last-iter
   value under the bug).

2. `test_multi_product_shelf_illumination_label_on_correct_product`
   Shelf with 2 products where only product B has `illumination_required` and
   detected state mismatches. Assert that the label update lands on product B
   (by index), not on the most recently appended `found_names` entry.

---

## Acceptance Criteria

- [ ] Lines 704-705 reset removed; shelf-level init at lines 629-630 is the sole initialization
- [ ] `text_score` computed once after the product loop from accumulated `text_results`
- [ ] `overall_text_ok` never transitions from `False` back to `True`
- [ ] `found_names.append(prod_name)` captures `_found_idx` at append time
- [ ] Illumination mismatch uses `found_names[_found_idx] = actual_label` (no `[-1]` guard)
- [ ] Single-product shelf behaviour unchanged (existing tests still pass)
- [ ] Two new multi-product regression tests pass
- [ ] `pytest packages/ai-parrot-pipelines/tests/ -v` passes

---

## Agent Instructions

1. Verify TASK-629 is in `tasks/completed/` before starting (this task edits the
   same method after Module 2's refactor — order matters).
2. Read `endcap_no_shelves_promotional.py` lines 620-740 carefully before editing.
3. Apply Bug 1 and Bug 2 fixes independently — test after each if possible.
4. Add the two regression tests to the endcap test file.
5. Run the full test suite.
6. Move this file to `tasks/completed/` and update index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
