# TASK-4193: `overrides_to_envelopes` — translate `schema_overrides` into A2UI envelopes

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4192
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 + §7 "Override translation table" (G3, AC5). The
`onSchemaLoaded` lifecycle hook can return shallow `schema_overrides` that
`get_schema` merges into the JSON-Schema body. On the A2UI path the user
decided (brainstorm Q1) those overrides are **translated** into
`updateComponents` / `updateDataModel` envelopes appended after the
`createSurface`, never ignored. TASK-4192 shipped the function with a
warnings-only baseline; this task implements the table. The envelope-building
pattern to copy is `api/a2ui_wire.confirmation` (lines 248-274): build models
from `_a2ui_ns()` and `serialize()` them.

---

## Scope

- Replace the baseline body of `overrides_to_envelopes` in `api/dialect.py` with the §7 table: `title`, `description`, `properties.<field_id>.{title,description,x-placeholder,x-read-only,x-options,enum,default}`, `required`; everything else → `override_not_translatable:<key>`.
- Re-lower single fields through `A2UIFormRenderer._lower_field` on a patched `FormField` copy.
- Write `tests/unit/api/test_dialect_overrides.py` (one test per table row + unknown key + unknown field), `importorskip`-guarded.

**NOT in scope**: handler wiring (TASK-4194), changing `renderers/a2ui.py` (frozen), deep-merge semantics (spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/dialect.py` | MODIFY | implement the translation table |
| `packages/parrot-formdesigner/tests/unit/api/test_dialect_overrides.py` | CREATE | per-row tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.api import a2ui_wire                                     # api/handlers.py:30 — use a2ui_wire._a2ui_ns() for lazy A2UI models
from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer, field_pointer   # renderers/a2ui.py:294, 75 (import INSIDE the function — lazy)
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection, RenderedForm   # core/schema.py:65, 401, 229, 153, 671
from parrot_formdesigner.core.options import FieldOption                          # core/options.py (fields: value: str, label: LocalizedString, description, disabled, icon)
from parrot_formdesigner.api.render import get_renderer                           # api/render.py:104
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py
def _a2ui_ns() -> Any            # line 77 — namespace with Component, ComponentMetadata, Extensions, UpdateComponents, UpdateDataModel, ErrorMessage, serialize, deserialize, A2UI_MEDIA_TYPE (verify the exact attribute set at lines 89-110 and ADD a missing name there rather than importing parrot.* directly)
def confirmation(surface_id, result, *, message="Form submitted.") -> list[dict]   # line 248 — THE pattern: m.Component(...) → m.serialize(m.UpdateComponents(surface_id=..., components=[...]))
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py
class A2UIFormRenderer(AbstractFormRenderer):
    def _lower_field(self, field: FormField, section: FormSection, subsection: FormSubsection | None, locale: str,
                     errors: dict[str, str]) -> tuple[list[Any], RenderWarning | None]     # line 606 — returns Component model instances
    # NOTE: _lower_field reads self._m (the namespace) — it is set only inside render() (line 345-350, reset in `finally` at 503).
    #       Set `renderer._m = a2ui_wire._a2ui_ns()` before calling and restore `None` after (see blueprint).
def field_pointer(field_id: str) -> str                                              # line 75 → "/answers/<escaped>"
# component ids: "root-title" (377), "root-description" (389), "root" (469), f"f-{field.field_id}" (649)
# RenderedForm.content for the a2ui renderer is m.serialize(surface) (line 492): {"version": "v1.0", "createSurface": {"surfaceId", "components": [...], ...}}
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema: sections: list[FormSection] (458); def iter_all_fields(self) -> Iterator[FormField] (477)
class FormSection: section_id; fields: list[SectionItem] (229-256)   # SectionItem = FormField | FormSubsection (226)
class FormSubsection: subsection_id; fields: list[FormField] (153-159)
class FormField: label; description; placeholder; required; default; read_only; options: list[FieldOption] | None (123-143)
```

### Does NOT Exist
- ~~`A2UIFormRenderer.lower_field` (public)~~ — only the private `_lower_field`; the task pins it (spec §7 Known Risks) and the test fails loudly if FEAT-544 renames it.
- ~~`A2UIFormRenderer.render_field()` / `rerender()`~~ — no such helpers.
- ~~deep merge of overrides~~ — only top-level keys of `overrides` and the direct sub-keys of `properties.<field_id>` are read.
- ~~`UpdateComponents` for a field whose id is not `f-<field_id>` in the surface~~ — unknown field → warning `override_unknown_field:<id>`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/dialect.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/api/test_dialect_overrides.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py#_a2ui_ns",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py#confirmation",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py#A2UIFormRenderer",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py#field_pointer"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Deterministic output: iterate `overrides` in insertion order; one `updateComponents` per touched component id, one `updateDataModel` per default change.
- All envelopes carry `surfaceId == f"form-{form.form_uid}"` and are `serialize()`d dicts; each must pass `validate_message()` (test).
- Imports of `parrot.*` and of `renderers.a2ui` happen **inside** the function (AC12).

### Translation table (spec §7 — normative)
| key | envelope | note |
|---|---|---|
| `title` | `updateComponents` replacing `root-title` (`Text`) | if absent in surface: new `Text` + `updateComponents` for `root` with the new id prepended to `children` |
| `description` | same for `root-description` | same create-if-missing |
| `properties.<fid>.{title, description, x-placeholder, x-read-only, x-options, enum}` | one `updateComponents` with the re-lowered component(s) for `f-<fid>` | unknown `<fid>` → `override_unknown_field:<fid>` |
| `properties.<fid>.default` | `updateDataModel{path: field_pointer(fid), value}` (+ the re-lowered component when the primitive binds `value` literally) | |
| `required` (list) | re-lower each field whose `required` flips; one `updateComponents` with all | fields not in surface → warning |
| other | none | `override_not_translatable:<key>` |

---

## Implementation Blueprint

### Steps (in order)
1. Add a private `_patched_field(field, prop_overrides) -> FormField` that returns `field.model_copy(update=...)` mapping `title→label`, `description→description`, `x-placeholder→placeholder`, `x-read-only→read_only`, `x-options/enum→options`, `default→default` — *why*: re-lowering must go through the FEAT-544 table, never a hand-built component.
2. Add `_relower(renderer, form, field_id, patched) -> list[Any]` that finds the owning section/subsection by walking `form.sections`, sets `renderer._m`, calls `_lower_field`, restores `_m` in `finally` — *why*: `_lower_field` needs the namespace only `render()` normally sets.
3. Implement the table in `overrides_to_envelopes` in insertion order — *why*: AC5 is tested row by row.
4. Tests: render a real surface with `A2UIFormRenderer`, apply each override, assert envelope kind/ids and `validate_message()`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/dialect.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    return \[\], \[f"override_not_translatable:{key}" for key in overrides\]' packages/parrot-formdesigner/src/parrot_formdesigner/api/dialect.py)
# REPLACE the TASK-4192 baseline body of overrides_to_envelopes (keep the signature + docstring, update the docstring's TASK note) with:
    from . import a2ui_wire  # lazy: the A2UI path only exists when the extra is installed
    from ..renderers.a2ui import A2UIFormRenderer, field_pointer

    m = a2ui_wire._a2ui_ns()
    renderer = get_renderer("a2ui")
    surface_id = f"form-{form.form_uid}"
    surface = rendered.content["createSurface"]
    present_ids = {c["id"] for c in surface["components"]}
    fields_by_id = {f.field_id: f for f in form.iter_all_fields()}
    envelopes: list[dict[str, Any]] = []
    warnings: list[str] = []
    for key, value in overrides.items():
        if key in ("title", "description"):
            comp_id = f"root-{key}"
            text = m.Component(id=comp_id, component="Text", text=str(value),
                               metadata=m.ComponentMetadata(extensions=m.Extensions({"parrot_role": key})))
            # FILL IN: if comp_id not in present_ids → also emit an updateComponents for "root" whose children = [comp_id, *existing root children] — bounded by §7 create-if-missing rule
            envelopes.append(m.serialize(m.UpdateComponents(surface_id=surface_id, components=[text])))
        elif key == "properties" and isinstance(value, dict):
            for fid, prop in value.items():
                field = fields_by_id.get(fid)
                if field is None or f"f-{fid}" not in present_ids or not isinstance(prop, dict):
                    warnings.append(f"override_unknown_field:{fid}")
                    continue
                if "default" in prop:
                    envelopes.append(m.serialize(m.UpdateDataModel(surface_id=surface_id, path=field_pointer(fid), value=prop["default"])))
                if not isinstance(renderer, A2UIFormRenderer):
                    warnings.append(f"override_not_translatable:properties.{fid}")
                    continue
                comps = _relower(renderer, form, fid, _patched_field(field, prop), locale, m)
                envelopes.append(m.serialize(m.UpdateComponents(surface_id=surface_id, components=comps)))
        elif key == "required" and isinstance(value, list):
            # FILL IN: for each fid in fields_by_id whose `required` != (fid in value): relower with required flipped; collect
            #          all components into ONE updateComponents; unknown ids → warning — bounded by §7 table row `required`
            pass
        else:
            warnings.append(f"override_not_translatable:{key}")
    return envelopes, warnings


def _patched_field(field: FormField, prop: Mapping[str, Any]) -> FormField:
    """Copy ``field`` with the JSON-Schema-level overrides applied (spec §7 table)."""
    update: dict[str, Any] = {}
    if "title" in prop:
        update["label"] = prop["title"]
    if "description" in prop:
        update["description"] = prop["description"]
    if "x-placeholder" in prop:
        update["placeholder"] = prop["x-placeholder"]
    if "x-read-only" in prop:
        update["read_only"] = bool(prop["x-read-only"])
    if "default" in prop:
        update["default"] = prop["default"]
    # FILL IN: "x-options" ([{value,label,disabled?}]) and bare "enum" ([...]) → update["options"] = [FieldOption(...)] — bounded by core/options.FieldOption fields
    return field.model_copy(update=update)


def _relower(renderer: Any, form: FormSchema, field_id: str, patched: FormField, locale: str, m: Any) -> list[Any]:
    """Re-lower ONE field through the FEAT-544 table; returns Component instances for an updateComponents."""
    # FILL IN: locate (section, subsection|None) owning field_id by walking form.sections (FormSubsection has .fields) — bounded by core/schema.py:229/153
    renderer._m = m
    try:
        components, _warning = renderer._lower_field(patched, section, subsection, locale, {})
    finally:
        renderer._m = None
    return components
```
**Why this shape**: envelopes are built exactly like `a2ui_wire.confirmation` so the wire framing is identical; re-lowering through `_lower_field` keeps one lowering truth (spec Non-Goals); the private-method dependency is pinned here on purpose (spec §7 Known Risks) — if it is renamed, the test fails loudly instead of guessing. Import `FormField`, `FormSection`, `FormSubsection` at module top (they are formdesigner-internal, no extra needed).

### `packages/parrot-formdesigner/tests/unit/api/test_dialect_overrides.py` (CREATE)
```python
"""overrides_to_envelopes — FEAT-650 TASK-4193 (requires the ai-parrot extra)."""

from __future__ import annotations

import pytest

pytest.importorskip("parrot.outputs.a2ui")

from parrot.outputs.a2ui.catalog import validate_message  # noqa: E402
from parrot.outputs.a2ui.serialization import deserialize  # noqa: E402
from parrot_formdesigner.api import dialect as d  # noqa: E402
from parrot_formdesigner.api.render import _RENDERERS, register_renderer  # noqa: E402
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection  # noqa: E402
from parrot_formdesigner.core.types import FieldType  # noqa: E402
from parrot_formdesigner.renderers import A2UIFormRenderer  # noqa: E402


@pytest.fixture(autouse=True)
def _a2ui():
    snap = dict(_RENDERERS); _RENDERERS.clear(); register_renderer("a2ui", A2UIFormRenderer()); yield
    _RENDERERS.clear(); _RENDERERS.update(snap)


@pytest.fixture
def form() -> FormSchema:
    return FormSchema(form_id="f", title={"en": "F"}, description={"en": "D"}, tenant="navigator", sections=[FormSection(
        section_id="s", fields=[FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"}),
                                FormField(field_id="color", field_type=FieldType.SELECT, label={"en": "Color"},
                                          options=[{"value": "r", "label": "Red"}])])])


async def _apply(form, overrides):
    envelopes, rendered, warnings = await d.render_a2ui_schema(form, overrides=overrides)
    for env in envelopes:
        validate_message(deserialize(env))
    return envelopes, warnings


async def test_title_replaces_root_title(form):
    envelopes, warnings = await _apply(form, {"title": "New"})
    # FILL IN: envelopes[1]["updateComponents"]["components"][0]["id"] == "root-title" and text == "New"; warnings == [] — bounded by §7 row `title`


async def test_property_title_relowers_field(form):
    envelopes, warnings = await _apply(form, {"properties": {"name": {"title": "Full name"}}})
    # FILL IN: one updateComponents whose component id == "f-name" with label "Full name" — bounded by §7 row properties.*


async def test_property_default_emits_update_data_model(form):
    envelopes, warnings = await _apply(form, {"properties": {"name": {"default": "Ana"}}})
    # FILL IN: an updateDataModel with path "/answers/name" and value "Ana" — bounded by §7


async def test_property_options_and_required(form):
    # FILL IN: {"properties": {"color": {"x-options": [...]}}, "required": ["name"]} → two updateComponents; name's checks contain required — bounded by §7
    pass


async def test_unknown_field_and_untranslatable_key_warn(form):
    envelopes, warnings = await _apply(form, {"properties": {"nope": {"title": "x"}}, "$schema": "x"})
    assert len(envelopes) == 1
    assert warnings == ["override_unknown_field:nope", "override_not_translatable:$schema"]
```
**Why this shape**: every §7 row gets a test (AC5); `validate_message` on every envelope is AC4; the fixture uses the real renderer because the translation is meaningless against a fake.

### FILL IN checklist
- [ ] `dialect.py::overrides_to_envelopes` — create-if-missing for `root-title`/`root-description`; bounded by §7 table.
- [ ] `dialect.py::overrides_to_envelopes` — `required` row; bounded by §7 table.
- [ ] `dialect.py::_patched_field` — `x-options`/`enum` → `FieldOption` list; bounded by `core/options.FieldOption`.
- [ ] `dialect.py::_relower` — owner section/subsection lookup; bounded by `core/schema.py:229/153`.
- [ ] test bodies marked `FILL IN`; bounded by AC5.

---

## Acceptance Criteria

- [ ] Every §7 table row produces the specified envelope(s); unknown keys/fields only warn (AC5).
- [ ] Every emitted envelope passes `validate_message()` and carries `surfaceId == f"form-{form_uid}"` (AC4).
- [ ] `renderers/a2ui.py` is untouched (AC14).
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_dialect_overrides.py -v`
- [ ] `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/dialect.py` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_dialect_overrides.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/api/test_dialect_negotiation.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_renderer.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §7 "Override translation table" and `api/a2ui_wire.py:248-274`
3. **Check dependencies** — TASK-4192 `"done"`
4. **Verify the Codebase Contract** — `grep -n 'def _lower_field\|self._m = ' packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py`; `sed -n 77,110p packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src` + Validation Commands
8. **Commit the code** — only the two files
9. **Close** with `scripts/sdd/close_task.sh TASK-4193 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
