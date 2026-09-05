# TASK-2860: `KPICard`/`DataTable` presentation props, `Infographic` half-width `Row` lowering, adapter pass-through, golden regeneration

**Feature**: FEAT-527 — Infographic → A2UI migration (dual-emit)
**Spec**: `sdd/specs/infographic-a2ui-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2859
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 items 2-3 and 5. After TASK-2859 the chart lane is at parity; the remaining
dropped fields are hero-card `icon`/`color`/`comparison_period`, table `style`, bullet-list
`columns`, and the chart `layout` hint has no lowering effect yet. This task closes those and
regenerates the golden fixtures whose `lower()` output legitimately changes (spec §7 "Golden
fixtures").

---

## Scope

- `catalog/parrot/kpicard.py` — `KPICARD_SCHEMA` (`:17-22`) += `"icon": {"type":"string"}`,
  `"color": {"type":"string"}`, `"comparisonPeriod": {"type":"string"}`. `lower()` emits them as
  `metadata.extensions` (`parrot_icon`, `parrot_color`, `parrot_comparison_period`) on the
  existing nodes (`:63-94`) — never as new visible `Text` nodes.
- `catalog/parrot/datatable.py` — schema += `"style": {"type":"string", "enum": [...TableStyle values
  from models/infographic.py:138...]}`; `lower()` records `parrot_style` in the body extensions (`:93`).
- `catalog/parrot/infographic.py` — `_lower_section()` (`:120-141`): consecutive child descriptors
  whose `properties.layout == "half"` are wrapped pairwise in `BasicNode(component="Row", children=[...])`
  with `metadata.extensions.parrot_layout = "half"`; other children unchanged. Update
  `INFOGRAPHIC_INSTRUCTIONS` (`:65-71`) to mention `layout`.
- `adapters/infographic.py` — `_hero_card()` (`:293+`) forwards `icon`, `color`,
  `comparison_period → "comparisonPeriod"`; `_table()` (`:267+`) forwards `style`; the
  `bullet_list → List` mapping records `columns` as `metadata.extensions.parrot_columns` on the
  `List` descriptor (find the bullet-list converter in the same file). Omit `None`s. Update the
  docstring's "dropped" bullet (`:57-59`) to say nothing presentation-relevant is dropped now.
- Regenerate goldens `kpicard_lowered.json`, `datatable_lowered.json`, `infographic_lowered.json`
  (and `chart_lowered.json` only if changed) with the existing test harness; paste the semantic
  diff (added extensions / Row wrapping) into the completion note.
- Tests: `tests/outputs/a2ui/test_components_card_kpicard_timeline_form.py`,
  `test_components_chart_datatable_map.py`, `test_components_infographic_report.py`,
  `adapters/test_infographic_adapter.py`, `test_catalog_parity.py` (update expectations deliberately).

**NOT in scope**: chart type/props (TASK-2859); renderer visuals for the new extensions
(TASK-2861 covers chart types; KPICard icon/color rendering in backend renderers is a follow-up unless trivial);
frontend (TASK-2867).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py` | MODIFY | schema + extensions |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/datatable.py` | MODIFY | `style` prop + extension |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/infographic.py` | MODIFY | half-width `Row` grouping, instructions |
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py` | MODIFY | `_hero_card`, `_table`, bullet `columns` |
| `packages/ai-parrot/tests/outputs/a2ui/golden/{kpicard,datatable,infographic}_lowered.json` | MODIFY | regenerated |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_*.py`, `adapters/test_infographic_adapter.py`, `test_catalog_parity.py` | MODIFY | assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.outputs.a2ui.catalog import register_component, get_component        # catalog/__init__.py:107
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, TabSpec, CatalogValidationError  # catalog/base.py:97,141,299
from parrot.outputs.a2ui.catalog.parrot.kpicard import KPICARD_SCHEMA            # kpicard.py:17 (keys: delta,label,trend,unit,value)
from parrot.outputs.a2ui.catalog.parrot.infographic import InfographicComponent, INFOGRAPHIC_SCHEMA, INFOGRAPHIC_INSTRUCTIONS  # infographic.py:144,33,65
from parrot.outputs.a2ui.adapters import infographic_response_to_envelope         # adapters/__init__.py:12
from parrot.models.infographic import TableStyle, BulletListStyle, HeroCardBlock, TableBlock, BulletListBlock  # models/infographic.py:138,148,327,732,710
from parrot.outputs.a2ui.models import Component                                  # used by every catalog module
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py
KPICARD_SCHEMA["properties"] = {"label": str, "value": {...}, "unit": str, "delta": {...}, "trend": enum[up,down,flat]}  # :17-22
# lower(): label Text with extensions {"parrot_role": "label"} :63 ; value Text with {"parrot_role": "value", "parrot_unit": ...} :68 ; Card metadata {"parrot_variant": "kpi"} :94

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/datatable.py
schema required ("columns",) :30 ; columns = props.get("columns") or [] :50 ; body_extensions = {"parrot_role": "rows"} :93
# DataTable schema keys today: ['columns','data','explanation','totalRows','truncated']

# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/infographic.py
def _lower_child(descriptor, data_model, child_id) -> BasicNode                  # :74
def _lower_section(section, data_model, section_id) -> BasicNode                 # :120-141 → Column(children=[heading Text, text Text, *children])
@register_component("Infographic", allowed_parents=["root","Column"]) class InfographicComponent  # :144 ; lower() :151-181 ; >1 section → Tabs(TabSpec(title, child)) :171-178

