# TASK-4231: Expose FormField.hint in HTML5, JSON Schema, Adaptive Card, A2UI and PDF renderers

**Feature**: FEAT-649 — Audio Form Interaction Workflow
**Spec**: `sdd/specs/audio-form-interaction-workflow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4209
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 13 / AC4 / S9: `FormField.hint` (added by TASK-4209) is a schema-wide contract — narrated
after a pause on audio, and **shown as help text by every visual renderer**. This task wires `hint` into the
five non-audio renderers. Audio narration of the hint is TASK-4232 / TASK-4214.

---

## Scope

- HTML5: render `<small class="hint …">` below the input, once per field, for every field type.
- JSON Schema: emit `"x-hint"` on the field property.
- Adaptive Card: subtle `TextBlock` (`isSubtle: true`) between the description block and the input.
- A2UI: a sibling `Text` component `f-<field_id>-hint` (metadata `parrot_role="hint"`) after the control.
- PDF: an italic line below the label.
- `hint` is a `LocalizedString`; resolve with each renderer's own `_resolve` / `_localize` helper.
- HTML-escape the hint in HTML5 (`html.escape`) — it is author text.
- Tests for all five renderers.

**NOT in scope**: audio renderer / narration (TASK-4232, TASK-4214); `prefilled` reading through
`unwrap_voice()` (spec Integration Points mentions it, but it is not assigned to this task by the plan —
see Completion Note if you find a renderer that breaks on an envelope value); XForms / Teams / Telegram
renderers; adding `hint` to the model (TASK-4209).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | MODIFY | `<small class="hint">` per field |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` | MODIFY | `x-hint` on the field property |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` | MODIFY | subtle TextBlock |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py` | MODIFY | `Text` hint sibling |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py` | MODIFY | italic hint line |
| `packages/parrot-formdesigner/tests/formdesigner/test_renderers_expose_hint.py` | CREATE | tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection      # core/schema.py:65, :401, :229
from parrot_formdesigner.core.types import FieldType                                # core/types.py:16
from parrot_formdesigner.renderers.html5 import HTML5Renderer                       # renderers/html5.py:131
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer             # renderers/jsonschema.py:301
from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer        # renderers/adaptive_card.py:121 (module imports parrot.outputs.cards.spec :23 → importorskip in tests)
from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer                     # renderers/a2ui.py:294 (needs parrot.outputs.a2ui → importorskip)
from parrot_formdesigner.renderers.pdf import PdfRenderer                           # renderers/pdf.py:115
from pypdf import PdfReader                                                         # used tests/unit/renderers/test_pdf.py:8
import html                                                                         # already imported renderers/html5.py:9
```
Provided by dependency tasks:
- `FormField.hint: LocalizedString | None = None` — TASK-4209 (core/schema.py, inserted below `answer_envelope` :143).

### Existing Signatures to Use
```python
# every renderer — renderers/base.py:68
async def render(self, form: FormSchema, style: StyleSchema | None = None, *, locale: str = "en",
                 prefilled: dict[str, Any] | None = None, errors: dict[str, str] | None = None) -> RenderedForm

# renderers/html5.py
def _resolve(value: LocalizedString | None, locale: str = "en") -> str             # :107
def _render_field(self, field, prefilled, errors, style, locale) -> str            # :689-955 ; description :714 ; per-branch help span ×~20 ; tail `if error:` :951 ; parts.append("</div>") :954
# renderers/jsonschema.py
def _resolve(value, locale="en") -> str                                             # :277
def _field_to_property(self, field, locale, prefilled) -> dict                      # description set :502-503
# renderers/adaptive_card.py
def _resolve(value, locale="en") -> str                                             # :45
def _build_field(...)                                                               # :696 ; description block :733-744 ; "# Input element" :746
# renderers/a2ui.py
def _resolve(value, locale="en") -> str                                             # :48
def _extensions(m, **values) -> ComponentMetadata                                   # :281
def _lower_field(self, field, section, subsection, locale, errors) -> tuple[list[Any], RenderWarning | None]   # :606 ; components = [m.Component(**kwargs)] :702 ; error sibling :704
# _lower_one uses field_components[0].id for degraded entries (:562) → the hint MUST NOT be components[0]
# renderers/pdf.py
def _localize(value: LocalizedString | None, locale: str, default: str = "") -> str  # :99
def _render_field(self, c, section_id, field, cursor_y, locale, prefilled, unsupported, render_warnings=None) -> float   # :325 ; label draw :346-348
LINE_HEIGHT = 6 * mm                                                                 # :133
```

