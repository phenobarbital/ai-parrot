# TASK-2715: FilterBar composite + lowering golden + honest degradation on JS-less surfaces

**Feature**: FEAT-493 — Backend HTML Design System
**Spec**: `sdd/specs/html-renderer-design-system.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2710
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (first half). The filter bar is the only part of this
feature that needs **net-new catalog vocabulary**: nothing in the 8
registered Parrot composites expresses "a bar of filters over this
surface's data". This task adds the composite and its lowering, and defines
what the JS-less surfaces do with it — deliberately separated from the
interactive behaviour (TASK-2716) so the vocabulary lands and is tested
before any client-side state exists.

Note the boundary carefully: this is the ONE place where this feature is
permitted to add a file under `catalog/` and a golden fixture. Every other
task is forbidden from touching either.

---

## Scope

- Create `catalog/parrot/filterbar.py` with `FILTERBAR_SCHEMA`,
  `FILTERBAR_INSTRUCTIONS` and `FilterBarComponent`, registered via
  `@register_component("FilterBar")` and display-only
  (`requires_actions=False`).
- Schema: `filters` — a list of `{column, label, options[], multiple?}` —
  plus an optional `title`. `column` is the data-model column the filter
  applies to.
- `lower()` returns a `Row` with
  `metadata={"extensions": {"parrot_variant": "filter-bar"}}`, whose children
  are `ChoicePicker` primitives, each carrying
  `parrot_role: "filter"` and `parrot_filter_column: <column>`.
- Register the module in `catalog/parrot/__init__.py`'s import list.
- Add the golden fixture
  `packages/ai-parrot/tests/outputs/a2ui/golden/filterbar_lowered.json`
  following the exact existing pattern: lowered twice, both dumps equal, and
  equal to the fixture bytes (determinism is part of the assertion).
- **Degradation on `ssr-html` and `pdf`**: emit a filter-state summary line
  ("Filters: Month = Aug-2026; Pay Code = all") plus a
  `degradation_record(...)`. Never a `<select>` or dropdown that a reader can
  click and that does nothing.

**NOT in scope**: the interactive multiselect UI and client-side filtering
(TASK-2716); the filter-bar CSS (TASK-2707 authored it); wiring filters to
recipe params.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/filterbar.py` | CREATE | The composite |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py` | MODIFY | Add `filterbar` to the import list |
| `packages/ai-parrot/tests/outputs/a2ui/golden/filterbar_lowered.json` | CREATE | Lowering golden |
| `packages/ai-parrot/tests/outputs/a2ui/test_components_filterbar.py` | CREATE | Registration + golden + primitive-validity tests |
| `.../a2ui_renderers/ssr_html.py` | MODIFY | Degradation to a summary line |
| `packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_filterbar_degradation.py` | CREATE | Degradation tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.outputs.a2ui.catalog import get_component, register_component
# verified: packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py:107
from parrot.outputs.a2ui.catalog.base import BasicNode, BasicTree, to_components
from parrot.outputs.a2ui.models import Component
from parrot.outputs.a2ui.renderers.degrade import degradation_record
# verified: packages/ai-parrot/src/parrot/outputs/a2ui/renderers/degrade.py:46
```

### The registration decorator

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py:107-116
def register_component(
    name: str,
    *,
    requires_actions: bool = False,
    catalog_id: str = DEFAULT_CATALOG_ID,
    is_primitive: bool = False,
    allowed_parents: list[str] | None = None,
    allowed_children: list[str] | None = None,
) -> Callable[[type], type]:
    """...Enforces the mandatory lowering contract at registration time: a class
    without a callable ``lower()`` cannot register (raises ComponentContractError)
    UNLESS is_primitive=True..."""
