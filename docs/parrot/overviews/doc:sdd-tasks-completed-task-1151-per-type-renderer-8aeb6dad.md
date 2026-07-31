---
type: Wiki Overview
title: 'TASK-1151: Per-Type Renderer Implementations (New Field Types)'
id: doc:sdd-tasks-completed-task-1151-per-type-renderer-implementations-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 2, Module 13. Registers one `FieldRenderer` callable per new `FieldType`
---

# TASK-1151: Per-Type Renderer Implementations (New Field Types)

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-1140, TASK-1141, TASK-1142, TASK-1143, TASK-1144, TASK-1145, TASK-1146, TASK-1147
**Assigned-to**: unassigned

---

## Context

Phase 2, Module 13. Registers one `FieldRenderer` callable per new `FieldType`
per renderer. For unsupported (FieldType, renderer) pairs, registers `FallbackRenderer`
which emits degraded content AND appends a `RenderWarning` to `RenderedForm.warnings`.

This task ALSO updates `_INLINE_FIELD_TYPES` and `_WEBAPP_FIELD_TYPES` in the
Telegram renderer to classify all 10 new types.

---

## Scope

For each new FieldType (`SIGNATURE`, `DYNAMIC_SELECT`, `TRANSFER_LIST`,
`REMOTE_RESPONSE`, `AVAILABILITY`, `LOCATION`, `TAGS`, `NPS`, `LIKERT`, `RANKING`):

- Register native renderer in each renderer that supports it natively
- Register renderer-specific `FallbackRenderer` subclass for unsupported pairs
- Fallback MUST append `RenderWarning` to `RenderedForm.warnings`
- Update Telegram `_INLINE_FIELD_TYPES` / `_WEBAPP_FIELD_TYPES` sets

Coverage matrix (from spec §3 Module 13):

| FieldType | JSON Schema | HTML5 | Adaptive Card | PDF | XForms | Telegram |
|---|---|---|---|---|---|---|
| `SIGNATURE` | native | native | fallback | fallback | fallback | WebApp |
| `DYNAMIC_SELECT` | native | native | native | fallback | `<xf:select1>` | inline/WebApp |
| `TRANSFER_LIST` | native | native | multi-choice | fallback | `<xf:select>` | WebApp |
| `REMOTE_RESPONSE` | native | native (read-only) | fallback | fallback | fallback | WebApp |
| `AVAILABILITY` | native | native | fallback | fallback | fallback | WebApp |
| `LOCATION` | native | native | choice list | as text | `<xf:select1>` | inline |
| `TAGS` | native | native | as text | as text | `<xf:input>` | WebApp |
| `NPS` | native | native | native | numeric input | `<xf:range>` | inline |
| `LIKERT` | native | native | choice set | numeric input | `<xf:select1>` | inline |
| `RANKING` | native | native | numeric input | numeric input | `<xf:range>` | inline |

**NOT in scope**: Existing 20 FieldType values (done in Phase 1), validator
branches (TASK-1150), extractor reverse-mappings (TASK-1152).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | MODIFY | Register 10 new type renderers |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` | MODIFY | Register 10 new type renderers |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py` | MODIFY | Register 10 new type renderers |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py` | MODIFY | Register 10 new type renderers |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` | MODIFY | Register 10 new type renderers |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/telegram/renderer.py` | MODIFY | Register 10 new type renderers + update sets |
| `packages/parrot-formdesigner/tests/unit/test_renderers.py` | MODIFY | Add coverage matrix and fallback warning tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (after prior tasks)
```python
# After TASK-1139:
from parrot_formdesigner.renderers.base import FieldRenderer, FallbackRenderer

# After TASK-1146:
from parrot_formdesigner.core.schema import RenderedForm, RenderWarning

# After TASK-1147:
from parrot_formdesigner.core.types import FieldType
# Now includes: SIGNATURE, DYNAMIC_SELECT, TRANSFER_LIST, REMOTE_RESPONSE,
# AVAILABILITY, LOCATION, TAGS, NPS, LIKERT, RANKING
```

### Fallback Pattern (MUST follow this for warning emission)
```python
class _PdfSignatureFallback(FallbackRenderer):
    async def render(self, field, *, locale="en", prefilled=None, error=None):
        # Return degraded content appropriate for PDF
        return {"type": "empty_box", "label": field.label}
    # The renderer (not this class) appends the RenderWarning to RenderedForm.warnings

