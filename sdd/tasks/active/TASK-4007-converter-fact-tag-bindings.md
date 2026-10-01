# TASK-4007: Convert legacy fact/price tag elements into fact_tag_present bindings

**Feature**: FEAT-624 — Planogram `fact_tag_present` rule
**Spec**: `sdd/specs/planogram-fact-tag-rule.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4003
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. Since PR #1547 the converter skips every `fact_tag` / `price_tag` element of a
legacy row and warns once per shelf. With the new kind it can bind each tag to the facing of the
product it labels. A tag that matches no product of its shelf becomes an unresolved item — never
a silent drop.

---

## Scope

- In `_walk_shelves`, collect `fact_tag` / `price_tag` elements instead of counting them; after
  the shelf's products are walked, bind each to the first facing of the matching product with
  `bindings.add("fact_tag_present", facing_id, {"price_required": ..., "name": name}, mandatory=False)`.
- Add `_tag_product_name(name)`.
- An unmatched tag appends the unresolved item worded exactly as below.
- Remove the "fact/price tag element(s) not converted" warning. Elements of type `slot` stay
  skipped without any message.
- Update the existing converter tests that encode the old behaviour (listed below) and add the new ones.

**NOT in scope**: `_convert_counter` (product_counter treats a `fact_tag` element as a product —
unchanged), `_convert_zones_only`, `_convert_ink`; matching on aliases (spec §8 open question).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py` | MODIFY | tag elements → bindings |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py` | MODIFY | fixture rename, updated and new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# test file already imports (test_config_migration.py:10-21): load_slots_definition, validate_bindings,
#   convert_config, check_row, ConversionReport, _main, MIGRATED_TYPES, ... — reuse them
from parrot_pipelines.planogram.migration import check_row, convert_config  # verified: migration.py (check_row, convert_config)
```

### Existing Signatures to Use
```python
# migration.py
_NON_FACING_TYPES = frozenset({"fact_tag", "price_tag", "slot"})   # line 38
class _BindingSet:
    def add(self, kind: str, target_id: str, params: Dict[str, Any], mandatory: bool = True) -> None:
        # rule_id = f"{kind}:{target_id}"; a second add with the same rule_id keeps the first entry
def _walk_shelves(config, report: ConversionReport, bindings: _BindingSet) -> Tuple[list, list]:  # line 218
    # per shelf: shelf_id = f"shelf-{index}", level, facings: List[Dict] (facing_id, product, ...),
    #   skipped = 0 (line 229), loop `for product in shelf.get("products") or []:`,
    #   line 235: `if ptype in _NON_FACING_TYPES:` / `skipped += 1` / `continue`
    #   line 280: `if skipped:` -> report.warnings.append("... fact/price tag element(s) not converted — ...")
def _shelf_top(shelf: Dict[str, Any]) -> Optional[float]:  # line 297
```

```python
# tests/planogram_cycle/test_config_migration.py
# legacy_config fixture (line 25): middle shelf products ES-400 [2,2], RR-60 [1,3], {"name": "Tag", "product_type": "fact_tag"} (line 57)
def test_fact_tags_are_not_facings(legacy_config):           # line 198 — asserts "Tag" not in products
def test_cli_convert_exit_zero_when_fully_resolved(...):     # line 289 — expects exit 0 after fixing RR-60 quantity
def test_skipped_fact_tags_are_warned(legacy_config):        # line 513 — asserts the warning this task removes
```

