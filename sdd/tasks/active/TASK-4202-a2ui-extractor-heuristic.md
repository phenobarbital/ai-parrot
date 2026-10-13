# TASK-4202: `A2UIExtractor` heuristic mode — `HEURISTIC_PRIMITIVE_MAP`, checks → constraints, Cards/Tabs/Text rules

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4201
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 + §7 "Heuristic primitive map" (G6, AC10; resolved §8:
`Text`-before-input becomes the label). Any Basic-catalog `createSurface`
without `parrot_*` extensions is mapped to a `FormSchema` lossily, with every
loss reported. This task fills the `_heuristic_field` hook TASK-4201 left and
adds the structural rules (Card → section, nested Column/Row with a leading
Text → subsection, Tabs → one section per TabItem, unsupported → dropped).

---

## Scope

- `HEURISTIC_PRIMITIVE_MAP` and `CHECK_FUNCTION_TO_CONSTRAINT` constants.
- `_heuristic_field`: primitive → `FieldType` (variant/flags aware), `field_id` from the `value` binding path (`field_id_from_pointer_token`) else the component id (strip `f-`), collisions → `_2`, `_3` + warning, checks → constraints/required/EMAIL, `Slider` min/max/step, `ChoicePicker` options, `DateTimeInput` min/max → warning.
- Structural rules in the heuristic walk dispatch: `Card` → section (title = first `Text` child), `Column`/`Row` inside a Card with a leading `Text` → subsection, `Tabs`/`TabItem` → sections + `tabs_flattened`, `Text` immediately preceding an unlabeled input → its `label` + `label_inferred_from_text:<id>`, submit/cancel Buttons → `cancel_allowed`, `Image`/`Video`/`AudioPlayer`/`Icon`/`Divider`/`List`/`Modal`/non-Basic → `dropped`.
- Tests `tests/unit/extractors/test_a2ui_extractor_heuristic.py` with hand-written surfaces.

**NOT in scope**: strict mode (TASK-4201), import endpoint (TASK-4203).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py` | MODIFY | heuristic mapping + structural rules |
| `packages/parrot-formdesigner/tests/unit/extractors/test_a2ui_extractor_heuristic.py` | CREATE | heuristic tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# all already imported by TASK-4201 in extractors/a2ui.py: FormField, FormSection, FormSubsection, FieldConstraints, FieldOption, FieldType
from parrot_formdesigner.renderers.a2ui import field_id_from_pointer_token   # renderers/a2ui.py:92 (lazy import inside the method)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py (TASK-4201)
class A2UIExtractor:
    def _heuristic_field(self, comp, props: dict[str, Any], data_model: dict[str, Any], warnings: list[str], dropped: list[DroppedComponent]) -> FormField | None   # the hook to REPLACE
    def _walk(...) -> Iterator[tuple[component, ancestors: list[str]]]
    # extract() dispatch loop has a `# FILL IN: dispatch` for the heuristic structural rules
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/inputs.py — Basic input props (in comp.model_extra):
#   TextField: label, value, placeholder, variant ("shortText"|"longText"|"number"|"obscured")   (66-79)
#   CheckBox: label, value (81-88) · ChoicePicker: label, variant ("multipleSelection"), options [{label,value}], value (100-117)
#   Slider: label, min=0, max, value, steps (120-133) · DateTimeInput: value, enableDate, enableTime, min, max, label (136-150)
#   Button: child (Text id), action.event.name ("form.submit" | "form.cancel" in FEAT-544 surfaces) (46-63)
# basic/layout.py __all__: Card, Column, Divider, List, Modal, Row, TabItem, Tabs (21) · basic/media.py: AudioPlayer, Icon, IconSvgPath, Image, Text, Video (21)
# basic/functions.py check function names: required, regex, length, numeric, email (85-89)
# packages/ai-parrot/src/parrot/outputs/a2ui/models.py
class CheckRule(BaseModel): condition: FunctionCall | DataBinding; message: str | None   # 272-288
class FunctionCall(BaseModel): ...   # 174 — carries the function name + args (verify attribute names: `call`/`args` at task time)
# packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py — FieldConstraints: min_length, max_length, min_value, max_value, step, pattern, ... (44-56)
```

### Does NOT Exist
- ~~a `Form` component to detect~~ — forbidden by the dialect spec; forms are compositions.
- ~~mapping for `Image`/`Video`/`AudioPlayer`/`Icon`/`Divider`/`List`/`Modal`~~ — always `dropped(unsupported_component)`.
- ~~`DateTimeInput.min/max` → constraints~~ — not expressible on DATE/TIME/DATETIME fields; warning `datetime_bounds_dropped:<id>`.
- ~~raising on unsupported content~~ — heuristic mode never raises on content (AC10); only structural defects raise (TASK-4201).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/extractors/test_a2ui_extractor_heuristic.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py#field_id_from_pointer_token",
    "sym:packages/ai-parrot/src/parrot/outputs/a2ui/models.py#CheckRule",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/constraints.py#FieldConstraints"
  ]
}
```