### Does NOT Exist
- ~~`FormField.hint`~~ before TASK-4209 lands; ~~`FormField.audio_hint`~~; ~~`meta["audio_hint"]`~~.
- ~~A field-level description in the A2UI renderer~~ — `_lower_field` emits none today (the spec's `a2ui.py:385` anchor is the FORM description, not a field site).
- ~~`adaptive_card.py:225`~~ as a field site — it is the form description (field site is `:733`).
- ~~A shared help-text helper in html5.py~~ — each branch appends its own `form-field__help` span.
- ~~`renderers/pdf.py` description rendering~~ — PDF draws no description today.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py", "action": "MODIFY"},
    {"path": "packages/parrot-formdesigner/tests/formdesigner/test_renderers_expose_hint.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py#HTML5Renderer._render_field",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py#JsonSchemaRenderer._field_to_property",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py#AdaptiveCardRenderer._build_field",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/a2ui.py#A2UIFormRenderer._lower_field",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py#PdfRenderer._render_field",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py#FormField"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Hint absent → output byte-identical to today (existing renderer tests must stay green).
- HTML5: one insertion point at the tail (before the error span) covers every branch — do NOT edit the ~20
  per-branch description spans.
- A2UI: the hint `Text` must be appended AFTER the control so `components[0]` stays the control; it is
  added for natively-lowered fields only (not for `hidden`; for `notice` degrade, append too — FILL IN).
- `getattr(field, "hint", None)` is NOT needed once TASK-4209 has landed — use `field.hint` directly.

---

## Implementation Blueprint

### Steps (in order)
1. HTML5 tail insertion — *why*: one site covers every field-type branch.
2. JSON Schema `x-hint` next to `description` — *why*: JSON Schema consumers already read `x-*` extensions.
3. Adaptive Card subtle block before the input — *why*: mirrors how description is shown.
4. A2UI `Text` sibling after the control — *why*: keeps `components[0]` the control for degrade bookkeeping.
5. PDF italic line after the label — *why*: PDF has no description slot; hint goes under the label.
6. Write the tests and run them plus the existing renderer suites.

### `renderers/html5.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if error:' packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py)
# BEFORE — insert above `        if error:` (verified: renderers/html5.py:951)
        hint = _resolve(field.hint, locale) if field.hint else None
        if hint:
            parts.append(f'<small class="hint form-field__hint text-xs text-gray-500 mt-1 block">{html.escape(hint)}</small>')

```
**Why**: `_render_field` already ends every branch at this point; escaping prevents author-text injection.

### `renderers/jsonschema.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            prop\["description"\] = _resolve(field.description, locale)' renderers/jsonschema.py)
# AFTER — insert below `            prop["description"] = _resolve(field.description, locale)` (verified: renderers/jsonschema.py:503)
        if field.hint:
            prop["x-hint"] = _resolve(field.hint, locale)
```

### `renderers/adaptive_card.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        # Input element' renderers/adaptive_card.py)
# BEFORE — insert above `        # Input element` (verified: renderers/adaptive_card.py:746)
        # Hint (FEAT-649)
        if field.hint:
            elements.append(
                {
                    "type": "TextBlock",
                    "text": _resolve(field.hint, locale),
                    "isSubtle": True,
                    "size": "Small",
                    "wrap": True,
                    "spacing": "None",
                }
            )

```

### `renderers/a2ui.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        components = \[m.Component(\*\*kwargs)\]' renderers/a2ui.py)
# AFTER — insert below `        components = [m.Component(**kwargs)]` (verified: renderers/a2ui.py:702)
        if field.hint:
            components.append(
                m.Component(
                    id=f"f-{field.field_id}-hint",
                    component="Text",
                    text=_resolve(field.hint, locale),
                    metadata=_extensions(m, parrot_role="hint", parrot_field_id=field.field_id),
                )
            )
# FILL IN: decide whether the `notice` degrade branch (:647-668) also appends the hint — bounded by
#   "components[0] stays the notice" and by test_a2ui_field_lowering.py staying green.
```
**Why**: `_lower_one` (`:555-571`) extends the section body with every returned component id, so the hint
renders under the control without touching the section layout code.

### `renderers/pdf.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        c.drawString(self.MARGIN_X, cursor_y, label)' renderers/pdf.py)
# AFTER — insert below the two lines (verified: renderers/pdf.py:347-348):
#        c.drawString(self.MARGIN_X, cursor_y, label)
#        cursor_y -= self.FIELD_HEIGHT
        hint = _localize(field.hint, locale) if field.hint else ""
        if hint:
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(self.MARGIN_X, cursor_y, hint)
            c.setFont("Helvetica", 10)
            cursor_y -= self.LINE_HEIGHT
# FILL IN: page-overflow — call self._maybe_new_page(c, cursor_y, …) if the hint pushes past the margin —
#   bounded by _maybe_new_page(:249) semantics and test_pdf.py staying green.
```

### `tests/formdesigner/test_renderers_expose_hint.py` (CREATE)
See Test Specification.

### FILL IN checklist
- [ ] `a2ui.py::_lower_field` — notice-branch hint; bounded by components[0] invariant.
- [ ] `pdf.py::_render_field` — page overflow for the hint line.
- [ ] Test bodies for Adaptive Card and A2UI (importorskip).

---

## Acceptance Criteria

- [ ] AC4: `hint` rendered by HTML5 (`<small class="hint`), JSON Schema (`x-hint`), Adaptive Card (subtle TextBlock), A2UI (`Text` with `parrot_role="hint"`) and PDF (text line).
- [ ] Fields without `hint` render exactly as before (existing renderer tests pass).
- [ ] HTML5 hint is escaped.
- [ ] `ruff check` passes on the five renderer files.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_renderers_expose_hint.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/renderers/test_pdf.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/renderers/test_a2ui_field_lowering.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/renderers/test_rest_jsonschema.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/renderers/test_rest_html5.py -q`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/formdesigner/test_renderers_expose_hint.py
from __future__ import annotations

from io import BytesIO

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.renderers.pdf import PdfRenderer


def _form(hint=None) -> FormSchema:
    field = FormField(field_id="name", field_type=FieldType.TEXT, label="Name", hint=hint)
    return FormSchema(form_id="demo", title="Demo", tenant="acme", sections=[FormSection(section_id="s", fields=[field])])


async def test_html5_hint_small_escaped():
    out = await HTML5Renderer().render(_form("Say <b>first</b> name"))
    assert '<small class="hint' in out.content
    assert "&lt;b&gt;" in out.content


async def test_html5_no_hint_unchanged():
    out = await HTML5Renderer().render(_form())
    assert 'class="hint' not in out.content


async def test_jsonschema_x_hint_localized():
    out = await JsonSchemaRenderer().render(_form({"en": "First name", "es": "Nombre"}), locale="es")
    # FILL IN: locate the "name" property in out.content (follow test_rest_jsonschema.py) and assert x-hint == "Nombre"


async def test_adaptive_card_subtle_hint():
    pytest.importorskip("parrot.outputs.cards.spec")
    from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer
    # FILL IN: render; assert a TextBlock with isSubtle True and text == hint exists


async def test_a2ui_hint_text_component():
    pytest.importorskip("parrot.outputs.a2ui")
    from parrot_formdesigner.renderers.a2ui import A2UIFormRenderer
    # FILL IN: render; components = content["createSurface"]["components"]; assert "f-name-hint" present and
    #   the control "f-name" precedes it


async def test_pdf_hint_line():
    from pypdf import PdfReader
    out = await PdfRenderer().render(_form("Use capitals"))
    text = "".join(page.extract_text() or "" for page in PdfReader(BytesIO(out.content)).pages)
    assert "Use capitals" in text
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug audio-form-interaction-workflow --feature-id FEAT-649`)
2. **Read the spec** (§3 Module 13, AC4, §9 S9).
3. **Check dependencies** — TASK-4209 must be `"done"` in `sdd/tasks/index/audio-form-interaction-workflow.json`.
4. **Verify the Codebase Contract** — re-run each `grep -c` anchor; if a count moved, re-locate and fix the blueprint first.
5. **Update status** → `"in-progress"` (set `started_at`), commit only the index file.
6. **Implement** from the blueprint; complete every `# FILL IN:`.
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/parrot-formdesigner/src`.
8. **Commit the code** — only the files listed.
9. **Close the task**: `scripts/sdd/close_task.sh TASK-4231 audio-form-interaction-workflow verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
