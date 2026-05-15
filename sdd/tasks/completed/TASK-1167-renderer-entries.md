# TASK-1167: Per-renderer registry entries for `FieldType.REST`

**Feature**: FEAT-170 — FormDesigner `FieldType.REST`
**Spec**: `sdd/specs/new-formdesigner-field-rest.spec.md` (Module 8)
**Status**: done
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1163, TASK-1164
**Assigned-to**: unassigned

---

## Context

Register `FieldType.REST` in each of the 6 renderers. Two native
(HTML5, JSON Schema); three fallbacks (PDF, XForms, Adaptive Card)
emitting `RenderWarning`; one redirect (Telegram WebApp).

**Important** — `RenderWarning` IS the correct type here: this is the
renderer layer (FEAT-167's design). The resolver-layer warnings
(`list[str]` on `RestFieldResult`) are a separate concept handled in
TASK-1162.

---

## Scope

For each renderer at
`packages/parrot-formdesigner/src/parrot_formdesigner/renderers/`:

- **`html5.py`** — native: emit a `<RestUploader>` markup block with
  hidden `<input>` for `answer` and `blob_ref`, a visible
  `<input type="file">` bound to the upload endpoint template, plus
  data attributes for spinner / retry hooks.
- **`jsonschema.py`** — native: object schema with
  `properties.answer` and `properties.blob_ref: {"type":["string","null"]}`,
  plus an `x-parrot-rest` extension dict carrying `mode`,
  `response_path`, `display_template`, and the upload URL template.
- **`adaptive_card.py`** — `FallbackRenderer` placeholder + warning.
- **`pdf.py`** — `FallbackRenderer` placeholder + warning.
- **`xforms.py`** — `FallbackRenderer` placeholder + warning.
- **`telegram/renderer.py`** — WebApp redirect entry (mirror the
  `SIGNATURE` / `TRANSFER_LIST` policy from FEAT-167).

Each renderer has a `_registry: dict[FieldType, Callable]`; add the
new entry there. Fallbacks MUST append
`RenderWarning(field_id=..., field_type="rest", renderer="<name>",
reason="<human-readable>")` to `RenderedForm.warnings`.

**NOT in scope**: building a real frontend `<RestUploader>` component
(separate-repo concern), changing the renderer base classes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | MODIFY | Native entry |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/jsonschema.py` | MODIFY | Native entry |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` | MODIFY | Fallback |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py` | MODIFY | Fallback |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py` | MODIFY | Fallback |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/telegram/renderer.py` | MODIFY | WebApp redirect |
| `packages/parrot-formdesigner/tests/unit/renderers/test_rest_*.py` | CREATE | One per renderer |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/renderers/base.py
class FieldRenderer(Protocol): ...
class FallbackRenderer: ...
# FEAT-167 introduced both — reuse, do not modify.

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py:194-207
class RenderWarning(BaseModel):
    field_id: str
    field_type: str            # "rest"
    renderer: str              # "html5" | "pdf" | "adaptive_card" | ...
    reason: str

class RenderedForm(BaseModel):
    content: Any; content_type: str
    style_output: Any | None = None
    metadata: dict[str, Any] | None = None
    warnings: list[RenderWarning] = []

# Each renderer exposes a private _registry dict keyed by FieldType.
# Locate it in each file (FEAT-167 added entries the same way) and
# append a new FieldType.REST entry.
```

### Does NOT Exist

- ~~A `FieldType.REST` entry in any renderer's `_registry`~~ — added.
- ~~A standalone `<RestUploader>` component file in this repo~~ —
  frontend is a separate repo (spec §1 Non-Goals).
- ~~A new fallback class~~ — reuse `FallbackRenderer`.

---

## Implementation Notes

### Pattern (HTML5 native)

```python
def _render_rest(field, ctx) -> str:
    spec = field.meta["rest"]
    upload_url = ctx.upload_url_template.format(
        form_id=ctx.form_id, field_id=field.field_id)
    return f'''
    <div class="parrot-rest-uploader" data-field-id="{field.field_id}"
         data-upload-url="{upload_url}">
        <input type="file" name="{field.field_id}_file"
               accept="{','.join(field.constraints.allowed_mime_types or [])}">
        <input type="hidden" name="{field.field_id}.answer">
        <input type="hidden" name="{field.field_id}.blob_ref">
        <span class="rest-status"></span>
    </div>'''

# Register: _registry[FieldType.REST] = _render_rest
```

### Pattern (JSON Schema native)

```python
def _schema_rest(field) -> dict:
    spec = field.meta["rest"]
    return {
        "type": "object",
        "properties": {
            "answer": {},  # heterogeneous
            "blob_ref": {"type": ["string", "null"]},
        },
        "required": ["answer"],
        "x-parrot-rest": {
            "mode": spec["mode"],
            "response_path": spec.get("response_path"),
            "display_template": spec.get("display_template"),
            "upload_url_template":
                "/api/v1/forms/{form_id}/fields/{field_id}/upload",
        },
    }
```

### Pattern (fallback)

```python
def _render_rest_fallback(field, ctx) -> str:
    ctx.warnings.append(RenderWarning(
        field_id=field.field_id, field_type="rest",
        renderer="<this_renderer_name>",
        reason="REST upload not supported in this renderer"))
    return "<placeholder>"
```

### Key constraints

- Renderer code stays HTML/PDF/etc.-pure — no aiohttp imports here.
- Telegram entry must NOT crash the chat flow; degrade gracefully.

---

## Acceptance Criteria

- [ ] HTML5 output includes `<input type="file">` + hidden `answer`/`blob_ref`.
- [ ] JSON Schema output includes `x-parrot-rest` with `mode`, etc.
- [ ] PDF / XForms / Adaptive Card outputs add a `RenderWarning(field_type="rest", renderer=...)`.
- [ ] Telegram emits a WebApp redirect entry (matches `SIGNATURE`).
- [ ] No FEAT-167 renderer tests regress.

---

## Test Specification

One test per renderer (6 files), e.g.:

```python
def test_html5_native_rest(rest_callback_field):
    out = HTML5Renderer().render(form_with(rest_callback_field))
    assert '<input type="file"' in out.content
    assert "blob_ref" in out.content

def test_pdf_fallback_warns(rest_callback_field):
    out = PdfRenderer().render(form_with(rest_callback_field))
    w = out.warnings[0]
    assert w.field_type == "rest" and w.renderer == "pdf"
```

---

## Completion Note

Added `FieldType.REST` to all 6 renderers:
- **html5.py**: `_RestUploaderRenderer` + `_render_rest()` (native: `<input type="file">` + hidden answer/blob_ref). 
- **jsonschema.py**: `_TYPE_MAP["rest"]="object"` + `x-parrot-rest` extension with mode/response_path/display_template/upload_url_template.
- **adaptive_card.py**: added to `_AC_FALLBACK_TYPES` → emits `RenderWarning(renderer="adaptive_card")`.
- **pdf.py**: added to `_PDF_FALLBACK_NEW_TYPES` → emits `RenderWarning(renderer="pdf")`.
- **xforms.py**: added `("input", "string")` fallback entry to `_XFORMS_TYPE_MAP`.
- **telegram/renderer.py**: added to `_WEBAPP_FIELD_TYPES` → WebApp redirect mode.
Created `tests/unit/renderers/test_rest_renderers.py` with 6 tests (all pass). 28 existing renderer tests pass (no regressions). Ruff: no new errors introduced. Committed on `feat-170-new-formdesigner-field-rest`.