---

## Implementation Notes

### Heuristic primitive map (spec §7 — normative)
| key | FieldType |
|---|---|
| `TextField` / `TextField:shortText` | TEXT |
| `TextField:longText` | TEXT_AREA |
| `TextField:number` | NUMBER |
| `TextField:obscured` | PASSWORD |
| `CheckBox` | BOOLEAN |
| `ChoicePicker` | SELECT |
| `ChoicePicker:multipleSelection` | MULTI_SELECT |
| `Slider` | NUMBER (+ min/max/step constraints) |
| `DateTimeInput:date` / `:time` / `:datetime` | DATE / TIME / DATETIME (by `enableDate`/`enableTime`) |

`checks`: `required` → `required=True`; `regex` → `pattern`; `length` → `min_length/max_length`; `numeric` → `min_value/max_value`; `email` on a TextField → `field_type = EMAIL`.

### Key Constraints
- Deterministic ids: `value` binding path last token (`field_id_from_pointer_token`) else `comp.id` without a leading `f-`; collision → suffix `_2`, `_3`, … + `field_id_collision:<id>`.
- A `Text` is "immediately preceding" when it is the previous sibling in the same parent's `children` list and the next sibling is an input without `label`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the two constants above the class — *why*: the table is normative and testable as data.
2. Replace `_heuristic_field` — *why*: the hook exists for exactly this.
3. Extend the `extract()` dispatch for heuristic structure (Card/Column/Row/Tabs/Text/Button) — *why*: sections and labels come from layout in heuristic mode.
4. Tests on hand-written surfaces (no renderer needed beyond `validate_envelope`).

### `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py` (MODIFY — constants)
```python
# occurrences: 1 (verified at task time: grep -c '^class A2UIExtractor:' packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py — created by TASK-4201)
# BEFORE — insert ABOVE `class A2UIExtractor:`
#: Basic primitive (+ variant / flag qualifier) → FieldType (spec §7, normative).
HEURISTIC_PRIMITIVE_MAP: dict[str, FieldType] = {
    "TextField": FieldType.TEXT, "TextField:shortText": FieldType.TEXT, "TextField:longText": FieldType.TEXT_AREA,
    "TextField:number": FieldType.NUMBER, "TextField:obscured": FieldType.PASSWORD, "CheckBox": FieldType.BOOLEAN,
    "ChoicePicker": FieldType.SELECT, "ChoicePicker:multipleSelection": FieldType.MULTI_SELECT, "Slider": FieldType.NUMBER,
    "DateTimeInput:date": FieldType.DATE, "DateTimeInput:time": FieldType.TIME, "DateTimeInput:datetime": FieldType.DATETIME,
}
#: Basic check function → how it lands on the FormField.
CHECK_FUNCTION_TO_CONSTRAINT: dict[str, str] = {"required": "required", "regex": "pattern", "length": "min_length/max_length",
                                               "numeric": "min_value/max_value", "email": "field_type=EMAIL"}
_UNSUPPORTED = {"Image", "Video", "AudioPlayer", "Icon", "Divider", "List", "Modal"}
_INPUTS = {"TextField", "CheckBox", "ChoicePicker", "Slider", "DateTimeInput"}


def _primitive_key(comp: Any, props: dict[str, Any]) -> str:
    """``"TextField:longText"``-style key for HEURISTIC_PRIMITIVE_MAP."""
    if comp.component == "DateTimeInput":
        date, time = bool(props.get("enableDate")), bool(props.get("enableTime"))
        return "DateTimeInput:" + ("datetime" if date and time else "time" if time else "date")
    variant = props.get("variant")
    return f"{comp.component}:{variant}" if variant else comp.component
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py` (MODIFY — `_heuristic_field`)
```python
# occurrences: 1 (verified at task time: grep -c 'reason="heuristic_not_implemented"' packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py)
# REPLACE the whole TASK-4201 `_heuristic_field` body with:
        if comp.component in _UNSUPPORTED or comp.component not in _INPUTS:
            reason = "unsupported_component" if comp.component in _UNSUPPORTED or comp.component in {"Text", "Button", "Card", "Column", "Row", "Tabs", "TabItem"} else "not_in_basic_catalog"
            dropped.append(DroppedComponent(component_id=comp.id, component=comp.component, reason=reason))
            return None
        from ..renderers.a2ui import field_id_from_pointer_token  # lazy

        key = _primitive_key(comp, props)
        field_type = HEURISTIC_PRIMITIVE_MAP.get(key, HEURISTIC_PRIMITIVE_MAP.get(comp.component, FieldType.TEXT))
        binding = props.get("value")
        if isinstance(binding, dict) and isinstance(binding.get("path"), str) and binding["path"].startswith("/answers/"):
            field_id = field_id_from_pointer_token(binding["path"].rsplit("/", 1)[-1])
            default = (data_model.get("answers") or {}).get(field_id)
        else:
            field_id, default = comp.id.removeprefix("f-"), (binding if not isinstance(binding, dict) else None)
            warnings.append(f"no_binding:{comp.id}")
        field_id = self._unique_field_id(field_id, warnings)
        required, constraints = False, FieldConstraints()
        for rule in comp.checks or []:
            # FILL IN: read the FunctionCall name/args (verify FunctionCall attribute names in models.py:174-210) and apply
            #          CHECK_FUNCTION_TO_CONSTRAINT: required→required=True; regex→constraints.pattern; length→min/max_length;
            #          numeric→min/max_value; email (TextField only)→field_type = FieldType.EMAIL — bounded by §7
            pass
        if comp.component == "Slider":
            constraints.min_value, constraints.max_value = float(props.get("min", 0)), float(props["max"]) if "max" in props else None
            # FILL IN: constraints.step = (max-min)/steps when props.get("steps") — bounded by §7 table row Slider
        if comp.component == "DateTimeInput" and (props.get("min") or props.get("max")):
            warnings.append(f"datetime_bounds_dropped:{comp.id}")
        options = [FieldOption(value=str(o.get("value")), label=o.get("label") or str(o.get("value"))) for o in props.get("options") or [] if isinstance(o, dict)] or None
        has_constraints = any(v is not None for v in constraints.model_dump().values())
        return FormField(field_id=field_id, field_type=field_type, label=props.get("label") or field_id.replace("_", " ").title(),
                         required=required, placeholder=props.get("placeholder") if comp.component == "TextField" else None,
                         options=options, constraints=constraints if has_constraints else None, default=default)

    def _unique_field_id(self, field_id: str, warnings: list[str]) -> str:
        """Suffix collisions deterministically (``_2``, ``_3`` …) and warn."""
        seen = self._seen_field_ids  # FILL IN: initialise `self._seen_field_ids: set[str] = set()` at the start of extract() — bounded by AC10
        if field_id not in seen:
            seen.add(field_id)
            return field_id
        n = 2
        while f"{field_id}_{n}" in seen:
            n += 1
        warnings.append(f"field_id_collision:{field_id}")
        seen.add(f"{field_id}_{n}")
        return f"{field_id}_{n}"
```

