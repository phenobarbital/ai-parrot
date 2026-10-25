# TASK-4198: `JsonSchemaExtractor` fidelity — section tree, `x-placeholder`, `x-read-only`, `x-options`, `default`, `description`

**Feature**: FEAT-650 — A2UI dialect for parrot-formdesigner
**Spec**: `sdd/specs/a2ui-dialect-formbuilder.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (G5, AC8, codex S4). JSON-Schema → A2UI is built by
composition (`JsonSchemaExtractor` → `A2UIFormRenderer`), so the extractor
must recover what `JsonSchemaRenderer` emits. Today it ignores `x-section`
/ `x-subsection` (every form collapses into one `"fields"` section),
`x-placeholder`, `x-read-only`, labelled `x-options` (array-typed
MULTI_SELECT/TAGS lose their options entirely — they are under `items.enum`
+ `x-options`), and section-level `depends_on`. This task closes those gaps
and adds a fixture-based renderer→extractor round-trip.

---

## Scope

- `extract()`: group properties by `x-section` / `x-subsection` (first-seen order) into `FormSection` / `FormSubsection`, with `title`, `description`, `depends_on` from `x-section-depends-on` / `x-subsection-depends-on`; properties without `x-section` keep today's `"fields"` section.
- `_property_to_field()`: `x-placeholder` → `placeholder`; `x-read-only` → `read_only`; `x-options` (`[{value,label,disabled?}]`) → `options`, preferred over bare `enum` and over `items.enum` for array-typed properties (keep `field_type` from `x-field-type`); `default` and `description` already flow — assert them in tests.
- Tests `tests/unit/extractors/test_jsonschema_sections.py`: renderer → extractor round-trip over a 2-section/1-subsection fixture; Pydantic input unchanged.

**NOT in scope**: `translate_jsonschema_to_a2ui` (TASK-4199), the renderer (`renderers/jsonschema.py` is read-only), style/snippets/events recovery (spec Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` | MODIFY | section tree + `x-*` fidelity |
| `packages/parrot-formdesigner/tests/unit/extractors/test_jsonschema_sections.py` | CREATE | round-trip tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already imported in extractors/jsonschema.py:13-22 — reuse, do not re-import:
from ..core.constraints import (DependencyRule, ... )         # line 13 block (DependencyRule used at :291 via model_validate)
from ..core.options import FieldOption, OptionsSource         # line 18
from ..core.resolution import resolve_rule_references         # line 20
from ..core.schema import FormField, FormSchema, FormSection  # line 21  ← ADD FormSubsection to this line
from ..core.types import FieldType                            # line 22
# tests:
from parrot_formdesigner.renderers import JsonSchemaRenderer  # renderers/__init__.py
from parrot_formdesigner.extractors import JsonSchemaExtractor
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py
class JsonSchemaExtractor:                                               # line 67
    def extract(self, schema, *, form_id=None, title=None) -> FormSchema # line 86
        # 109-124: required_set / properties / `fields: list[FormField] = []` (114) / loop calling _property_to_field (116-123)
        # 126-134: form = FormSchema(form_id=..., title=..., sections=[FormSection(section_id="fields", title=..., fields=fields)])
        # 141: return resolve_rule_references(form)
    def _property_to_field(self, *, name, prop, required, root_schema) -> FormField   # line 176
        # 211-212: label = prop.get("title", ...); description = prop.get("description"); 213: default = prop.get("default")
        # 231-233: `# Handle enum → SELECT` → field_type = FieldType.SELECT; options = [FieldOption(value=str(v), label=str(v)) ...]
        # 345: final `return FormField(field_id=name, field_type=..., label=..., description=..., required=..., default=..., constraints=..., options=options, ...)`
    def _map_type(self, prop) -> FieldType                               # line 390 (honours x-field-type at 411)
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSubsection(BaseModel): subsection_id: str; title; description; fields: list[FormField]; depends_on: DependencyRule | None; meta   # 153-159
class FormSection(BaseModel): section_id: str; title; description; fields: list[SectionItem]; depends_on: DependencyRule | None; meta        # 229-256
class FormField: placeholder: LocalizedString | None (127); read_only: bool = False (130); options: list[FieldOption] | None (132)
# packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py
class FieldOption(BaseModel): value: str; label: LocalizedString; description; disabled: bool; icon   # lines 25-30
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py — what the renderer EMITS (read-only):
#   x-section = {"section_id", "title", "description"} (420-426); x-subsection = {"subsection_id", "title", "description"} (429-431)
#   x-section-depends-on = section.depends_on (436, 446 — may arrive as a dict after JSON transport); x-subsection-depends-on = item.depends_on.model_dump() (437)
#   x-options = [{"value", "label"}] (564-569 single; 577-582 array-typed under the property, while `items.enum` holds the raw values)
#   x-placeholder (617), x-read-only = True (622), x-field-type (493)
```

### Does NOT Exist
- ~~`x-section` handling anywhere in the extractor~~ — this task adds it (verified by grep: zero hits today).
- ~~`JsonSchemaExtractor.extract_sections()`~~ — no such method; the grouping lives inside `extract()`.
- ~~`FieldOption.model_validate` from `x-options` entries with `disabled`~~ — `disabled` exists on `FieldOption`; `icon`/`description` may be absent — construct explicitly.
- ~~`x-section` on Pydantic / OpenAPI schemas~~ — absent ⇒ legacy single `"fields"` section (AC8).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/unit/extractors/test_jsonschema_sections.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py#JsonSchemaExtractor",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSubsection",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormSection",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/options.py#FieldOption"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Preserve first-seen order of sections and of fields within them (property order == renderer order).
- A `x-section-depends-on` value may be a dict (JSON transport) or an object with `model_dump()` — accept both, warn and drop on validation failure (same style as `x-depends-on` handling at line 291-296).
- `x-options` wins over `enum` for both single and array-typed properties; do NOT force `field_type = SELECT` when `x-field-type` declared another type (e.g. `multi_select`, `tags`).

---

## Implementation Blueprint

### Steps (in order)
1. Add `FormSubsection` to the `core.schema` import — *why*: the subsection container is needed to rebuild the tree.
2. Replace the single-section assembly in `extract()` with a grouping helper `_group_sections(fields_with_props)` — *why*: keeps `extract()` readable and the legacy path intact.
3. Extend `_property_to_field` for `x-placeholder`, `x-read-only`, `x-options` — *why*: AC8.
4. Write the renderer→extractor round-trip tests.

### `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` (MODIFY — extract)
```python
# occurrences: 1 (verified: grep -c '        fields: list\[FormField\] = \[\]' packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py)
# REPLACE the block from `        fields: list[FormField] = []` (verified: :114) through the `form = FormSchema(...)` assembly
# (`        form = FormSchema(` verified: :126, occurrences 1) so that it reads:
        entries: list[tuple[FormField, dict[str, Any]]] = []
        for prop_name, prop_schema in properties.items():
            field = self._property_to_field(
                name=prop_name, prop=prop_schema, required=prop_name in required_set, root_schema=root_schema
            )
            entries.append((field, prop_schema if isinstance(prop_schema, dict) else {}))
        form = FormSchema(
            form_id=resolved_form_id,
            title=resolved_title,
            sections=self._group_sections(entries, resolved_title),
        )