### Does NOT Exist
- ~~`FacingDefinition.fact_tag`~~ — expectation lives only in the binding.
- ~~alias matching~~ — exact name match after suffix removal only (spec §7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#_walk_shelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#_BindingSet",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#convert_config",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/migration.py#check_row"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Matching happens AFTER the product loop, so a tag listed before its product still binds.
- Compare names with `casefold()` on both sides; product names come from the `facings` already
  built for this shelf (`facing["product"]`), first facing wins.
- `_tag_product_name` removes a trailing `fact tag` or `price tag` (case-insensitive) and strips
  whitespace: `"ES-60W Fact Tag" -> "ES-60W"`, `"Tag" -> ""` (empty → unmatched).
- The rename of the fixture's tag from `"Tag"` to `"RR-60 Fact Tag"` (with `price_required: true`)
  keeps `test_cli_convert_exit_zero_when_fully_resolved` at exit 0.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_tag_product_name` next to `_shelf_top` — *why*: one tested place for the naming rule.
2. Replace the skip at line 235 with collection of tag elements — *why*: they are needed after the loop.
3. Bind or report each tag after the loop; drop the old warning — *why*: spec §5 AC on the converter.
4. Update the fixture and the three tests, add the new ones.

### `migration.py` (MODIFY — helper)
```python
# occurrences: 1 (verified: grep -c '^def _shelf_top' migration.py)
# BEFORE — insert above `def _shelf_top(shelf: Dict[str, Any]) -> Optional[float]:` (verified: migration.py:297)
_TAG_SUFFIX = re.compile(r"\s*(fact|price)\s+tag\s*$", re.IGNORECASE)


def _tag_product_name(name: str) -> str:
    """Tag element name with a trailing ``fact tag`` / ``price tag`` removed (case-insensitive), stripped."""
    return _TAG_SUFFIX.sub("", name).strip()
```
Add `import re` to the module imports (it is not imported today — verify with `grep -n '^import re' migration.py`).

### `migration.py` (MODIFY — collect)
```python
# occurrences: 1 (verified: grep -c '            if ptype in _NON_FACING_TYPES:' migration.py)
# REPLACE lines 235-237 (verified: migration.py:235)
            if ptype in _NON_FACING_TYPES:
                if ptype != "slot":
                    tags.append(product)
                continue
# and replace `        skipped = 0` (line 229) with `        tags: List[Dict[str, Any]] = []`
```

### `migration.py` (MODIFY — bind)
```python
# occurrences: 1 (verified: grep -c '        if skipped:' migration.py)
# REPLACE the 5-line `if skipped:` block (verified: migration.py:280-284) with:
        first_facing_of = {}
        for facing in facings:
            first_facing_of.setdefault(str(facing["product"]).casefold(), facing["facing_id"])
        for tag in tags:
            tag_name = str(tag.get("name") or "").strip()
            facing_id = first_facing_of.get(_tag_product_name(tag_name).casefold())
            if facing_id is None:
                report.unresolved.append(
                    f"{shelf_id} ({level}): tag '{tag_name}' matches no product of the shelf — bind it to a facing or drop it"
                )
                continue
            # FILL IN: bindings.add("fact_tag_present", facing_id,
            #          {"price_required": bool(tag.get("price_required")), "name": tag_name}, mandatory=False)
            #          — bounded by spec §3 M5 (rule id shape fact_tag_present:<facing_id>, mandatory False)
```

### `tests/planogram_cycle/test_config_migration.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '{"name": "Tag", "product_type": "fact_tag"},' test_config_migration.py)
# REPLACE line 57:
                    {"name": "RR-60 Fact Tag", "product_type": "fact_tag", "price_required": True},
# update the fixture docstring (line 27) "one fact_tag" -> "one fact_tag labelling RR-60"

# line 198 test_fact_tags_are_not_facings: assert "RR-60 Fact Tag" not in products

# REPLACE test_skipped_fact_tags_are_warned (line 513) with:
def test_tag_elements_become_bindings(legacy_config):
    report = _convert(legacy_config)
    binding = next(b for b in report.bindings if b["kind"] == "fact_tag_present")
    assert binding == {
        "rule_id": "fact_tag_present:shelf-2:3",
        "kind": "fact_tag_present",
        "target_id": "shelf-2:3",
        "params": {"price_required": True, "name": "RR-60 Fact Tag"},
        "mandatory": False,
    }
    assert not any("fact/price tag" in item for item in report.warnings)


def test_tag_listed_before_its_product_still_binds(legacy_config):
    products = legacy_config["shelves"][1]["products"]
    products.insert(0, products.pop())  # tag first
    # FILL IN: assert a fact_tag_present binding targets the first RR-60 facing — bounded by "match after the loop"


def test_unmatched_tag_is_unresolved(legacy_config):
    legacy_config["shelves"][1]["products"][2]["name"] = "Tag"
    report = _convert(legacy_config)
    assert any("tag 'Tag' matches no product" in item for item in report.unresolved)


def test_converted_candidate_with_tags_validates(legacy_config):
    legacy_config["shelves"][1]["products"][1]["quantity_range"] = [1, 1]
    report = _convert(legacy_config)
    # FILL IN: assert check_row({"config_name": "x", "planogram_type": "product_on_shelves",
    #          "slots_definition": report.candidate, "planogram_config": {**legacy_config,
    #          "rule_bindings": report.bindings, "layout_profile": report.layout_profile}}).ok
    #          — requires TASK-4003's validation to accept the kind
```

### FILL IN checklist
- [ ] `_walk_shelves` — the `bindings.add(...)` call.
- [ ] `test_tag_listed_before_its_product_still_binds` and `test_converted_candidate_with_tags_validates` bodies.
- [ ] Check the slot numbering of the expected `target_id` (`shelf-2:3` = ES-400 ×2 then RR-60); adjust only if the existing fixture assertions at line 158 say otherwise.

---

## Acceptance Criteria

- [ ] Each legacy `fact_tag` / `price_tag` matching a product of its shelf yields one
      `fact_tag_present` binding with `price_required` carried and `mandatory: false`.
- [ ] An unmatched tag yields the unresolved item; nothing is dropped silently.
- [ ] The "fact/price tag element(s) not converted" warning is gone; `slot` elements stay silent.
- [ ] All tests in `test_config_migration.py` pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_config_migration.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_migration_runner.py -q`

---

## Test Specification

See the MODIFY block for the test file: binding shape, list-order independence, unmatched tag,
and that the converted candidate passes `check_row`.

---

## Agent Instructions

1. Work in the feature worktree; run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src`.
2. Confirm TASK-4003 is `done`; verify the Codebase Contract; mark `in-progress`; implement; validate.
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4007 planogram-fact-tag-rule verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