### `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py` (MODIFY — heuristic structure in `extract()` dispatch)
```python
# In the `# FILL IN: dispatch` block of extract() (TASK-4201), add the HEURISTIC branch rules — bounded by §7 table:
#   Card            → new section: section_id = comp.id (strip "sec-" if present); title = text of its first Text descendant
#                     (the Text id is then marked "consumed" so it is not reused as a label)
#   Column/Row inside a Card whose first child is a Text → FormSubsection(subsection_id=comp.id, title=that Text); other
#                     Columns/Rows are transparent containers
#   Tabs/TabItem    → one section per TabItem (section_id = TabItem id, title = its first Text) + warnings.append("tabs_flattened")
#   Text            → if the NEXT sibling (same parent children list) is an input in _INPUTS without props["label"] →
#                     remember it as that input's label and warnings.append(f"label_inferred_from_text:{next_id}");
#                     otherwise dropped(unsupported_component)   # resolved §8
#   Button          → action.event.name == "form.cancel" → cancel_allowed=True; "form.submit" → nothing; other Buttons → dropped
#   inputs          → self._field_from_component(...) placed under the current (section, subsection) from `ancestors`
#   no Card at all  → every field goes to FormSection(self.default_section_id)
```
**Why this shape**: the table and the resolved-§8 label rule are transcribed literally; everything unmapped lands in `dropped` with a reason so AC10's "every loss reported" holds; `field_id_from_pointer_token` keeps id derivation identical to the renderer's escaping.

### `packages/parrot-formdesigner/tests/unit/extractors/test_a2ui_extractor_heuristic.py` (CREATE)
```python
"""A2UIExtractor heuristic mode — FEAT-650 TASK-4202."""

from __future__ import annotations

import pytest

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.core.types import FieldType  # noqa: E402
from parrot_formdesigner.extractors import A2UIExtractor, ExtractionMode  # noqa: E402


def _c(id_, component, **props):
    return {"id": id_, "component": component, **props}


def _surface(components, data_model=None):
    return {"version": "v1.0", "createSurface": {"surfaceId": "s", "sendDataModel": True,
            "components": components, "dataModel": data_model or {"answers": {}}}}


