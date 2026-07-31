# TASK-2005: Renderers — data-field-uid attributes + RenderWarning.field_uid

**Feature**: FEAT-393 — Stable UUID-Based Field Identity (field_uid)
**Spec**: `sdd/specs/formdesigner-field-uid.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1996
**Assigned-to**: unassigned

---

## Context

Implements Module 11 of FEAT-393 (spec §3, blueprint §9). Renderers expose
the UID as a data attribute for designer tooling; fallback warnings carry
both identifiers. Control names/ids stay `field_id` — zero change for form
fillers.

---

## Scope

- `renderers/html5.py`: emit `data-field-uid="{uid}"` next to the existing
  `data-field-id` (:1089), HTML-escaped.
- `renderers/fields/audio.py`: add `data-field-uid` alongside existing attrs
  (:88 region).
- All `RenderWarning(...)` emissions gain `field_uid=field.field_uid`:
  `html5.py:337-345`, `adaptive_card.py:209-219`, `pdf.py:452-459`.
- NOTHING else changes: control `id`/`name`, AcroForm widget names,
  JSON-Schema property keys, XForms element names, Telegram callback
  encoding, derived composite names — all stay `field_id`-based.
- Renderer snapshot/assertion tests updated; spec §4 Module 11 tests.

**NOT in scope**: audio manifest models (TASK-2004); any renderer output-name
changes (explicit non-goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | MODIFY | data-field-uid; RenderWarning |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/fields/audio.py` | MODIFY | data-field-uid |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` | MODIFY | RenderWarning |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py` | MODIFY | RenderWarning |
| `packages/parrot-formdesigner/tests/unit/renderers/` | MODIFY | attr + warning assertions |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.schema import RenderWarning  # field_uid added by TASK-1996
```

### Existing Signatures to Use
```python
# renderers/html5.py — control emission: id/name (:805-806, :921-922, :974-975, :1299-1300,
#   :1344-1345, :1373-1374, :1413-1414); data-field-id (:1089); escaping via
#   html.escape(..., quote=True) (:1508); RenderWarning emission FORMULA-only (:337-345)
# renderers/adaptive_card.py — RenderWarning (:209-219); input "id": field.field_id (:687)
# renderers/pdf.py — RenderWarning (:452-459); AcroForm widget name=field.field_id (13 sites)
# renderers/fields/audio.py — field_id = html.escape(field.field_id, quote=True) (:88);
#   11 derived DOM ids + JS literals (:92-156)
# core/schema.py — RenderWarning (:376-390); RenderedForm.warnings (:410)
```

### Does NOT Exist
- ~~`data-field-uid` anywhere today~~ — created HERE
- ~~RenderWarning emissions in jsonschema/xforms/telegram renderers~~ — only html5/adaptive_card/pdf emit warnings; do not add new emission sites
- ~~a FallbackRenderer class~~ — prose-only concept

---

## Implementation Notes

### Pattern to Follow
Spec §9 "Module 11" blueprint:
```python
f'data-field-uid="{html.escape(str(field.field_uid), quote=True)}"'
```

### Key Constraints
- UUIDs contain no HTML-hostile chars, but escape anyway (consistency with
  :1508 policy).
- Do NOT touch derived composite names (`{field_id}_svg`, `__mime`, etc.) —
  they are data-binding surface.

---

## Acceptance Criteria

- [ ] HTML5 + audio field markup contains `data-field-uid`; control names unchanged
- [ ] RenderWarnings from html5/adaptive_card/pdf carry `field_uid`
- [ ] JSON-Schema/XForms/Telegram output byte-identical for a UID-less assertion (control surface untouched)
- [ ] `pytest packages/parrot-formdesigner/tests/unit/renderers/ -v` passes; `ruff check` clean

---

## Test Specification

```python
def test_html5_data_field_uid_attr(sample_form): ...
def test_html5_control_name_still_field_id(sample_form): ...
def test_render_warning_field_uid_html5(formula_form): ...
def test_render_warning_field_uid_pdf(signature_form): ...
def test_audio_template_data_field_uid(audio_field): ...
```

---

## Agent Instructions

1. **Read the spec** §9 Module 11; verify TASK-1996 completed.
2. **Verify the contract** anchors (html5.py is large; re-grep).
3. **Update status** in `sdd/tasks/index/formdesigner-field-uid.json` → `"in-progress"`.
4. **Implement**, run tests, verify acceptance criteria.
5. **Move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