```

### The composite to copy structurally

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/kpicard.py
KPICARD_SCHEMA: dict[str, Any] = {"type": "object", "properties": {...}, "required": [...]}   # line 16
KPICARD_INSTRUCTIONS = ("Use KPICard to ... Display-only.")                                   # line 28

@register_component("KPICard")                     # line 49
class KPICardComponent:                            # line 50
    SCHEMA = KPICARD_SCHEMA
    INSTRUCTIONS = KPICARD_INSTRUCTIONS
    def lower(self, component: Component, data_model: dict[str, Any]) -> BasicTree:   # line 56
        props = component.model_extra or {}
        ...
        return BasicNode(
            id=component.id,
            component="Card",
            child=BasicNode(component="Column", children=children),
            metadata={"extensions": {"parrot_variant": "kpi"}},        # line 94
        )
```

### The registration index that must be updated

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/__init__.py:14-23
from parrot.outputs.a2ui.catalog.parrot import (
    chart, datatable, infocard, infographic, kpicard, map, report, timeline,  # noqa: F401
)
# `form` is intentionally NOT imported — Form is retired (spec G6)
```

A component module that is not imported here is never registered.

### The golden-test pattern to follow EXACTLY

```python
# packages/ai-parrot/tests/outputs/a2ui/test_components_card_kpicard_timeline_form.py:16-24, 87-96
GOLDEN_DIR = Path(__file__).parent / "golden"

def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(mode="json", exclude_none=True),
                      sort_keys=True, indent=2).encode() + b"\n"

def _validates(tree) -> None:
    flat = to_components(tree)
    ...

class TestKPICardComponent:
    def test_kpicard_registered_in_catalog(self):
        assert get_component("KPICard").definition.requires_actions is False

    def test_kpicard_lowering_golden(self):
        one = _dump(kpicard.KPICardComponent().lower(_kpicard(), {}))
        two = _dump(kpicard.KPICardComponent().lower(_kpicard(), {}))
        assert one == two == (GOLDEN_DIR / "kpicard_lowered.json").read_bytes()
```

Lowering twice and asserting equality is how determinism is enforced — keep
it. Note the trailing newline in `_dump`; the fixture file must end with one.

### The primitive being composed

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/catalog/basic/inputs.py
class ChoicePicker(Checkable, Component):          # line 100
    INSTRUCTIONS: ClassVar[str] = (
        "ChoicePicker: requires `options` (list of {label, value}) and ..."  # line 104
    )
    component: Literal["ChoicePicker"] = "ChoicePicker"    # line 111
class ChoiceOption(BaseModel):                     # line 92 — a single {label, value}
```

### The degradation helper

```python
# packages/ai-parrot/src/parrot/outputs/a2ui/renderers/degrade.py
def degrade(node: BasicNode, reason: str) -> BasicNode: ...          # line 24
    # returns a Text BasicNode with metadata.extensions.parrot_role="notice"
def degradation_record(node: BasicNode, reason: str) -> dict[str, Any]: ...   # line 46
```

Renderers accumulate records into a `degradations` list which becomes
`RenderedArtifact.metadata["degraded"]`.

### Does NOT Exist

- ~~`FilterBar` / `FilterBarComponent` / `FILTERBAR_SCHEMA`~~ — all net-new (0 hits repo-wide)
- ~~`parrot_filter_column`~~ — net-new extension key (0 hits)
- ~~`Filter` as a Basic Catalog primitive~~ — the 18 primitives include `ChoicePicker`, `CheckBox`, `Slider`, `TextField`, `DateTimeInput`, but nothing named `Filter`
- ~~`Form` as a registered component~~ — deliberately retired (`catalog/parrot/__init__.py` docstring); do not model `FilterBar` on it
- ~~`degrade_record` / `record_degradation`~~ — the real name is `degradation_record` (`degrade.py:46`)
- ~~a `filters` key in any existing schema~~ — no filter vocabulary exists anywhere in the catalog today

---

## Implementation Notes

### Key Constraints

- Display-only: `requires_actions=False`. An action-bearing component is
  rejected by `validate_envelope` for LLM-produced envelopes, which would
  make `FilterBar` unusable from the producer side.
- **Determinism.** The golden test lowers twice and compares. Do not mint
  ids with `uuid` or embed timestamps inside `lower()`; derive any child id
  from `component.id`.
- The degradation summary must state the *effective* filter state, including
  "all" for an unconstrained filter — a summary that omits unset filters
  reads as though they were applied.