GENERIC = _surface([
    _c("root", "Column", children=["card1", "img", "actions"]),
    _c("card1", "Card", child="body1"),
    _c("body1", "Column", children=["t1", "name", "lbl_age", "age", "tags", "when"]),
    _c("t1", "Text", text="Personal"),
    _c("name", "TextField", label="Name", value={"path": "/answers/name"}, checks=[{"condition": {"call": "required", "args": {"value": {"path": "/answers/name"}}}}]),
    _c("lbl_age", "Text", text="Age"),
    _c("age", "Slider", min=0, max=120, value={"path": "/answers/age"}),
    _c("tags", "ChoicePicker", label="Tags", variant="multipleSelection", options=[{"label": "A", "value": "a"}], value={"path": "/answers/tags"}),
    _c("when", "DateTimeInput", enableDate=True, enableTime=True, value={"path": "/answers/when"}),
    _c("img", "Image", url="x.png"),
    _c("actions", "Row", children=["cancel"]),
    _c("cancel", "Button", child="cancel_t", action={"event": {"name": "form.cancel"}}),
    _c("cancel_t", "Text", text="Cancel"),
], {"answers": {"name": "Ana"}})


def test_generic_surface_maps_fields_sections_and_drops():
    out = A2UIExtractor().extract(GENERIC)
    assert out.mode is ExtractionMode.HEURISTIC
    sec = out.form.sections[0]
    assert sec.section_id == "card1"
    back = {f.field_id: f for f in out.form.iter_fields_recursive()}
    assert back["name"].field_type is FieldType.TEXT and back["name"].required and back["name"].default == "Ana"
    assert back["age"].field_type is FieldType.NUMBER and back["age"].constraints.max_value == 120
    assert back["tags"].field_type is FieldType.MULTI_SELECT and back["tags"].options[0].value == "a"
    assert back["when"].field_type is FieldType.DATETIME
    assert out.form.cancel_allowed is True
    assert {d.component_id for d in out.dropped} >= {"img"}
    # FILL IN: assert str(back["age"].label) mentions "Age" and "label_inferred_from_text:age" in out.warnings — bounded by resolved §8


def test_tabs_flatten_to_sections_and_collisions_suffix():
    # FILL IN: Tabs with two TabItems each holding a TextField bound to "/answers/x" → sections == TabItem ids,
    #          field ids ["x", "x_2"], warnings include "tabs_flattened" and "field_id_collision:x" — bounded by §7/AC10


def test_text_variants_and_checks():
    # FILL IN: TextField variants longText/number/obscured → TEXT_AREA/NUMBER/PASSWORD; checks regex/length/numeric → constraints;
    #          email check → EMAIL — bounded by HEURISTIC_PRIMITIVE_MAP / CHECK_FUNCTION_TO_CONSTRAINT


def test_never_raises_on_content():
    out = A2UIExtractor().extract(_surface([_c("root", "Column", children=["v"]), _c("v", "Video", url="v.mp4")]))
    assert out.form.sections and not list(out.form.iter_all_fields()) and out.dropped[0].reason == "unsupported_component"
```
**Why this shape**: one generic surface exercises every row of the §7 table at once; the Tabs/collision/variants tests pin the remaining rules; the last test is AC10's "never raises on content".

### FILL IN checklist
- [ ] `a2ui.py::_heuristic_field` — checks loop (verify `FunctionCall` attribute names), Slider step; bounded by §7.
- [ ] `a2ui.py::extract` — heuristic structural dispatch (Card/Column/Row/Tabs/Text/Button); bounded by §7 + resolved §8.
- [ ] `a2ui.py::extract` — `self._seen_field_ids` reset per call; bounded by AC10.
- [ ] tests `FILL IN` bodies; bounded by AC10.

---

## Acceptance Criteria

- [ ] Every §7 heuristic table row and the resolved-§8 label rule are implemented and tested; unsupported/unreachable components appear in `dropped` with reasons; collisions suffixed + warned (AC10).
- [ ] Heuristic extraction never raises on content; structural defects still raise (TASK-4201 behaviour preserved).
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/extractors/test_a2ui_extractor_heuristic.py -v` and the strict suite; `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/extractors/test_a2ui_extractor_heuristic.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/extractors/test_a2ui_extractor_strict.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §7 "Heuristic primitive map" and §8 resolved items
3. **Check dependencies** — TASK-4201 `"done"`
4. **Verify the Codebase Contract** — `grep -n 'class FunctionCall' -A20 packages/ai-parrot/src/parrot/outputs/a2ui/models.py`; `grep -n 'heuristic_not_implemented' packages/parrot-formdesigner/src/parrot_formdesigner/extractors/a2ui.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the two files
9. **Close** with `scripts/sdd/close_task.sh TASK-4202 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