# In PdfRenderer._build_registry():
self._registry[FieldType.SIGNATURE] = _PdfSignatureFallback()
```

Warning emission happens in the renderer's dispatch loop:
```python
renderer_fn = self._registry.get(field.field_type, self._fallback)
field_output = await renderer_fn.render(field, locale=locale, ...)
if isinstance(renderer_fn, FallbackRenderer):
    warnings.append(RenderWarning(
        field_id=field.field_id,
        field_type=field.field_type.value,
        renderer="pdf",  # use the renderer's name constant
        reason=f"unsupported {field.field_type.value} in pdf — rendered as placeholder",
    ))
```

### Does NOT Exist
- ~~`AuthContext` in renderer calls~~ — Phase 3; do NOT add auth_context kwarg yet
- ~~`OptionsLoader`~~ — Phase 3; DYNAMIC_SELECT renders with empty options placeholder

---

## Implementation Notes

### HTML5 Native Renderers for New Types
- **SIGNATURE**: `<canvas>` element + hidden inputs for `svg` and `png` values
- **DYNAMIC_SELECT**: `<select>` with `data-source` attribute (JS populates at runtime)
- **TRANSFER_LIST**: dual `<select multiple>` pattern
- **REMOTE_RESPONSE**: read-only `<div>` showing placeholder text
- **AVAILABILITY**: date range picker UI (simplified; full JS is frontend concern)
- **LOCATION**: `<select>` populated from pycountry data
- **TAGS**: `<input type="text">` with `data-tags="true"` attribute
- **NPS**: radio group 0–10
- **LIKERT**: radio group scale_min..scale_max
- **RANKING**: range input or radio group

### JSON Schema Native Renderers
All 10 types must have native JSON Schema representations using `format` keywords:
```python
{FieldType.SIGNATURE: lambda f, **kw: {"type": "object", "format": "signature", ...}}
{FieldType.NPS: lambda f, **kw: {"type": "integer", "format": "nps", "minimum": 0, "maximum": 10}}
```

### Telegram Classification for New Types
Update `_INLINE_FIELD_TYPES` and `_WEBAPP_FIELD_TYPES`:
```python
# Add to _INLINE_FIELD_TYPES:
FieldType.NPS, FieldType.LIKERT, FieldType.RANKING, FieldType.LOCATION,
FieldType.DYNAMIC_SELECT,

# Add to _WEBAPP_FIELD_TYPES:
FieldType.SIGNATURE, FieldType.TRANSFER_LIST, FieldType.REMOTE_RESPONSE,
FieldType.AVAILABILITY, FieldType.TAGS,
```

---

## Acceptance Criteria

- [ ] All 10 new types have registered renderers in all 6 renderers
- [ ] Fallback renderers emit `RenderWarning` appended to `RenderedForm.warnings`
- [ ] Native renderers produce non-None output
- [ ] `test_renderer_fallback_emits_warning` passes (PDF SIGNATURE → warning)
- [ ] `test_renderer_coverage_matrix` passes (all 60 pairs produce output)
- [ ] Telegram `_INLINE_FIELD_TYPES` and `_WEBAPP_FIELD_TYPES` updated
- [ ] All existing Phase 1 registry tests still pass
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_renderer_fallback_emits_warning():
    """PDF rendering of SIGNATURE produces placeholder + appends RenderWarning."""
    from parrot_formdesigner.renderers.pdf import PdfRenderer
    from parrot_formdesigner.core.schema import RenderWarning
    renderer = PdfRenderer()
    sig_field = FormField(
        field_id="sig1", field_type=FieldType.SIGNATURE, label="Signature"
    )
    form = FormSchema(
        form_id="t", title="T",
        sections=[FormSection(section_id="s", fields=[sig_field])]
    )
    result = await renderer.render(form)
    assert len(result.warnings) >= 1
    w = result.warnings[0]
    assert w.field_type == "signature"
    assert w.renderer == "pdf"
    assert "placeholder" in w.reason.lower() or "unsupported" in w.reason.lower()


@pytest.mark.asyncio
async def test_renderer_coverage_matrix():
    """Each (FieldType, renderer) pair produces native output or a warning. No silent None."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
    new_types = [
        FieldType.SIGNATURE, FieldType.DYNAMIC_SELECT, FieldType.TRANSFER_LIST,
        FieldType.REMOTE_RESPONSE, FieldType.AVAILABILITY, FieldType.LOCATION,
        FieldType.TAGS, FieldType.NPS, FieldType.LIKERT, FieldType.RANKING,
    ]
    for renderer in [HTML5Renderer(), JsonSchemaRenderer()]:
        for ft in new_types:
            field = FormField(field_id="f1", field_type=ft, label="Test")
            form = FormSchema(
                form_id="t", title="T",
                sections=[FormSection(section_id="s", fields=[field])]
            )
            result = await renderer.render(form)
            assert result is not None, f"{renderer.__class__.__name__} returned None for {ft}"
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