- Do not modify any other file under `catalog/` — TASK-2710's guard test
  permits only `filterbar`-named additions.

### References in Codebase

- `.../catalog/parrot/kpicard.py` — the closest structural precedent (small schema, variant-tagged Card)
- `.../catalog/parrot/datatable.py:56-66` — how a composite tags children with roles
- `docs/flex_program_report (39).html` lines 60-105 — the reference filter-bar markup this vocabulary must be able to express

---

## Acceptance Criteria

- [ ] `get_component("FilterBar").definition.requires_actions is False`
- [ ] `FilterBar` appears in the catalog only after `catalog/parrot/__init__.py` imports it — verified by the registration test
- [ ] `lower()` returns a `Row` tagged `parrot_variant: "filter-bar"` whose children are `ChoicePicker` nodes carrying `parrot_role: "filter"` and `parrot_filter_column`
- [ ] Lowering the same component twice produces byte-identical dumps, equal to `filterbar_lowered.json`
- [ ] `to_components()` accepts the lowered tree (valid v1.0 primitives)
- [ ] `ssr-html` renders a filter-state summary line and records a `degradation_record`; the output contains no `<select>` and no dropdown control
- [ ] The summary names every declared filter, using "all" for unconstrained ones
- [ ] The other 8 goldens are unchanged
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/ packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/test_components_filterbar.py
import json
from pathlib import Path

from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog.base import to_components
from parrot.outputs.a2ui.catalog.parrot import filterbar
from parrot.outputs.a2ui.models import Component

GOLDEN_DIR = Path(__file__).parent / "golden"


def _dump(tree) -> bytes:
    return json.dumps(tree.model_dump(mode="json", exclude_none=True),
                      sort_keys=True, indent=2).encode() + b"\n"


def _filterbar() -> Component:
    return Component(
        id="fb", component="FilterBar",
        filters=[
            {"column": "month", "label": "Month",
             "options": [{"label": "Aug-2026", "value": "2026-08"}], "multiple": True},
            {"column": "pay_code", "label": "Pay Code", "options": []},
        ],
    )


class TestFilterBarComponent:
    def test_filterbar_registered_in_catalog(self):
        assert get_component("FilterBar").definition.requires_actions is False

    def test_filterbar_lowering_golden(self):
        one = _dump(filterbar.FilterBarComponent().lower(_filterbar(), {}))
        two = _dump(filterbar.FilterBarComponent().lower(_filterbar(), {}))
        assert one == two == (GOLDEN_DIR / "filterbar_lowered.json").read_bytes()

    def test_filterbar_emits_v1_primitives(self):
        tree = filterbar.FilterBarComponent().lower(_filterbar(), {})
        assert tree.component == "Row"
        assert tree.metadata.extensions.root["parrot_variant"] == "filter-bar"
        to_components(tree)

    def test_children_carry_filter_column(self):
        tree = filterbar.FilterBarComponent().lower(_filterbar(), {})
        cols = [c.metadata.extensions.root["parrot_filter_column"] for c in tree.children]
        assert cols == ["month", "pay_code"]


# packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_filterbar_degradation.py
class TestFilterBarDegradation:
    async def test_ssr_renders_summary_not_a_control(self): ...
    async def test_ssr_records_degradation(self): ...
    async def test_summary_names_unconstrained_filters_as_all(self): ...
    async def test_pdf_inherits_the_degradation(self): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 8) and note the boundary: this is the only
   task permitted to add a `catalog/` file and a golden fixture.
2. **Check dependencies** — TASK-2710 must be completed.
3. **Verify the Codebase Contract**, especially the golden `_dump` helper
   (including its trailing newline) and the `catalog/parrot/__init__.py`
   import list.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope. Keep `lower()` deterministic.
6. **Verify** every acceptance criterion, and confirm the other 8 goldens are
   untouched.
7. **Move this file** to `sdd/tasks/completed/`, update the index → `"done"`,
   fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-02