# (keep the existing `return resolve_rule_references(form)` at the end, verified :141)

    def _group_sections(self, entries: list[tuple[FormField, dict[str, Any]]], title: str) -> list[FormSection]:
        """Rebuild the section/subsection tree from ``x-section`` / ``x-subsection`` (FEAT-650).

        Properties without ``x-section`` fall into the legacy ``"fields"`` section so
        Pydantic/OpenAPI input is unchanged. Order is first-seen.
        """
        sections: dict[str, FormSection] = {}
        subsections: dict[tuple[str, str], FormSubsection] = {}
        for field, prop in entries:
            sec_meta = prop.get("x-section") if isinstance(prop.get("x-section"), dict) else None
            if sec_meta is None:
                section = sections.setdefault("fields", FormSection(section_id="fields", title=title, fields=[]))
                section.fields.append(field)
                continue
            sid = str(sec_meta.get("section_id") or "fields")
            if sid not in sections:
                sections[sid] = FormSection(section_id=sid, title=sec_meta.get("title"), description=sec_meta.get("description"),
                                            fields=[], depends_on=self._dependency(prop.get("x-section-depends-on"), sid))
            sub_meta = prop.get("x-subsection") if isinstance(prop.get("x-subsection"), dict) else None
            if sub_meta is None:
                sections[sid].fields.append(field)
                continue
            # FILL IN: key=(sid, sub_meta["subsection_id"]); create FormSubsection(title, description, fields=[],
            #          depends_on=self._dependency(prop.get("x-subsection-depends-on"), ...)) once, append it to
            #          sections[sid].fields on creation, then append `field` to its .fields — bounded by core/schema.py:153
        return list(sections.values())

    def _dependency(self, raw: Any, owner: str) -> DependencyRule | None:
        """Accept a dict (JSON transport) or an object with ``model_dump()``; warn and drop on failure."""
        if raw is None:
            return None
        data = raw.model_dump() if hasattr(raw, "model_dump") else raw
        try:
            return DependencyRule.model_validate(data)
        except Exception:  # noqa: BLE001 — same tolerance as x-depends-on at :291-296
            logger.warning("Could not reconstruct section depends_on for '%s'", owner)
            return None