# packages/ai-parrot/src/parrot/outputs/a2ui/adapters/infographic.py
def _table(self, block) -> dict   # :267
def _hero_card(self, block) -> dict  # :293  (→ "KPICard" descriptor)
# bullet_list → List{direction:'vertical'} of Text ; checklist → List of CheckBox  (module docstring :40-46 — locate the converter methods in-file)
def _descriptor(component: str, properties: dict) -> dict   # module helper used by every converter (:265)

# packages/ai-parrot/src/parrot/models/infographic.py
class TableStyle(str, Enum)      # :138  ; class BulletListStyle(str, Enum) # :148
class HeroCardBlock(BaseModel)   # :327  (label, value, icon, trend, trend_value, comparison_period, color — verify at :327-479)
class BulletListBlock(BaseModel) # :710  (items, style, columns — verify)
class TableBlock(BaseModel)      # :732  (columns, rows, style — verify)

# goldens harness
GOLDEN_DIR = Path(__file__).parent / "golden"   # tests/outputs/a2ui/test_components_card_kpicard_timeline_form.py:16 (test_kpicard_lowering_golden :90)
#                                                 tests/outputs/a2ui/test_components_chart_datatable_map.py:12 (test_datatable_lowering_golden :115)
#                                                 tests/outputs/a2ui/test_components_infographic_report.py (infographic golden)
```

### Does NOT Exist
- ~~`KPICard.icon` / `.color` / `.comparisonPeriod`~~ in today's schema — added here.
- ~~`DataTable.style`~~ — added here.
- ~~a `Grid` Basic Catalog primitive~~ — use `Row`/`Column` (the 18 primitives: Text, Image, Icon, Video, AudioPlayer, Row, Column, List, Card, Tabs, Modal, Divider, Button, TextField, CheckBox, ChoicePicker, Slider, DateTimeInput).
- ~~an automatic golden regeneration flag~~ — regenerate by running the lowering and writing the JSON explicitly (follow how the goldens were first produced in the test files; do not rubber-stamp).

---

## Implementation Notes

### Pattern to Follow
Presentation semantics live in `metadata.extensions` (see `docs/outputs/a2ui-v1.md` §"metadata.extensions"),
exactly like `parrot_role`/`parrot_unit`/`parrot_variant` today. Do not add visible nodes.

### Key Constraints
- Lowering stays pure/deterministic (no uuids/clocks); child ids follow the `f"{section_id}-c{ci}"` scheme (`:140`).
- `Row` children for `half` layout: group consecutive `half` descriptors in pairs; an odd trailing one stays in a single-child `Row`.
- Schemas are hand-written JSON for KPICard/DataTable (not derived) — editing them directly is correct here.
- FEAT-493's "no `lower()` changes" non-goal does not bind FEAT-527, but every golden diff must be explained.

### References in Codebase
- `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/infocard.py` — small composite with extensions.
- `docs/outputs/a2ui-v1.md` §"metadata.extensions — presentation semantics live outside the schema".

---

## Acceptance Criteria

- [ ] `KPICARD_SCHEMA` and DataTable schema accept the new props; envelopes using them pass `validate_envelope`
- [ ] Adapter forwards `icon`/`color`/`comparisonPeriod` (KPICard), `style` (DataTable), `parrot_columns` (List extension); `None`s omitted
- [ ] Two consecutive `layout:"half"` charts lower into one `Row` with `parrot_layout: "half"`; a `full` chart stays a direct Column child
- [ ] Goldens regenerated; completion note lists the semantic diff per fixture
- [ ] `timeout -s KILL 600 pytest packages/ai-parrot/tests/outputs/a2ui -q` green; `ruff check` on the four modified modules

---

## Test Specification

```python
# tests/outputs/a2ui/test_components_infographic_report.py (add)
def test_half_layout_children_grouped_in_row():
    comp = Component(id="root", component="Infographic", title="T", sections=[{"heading": "S", "components": [
        {"component": "Chart", "properties": {"type": "bar", "x": "m", "y": ["v"], "layout": "half", "data": {"path": "/a"}}},
        {"component": "Chart", "properties": {"type": "donut", "x": "m", "y": ["v"], "layout": "half", "data": {"path": "/b"}}},
    ]}])
    tree = InfographicComponent().lower(comp, {"a": [], "b": []})
    section = tree.root.children[1]   # after title Text
    rows = [c for c in section.children if c.component == "Row"]
    assert len(rows) == 1 and len(rows[0].children) == 2
    assert rows[0].metadata["extensions"]["parrot_layout"] == "half"

# tests/outputs/a2ui/adapters/test_infographic_adapter.py (add)
def test_hero_card_and_table_presentation_forwarded(variance_response):  # fixture from spec §4
    env = infographic_response_to_envelope(variance_response)
    kpi = _find(env, "KPICard"); assert kpi["properties"]["icon"] == "💰" and kpi["properties"]["comparisonPeriod"] == "vs Q2"
    table = _find(env, "DataTable"); assert table["properties"]["style"] == "striped"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2859 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `models/infographic.py:327-479, 710-805` for exact block field names; read the adapter's bullet-list converter
4. **Update status** in `sdd/tasks/index/infographic-a2ui-migration.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2860-kpicard-datatable-props-infographic-layout.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below (include the golden diff summary)

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
