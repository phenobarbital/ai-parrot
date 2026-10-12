# TASK-4208: Document the reporting policy and `products_found`

**Feature**: FEAT-648 — `products_found` for every product-detecting planogram type
**Spec**: `sdd/specs/products-found-endcap.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 / G6. `docs/pipelines/planogram-compliance-cycle.md` is the only
planogram doc and says nothing about `ReportingPolicy`, `slot_presence` or
`products_found` (proposal finding F012). FEAT-645's spec still lists
`test_non_ink_wall_result_unchanged` as a contract that FEAT-648 reverses.

The content is fixed by the spec, so this task has no edge to the code tasks and
runs concurrently with them.

---

## Scope

- Add a `Reporting` row to the "Layout profiles" field-group table.
- Add a new `## Reporting policy and \`products_found\`` section before `## OCR and references`.
- Add `products_found` to the additive-keys sentence under `## Result keys`.
- Annotate the FEAT-645 spec test-matrix row 329 with the supersession note.

**NOT in scope**: any code or test; other docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/pipelines/planogram-compliance-cycle.md` | MODIFY | new row, new section, result key |
| `sdd/specs/planogram-ink-wall-slot-presence.spec.md` | MODIFY | supersession note on row 329 |

---

## Codebase Contract (Anti-Hallucination)

### Facts the docs must state (verified)
```python
# comparison/definition.py:49-57
class ReportingPolicy(BaseModel):  # extra="forbid"
    product_label: Literal["display_name", "product"] = "display_name"
    slot_presence: bool = False
    misplaced_min_confidence: float = 0.9
# effective_reporting (definition.py:196-225): ReportingPolicy() → layout.reporting (type profile merged with
#   planogram_config["layout_profile"] by resolve_layout_profile, layout.py:154) → slots_definition.meta["reporting"] (partial, last)
# Per-type defaults after TASK-4206:
#   ink_wall: product_label="product", slot_presence=True        (types/ink_wall.py:80)
#   endcap_backlit_multitier, product_on_shelves, product_counter, graphic_panel_display: display_name / True
#   endcap_no_shelves_promotional: default (display_name / False); zone-only → [] anyway
# SlotPresence fields (contracts.py:231-249): shelf_id, shelf_level, slot, position, facing_ids, model, sku, brand,
#   display_name, found, misplaced, status, confidence, facings, facings_found, observed
# found (comparison/presence.py:8-39): True = MATCH / VARIANT_UNRESOLVED / INFERRED_PRESENT, or MISPLACED with
#   confidence >= misplaced_min_confidence (then misplaced=True); False = MISMATCH / EMPTY;
#   None = NOT_VISIBLE / NOT_ASSESSED / CONFLICT (unknown, never "absent"). A slot groups facings by
#   (shelf_id, position or slot); found=True if any facing is found; facings_found counts them.
# Result: result["products_found"] (plan.py:519); job JSON serialisable["products_found"] (handlers/planogram_compliance.py:191)
```

### Does NOT Exist
- ~~`planogram_config["reporting"]`~~ — the config path is `planogram_config["layout_profile"]["reporting"]`.
- ~~`SlotsDefinition.reporting`~~ — it is `slots_definition["meta"]["reporting"]`.
- ~~an existing "Reporting" section in the doc~~ — this task creates it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/pipelines/planogram-compliance-cycle.md", "action": "MODIFY"},
    {"path": "sdd/specs/planogram-ink-wall-slot-presence.spec.md", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Insert the table row — *why*: the field-group table is where readers look up profile keys.
2. Insert the new section — *why*: G6; the tri-state must be written down so consumers do not read `None` as absent (spec §7).
3. Extend the Result keys sentence — *why*: the key is additive and currently undocumented.
4. Annotate the FEAT-645 spec row.

### `docs/pipelines/planogram-compliance-cycle.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '| References |' — line 37) -->
<!-- AFTER — insert below the `| References | …` row (verified: :37) -->
| Reporting | `reporting.product_label` (`display_name` or `product`), `reporting.slot_presence`, `reporting.misplaced_min_confidence` |

<!-- occurrences: 1 (verified: grep -cF '## OCR and references' — line 52) -->
<!-- BEFORE — insert above `## OCR and references` (verified: :52), followed by one blank line -->
## Reporting policy and `products_found`

`ReportingPolicy` controls how products are labelled and whether slot presence is reported.
It resolves in this order, each step overriding the previous one: the policy defaults, the
type's layout profile, `planogram_config["layout_profile"]["reporting"]`, and finally
`slots_definition["meta"]["reporting"]`. Unknown keys are rejected.

| Type | `product_label` | `slot_presence` |
|---|---|---|
| `ink_wall` | `product` | on |
| `endcap_backlit_multitier`, `product_on_shelves`, `product_counter`, `graphic_panel_display` | `display_name` | on |
| `endcap_no_shelves_promotional` | `display_name` | off (zone-only definitions) |

<!-- FILL IN: one paragraph + bullet list describing a products_found entry (the SlotPresence fields
     listed in the Codebase Contract) and the tri-state `found` exactly as stated there — bounded by spec §7
     "Tri-state found": state explicitly that None means "not decided", never "not found". -->

<!-- FILL IN: two JSON snippets disabling presence — one under planogram_config.layout_profile.reporting,
     one under slots_definition.meta.reporting — bounded by the Does NOT Exist list. -->

<!-- occurrences: 1 (verified: grep -cF '## Result keys' — line 119) -->
<!-- MODIFY the sentence starting `Additive keys are` (:125): insert `products_found` after `position_results`,
     so it reads: "Additive keys are `detections`, `identifications`, `position_results`, `products_found`, `shelf_scores`, …" -->
```

### `sdd/specs/planogram-ink-wall-slot-presence.spec.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '| `test_non_ink_wall_result_unchanged` |' — line 329) -->
<!-- REPLACE the last cell of row 329 so the row reads: -->
| `test_non_ink_wall_result_unchanged` | an endcap / product_on_shelves fixture run: `products_found == []`, lists identical to before. **Superseded by FEAT-648** (`sdd/specs/products-found-endcap.spec.md`): shelf-based types now opt in; the test became `test_non_ink_wall_labels_unchanged_with_presence`. |
```

### FILL IN checklist
- [ ] Entry description + tri-state paragraph — bounded by the Codebase Contract facts and spec §7.
- [ ] Two opt-out snippets — bounded by Does NOT Exist.

---

## Acceptance Criteria

- [ ] The doc has the Reporting row, the new section (with the per-type table, entry shape, tri-state, opt-outs) and `products_found` under Result keys.
- [ ] The FEAT-645 spec row 329 carries the supersession note; nothing else in that spec changes.
- [ ] `git diff --stat` touches only the two files.

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_slot_presence.py -q`

(Docs-only task: this run only confirms the presence contract the doc describes still holds. Also check by eye: `grep -n "products_found" docs/pipelines/planogram-compliance-cycle.md` lists the section and the result key.)

---

## Agent Instructions

1. Work in the feature worktree; verify the anchors with `grep -cF`.
2. Mark `in-progress`, edit from the blueprint, complete every `FILL IN`.
3. Commit only the two files; close with `scripts/sdd/close_task.sh TASK-4208 products-found-endcap verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