**Notes**: Created `catalog/parrot/filterbar.py` with `FILTERBAR_SCHEMA`
(`filters`: list of `{column, label, options[], multiple?}`, optional
`title`), `FILTERBAR_INSTRUCTIONS`, and `FilterBarComponent` (`@register_
component("FilterBar")`, display-only). `lower()` returns a `Row` tagged
`parrot_variant: "filter-bar"` whose children are `ChoicePicker`
primitives, each carrying `parrot_role: "filter"` and
`parrot_filter_column`. Interpretation decision (the schema has no
"current selection" field): a filter with exactly ONE declared option
lowers pre-selected (`value=[that option's value]`); zero or multiple
options start unconstrained (`value=[]`, meaning "all") — this exactly
reproduces the task's own illustrative example ("Month = Aug-2026; Pay
Code = all") from a fixture where Month has 1 option and Pay Code has 0.
Child ids are deterministic (`{component.id}-f{i}`, no `uuid`/timestamp).
Registered `filterbar` in `catalog/parrot/__init__.py`'s import list.
Generated `filterbar_lowered.json` from the task's own `_filterbar()`
fixture. `ssr_html._render_Row` degrades a `parrot_variant: "filter-bar"`
Row to ONE combined summary `<p>` line + a single `degradation_record` on
the Row itself (not per-filter) — never delegates to the generic
`_render_ChoicePicker` path, so no per-filter markup leaks through.
`PDFRenderer` inherits this dispatch unmodified (verified).

Tests: this task's new
`packages/ai-parrot/tests/outputs/a2ui/test_components_filterbar.py` (9
tests) and
`packages/ai-parrot-visualizations/tests/outputs/a2ui_renderers/test_filterbar_degradation.py`
(4 tests) pass; the full `packages/ai-parrot-visualizations/tests/` suite
(209 tests) passes; `packages/ai-parrot/tests/outputs/a2ui/catalog/` (110
tests, `-m "not network"`) and the golden-adjacent component test files
(45 tests) pass. `ruff check` and `mypy` clean on all changed/created
files (`filterbar.py`'s `mypy` "unexpected keyword argument"/"incompatible
metadata type" notes are the SAME pre-existing pattern verified present in
`kpicard.py` — `BasicNode`'s `extra="allow"` isn't understood statically
by mypy anywhere in this catalog, not a regression).

**Found and fixed a bug in TASK-2710's own guard test** (necessary to
verify THIS task's own "goldens untouched" acceptance criterion
honestly): `test_semantic_classes.py::TestGoldensUntouched::
test_no_catalog_file_modified` (a) needed to allow
`catalog/parrot/__init__.py`'s registration-list touch — the one other
file every new catalog component unavoidably requires, which TASK-2710's
"filterbar.py + its golden are the ONLY permitted additions" wording
hadn't anticipated; and (b), more importantly, its bare `git diff`
subprocess call had NO `cwd=` anchor — discovered that importing
`DatasetManager`/Navigator-adjacent modules earlier in a pytest session
triggers navconfig's settings bootstrap, which calls `os.chdir()` back to
the MAIN REPO checkout, and that chdir PERSISTS for the rest of the
process. Without `cwd=`, this test's `git diff` silently ran against the
main repo (no worktree changes visible there) and passed VACUOUSLY on an
empty diff regardless of what `catalog/` files were actually touched —
verified by adding a debug print and reproducing the empty-diff-under-
pytest vs non-empty-diff-outside-pytest split. Fixed by anchoring with
`cwd=Path(__file__).resolve().parents[5]`. Recorded as a wiki memory
lesson for future sessions.

**Deviations from spec**: `title` is declared in `FILTERBAR_SCHEMA` (per
scope: "plus an optional title") but NOT used in `lower()`'s output — the
acceptance criteria and test contract explicitly enumerate the Row's
children as ChoicePicker-only (`test_children_carry_filter_column`
list-comprehends every child's `parrot_filter_column`, which a title
`Text` child would not have), so wiring a title render was out of this
task's explicit contract; the field is schema-complete for a future task
to consume. Also touched `test_semantic_classes.py` (TASK-2710's file, not
in this task's own file list) — see the bug-fix note above; unavoidable to
honestly verify this task's own acceptance criteria.