```
**Why this shape**: grouping after field construction keeps `_property_to_field` single-responsibility; the `"fields"` fallback is the AC8 legacy guarantee; `_dependency` mirrors the existing tolerance pattern. Note `FormSection.fields` / `FormSubsection.fields` are plain lists on pydantic models — appending after construction is fine because `FormSchema` validation (uniqueness, `resolve_rule_references`) runs at the end.

### `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py` (MODIFY — `_property_to_field`)
```python
# occurrences: 1 (verified: grep -c '        # Handle enum → SELECT' packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py)
# REPLACE the `# Handle enum → SELECT` block (verified :231-233, three lines) with:
        # Options: labelled x-options (renderer, single AND array-typed) win over bare enum / items.enum (FEAT-650)
        x_options = prop.get("x-options")
        if isinstance(x_options, list) and x_options:
            options = [
                FieldOption(value=str(o.get("value")), label=o.get("label") or str(o.get("value")), disabled=bool(o.get("disabled", False)))
                for o in x_options if isinstance(o, dict) and o.get("value") is not None
            ]
            if "x-field-type" not in prop and field_type not in (FieldType.MULTI_SELECT, FieldType.TAGS):
                field_type = FieldType.SELECT
        elif "enum" in prop:
            field_type = FieldType.SELECT
            options = [FieldOption(value=str(v), label=str(v)) for v in prop["enum"] if v is not None]
        placeholder = prop.get("x-placeholder")
        read_only = bool(prop.get("x-read-only", False))
# occurrences: 2 (verified: grep -c '        return FormField($' packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py)
# FILL IN: disambiguate — the SECOND `        return FormField(` (the final one at :343, right after the `answer_envelope`
#          validation block; the first at :214 is the x-parrot-rest early return, indented 12 spaces). In the second call add the kwargs:
            placeholder=placeholder,
            read_only=read_only,
```
**Why**: `x-options` carries labels/disabled the renderer emitted (S4); `x-field-type` is honoured by `_map_type` (:411) so an array-typed `multi_select` keeps its type while gaining options.

### `packages/parrot-formdesigner/tests/unit/extractors/test_jsonschema_sections.py` (CREATE)
```python
"""JsonSchemaRenderer → JsonSchemaExtractor fidelity — FEAT-650 TASK-4198."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, FormSubsection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.extractors import JsonSchemaExtractor
from parrot_formdesigner.renderers import JsonSchemaRenderer


@pytest.fixture
def form() -> FormSchema:
    return FormSchema(form_id="rt", title={"en": "RT"}, tenant="navigator", sections=[
        FormSection(section_id="s1", title={"en": "One"}, description={"en": "d1"}, fields=[
            FormField(field_id="name", field_type=FieldType.TEXT, label={"en": "Name"}, placeholder={"en": "ph"}, default="x", description={"en": "fd"}),
            FormField(field_id="ro", field_type=FieldType.NUMBER, label={"en": "RO"}, read_only=True),
            FormSubsection(subsection_id="s1a", title={"en": "Sub"}, fields=[
                FormField(field_id="tags", field_type=FieldType.MULTI_SELECT, label={"en": "Tags"},
                          options=[{"value": "a", "label": "A"}, {"value": "b", "label": "B", "disabled": True}])])]),
        FormSection(section_id="s2", title={"en": "Two"}, fields=[
            FormField(field_id="color", field_type=FieldType.SELECT, label={"en": "Color"}, options=[{"value": "r", "label": "Red"}])]),
    ])


async def _roundtrip(form):
    rendered = await JsonSchemaRenderer().render(form)
    return JsonSchemaExtractor().extract(rendered.content, form_id=form.form_id)


async def test_section_tree_rebuilt(form):
    back = await _roundtrip(form)
    assert [s.section_id for s in back.sections] == ["s1", "s2"]
    s1 = back.sections[0]
    assert str(s1.title) and [getattr(i, "field_id", getattr(i, "subsection_id", None)) for i in s1.fields] == ["name", "ro", "s1a"]
    sub = s1.fields[2]
    assert isinstance(sub, FormSubsection) and [f.field_id for f in sub.fields] == ["tags"]


async def test_field_attributes_recovered(form):
    back = {f.field_id: f for f in (await _roundtrip(form)).iter_fields_recursive()}
    # FILL IN: name.placeholder == "ph"/{"en":"ph"} per LocalizedString shape, name.default == "x", name.description set,
    #          ro.read_only is True, color.options labels == ["Red"], tags.field_type is MULTI_SELECT with 2 options and
    #          options[1].disabled is True — bounded by AC8


async def test_section_depends_on_roundtrips():
    # FILL IN: a form whose section has depends_on=DependencyRule(...) → extracted section.depends_on equal — bounded by AC8
    pass


def test_pydantic_input_keeps_single_fields_section():
    from pydantic import BaseModel

    class M(BaseModel):
        a: str
        b: int = 1

    back = JsonSchemaExtractor().extract(M.model_json_schema())
    assert [s.section_id for s in back.sections] == ["fields"] and [f.field_id for f in back.iter_all_fields()] == ["a", "b"]
```
**Why this shape**: the fixture covers every `x-*` extension S4 listed; the Pydantic test is the AC8 "unchanged legacy" guard.

### FILL IN checklist
- [ ] `jsonschema.py::_group_sections` — subsection creation/append; bounded by `core/schema.py:153`.
- [ ] `jsonschema.py::_property_to_field` — add `placeholder=`/`read_only=` to the final `return FormField(` (ambiguous anchor, 2 occurrences); bounded by AC8.
- [ ] `test_jsonschema_sections.py` — attribute + depends_on assertions; bounded by AC8.

---

## Acceptance Criteria

- [ ] Renderer → extractor rebuilds sections, subsections, section/subsection `depends_on`, `placeholder`, `read_only`, `default`, `description`, labelled/disabled options for single and array-typed properties (AC8).
- [ ] Pydantic/OpenAPI input still yields one `"fields"` section; existing extractor tests pass.
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/extractors/test_jsonschema_sections.py -v`; `ruff check` clean.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/extractors/test_jsonschema_sections.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/extractors/test_extractor_roundtrip.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/extractors/test_jsonschema_rest.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_extractors.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug a2ui-dialect-formbuilder --feature-id FEAT-650`)
2. **Read the spec** §3 M4, §9 S4, and `renderers/jsonschema.py:397-470, 560-625` (what is emitted)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — `grep -n 'fields: list\[FormField\] = \[\]\|form = FormSchema(\|# Handle enum\|return FormField($' packages/parrot-formdesigner/src/parrot_formdesigner/extractors/jsonschema.py`
5. **Update status** in the per-spec index → `"in-progress"`, commit only the index
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** with `PYTHONPATH=packages/parrot-formdesigner/src` + Validation Commands
8. **Commit the code** — only the two files
9. **Close** with `scripts/sdd/close_task.sh TASK-4198 a2ui-dialect-formbuilder verified`
10. **Fill in the Completion Note**, commit the staged SDD state

---

## Completion Note

Implemented by codex gpt-5.6-luna; merged by sdd-worker orchestrator; merge-tier validation green (2132 passed, 14 skipped).

**Completed by**: sdd-worker orchestrator
**Date**: 2026-10-24
**Notes**: JSON Schema extractor section tree + x-* fidelity.

**Deviations from spec**: none
