# TASK-2449: Other Renderers Update

**Feature**: FEAT-460 — Raw Upload Field Types
**Spec**: `sdd/specs/raw-upload-field-types.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2442
**Assigned-to**: unassigned

---

## Context

Five non-JSON-Schema renderers need FileEnvelope awareness so they can render
upload field values correctly when the value is a FileEnvelope dict instead of
a plain string. Implements **Module 8** from the spec.

---

## Scope

- Update **html5.py**: `<input type="file">` rendering unchanged for form display,
  but when rendering a submitted value, extract `filename` from FileEnvelope
  for display text. Add `accept` attribute from `constraints.allowed_mime_types`.
- Update **pdf.py**: When rendering a FILE/IMAGE value, if value is a FileEnvelope
  dict, show `filename` as fallback text instead of the raw string/URL.
- Update **xforms.py**: `upload` binding type preserved. If value is a FileEnvelope,
  extract `data_url` or `blob_ref` for the XForms value binding.
- Update **adaptive_card.py**: When rendering upload field values, show `filename`
  from FileEnvelope. For images, link to `thumbnail_url` if available.
- Update **telegram/renderer.py**: When rendering upload field results, display
  `filename` and `content_type` from FileEnvelope. For images, use `thumbnail_url`
  for inline preview.

Each renderer must handle BOTH legacy string values (backward compat) and
FileEnvelope dicts.

**NOT in scope**: JSON Schema renderer (TASK-2448), validators (TASK-2447),
controls/helpers (TASK-2450).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/html5.py` | MODIFY | Envelope-aware value rendering |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/pdf.py` | MODIFY | Envelope-aware fallback text |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/xforms.py` | MODIFY | Envelope-aware value binding |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/adaptive_card.py` | MODIFY | Envelope-aware display |
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/telegram/renderer.py` | MODIFY | Envelope-aware display |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_formdesigner.core.file_envelope import (
    FileEnvelope, UPLOAD_FIELD_TYPES,
)  # created by TASK-2442
from parrot_formdesigner.core.types import FieldType  # core/types.py:16
```

### Existing Signatures to Use
```python
# Each renderer has its own class and render method pattern.
# Read each file to identify the exact methods that handle
# FILE/IMAGE/IMAGE_DROPZONE/MULTI_UPLOAD before modifying.
# The implementing agent MUST grep/read the exact handling sites.
```

### Does NOT Exist
- ~~`BaseRenderer.render_file_envelope()`~~ — no such shared method
- ~~`renderers/base.py`~~ — there is no shared base renderer; each renderer is standalone
- ~~`renderers/utils.py`~~ — no shared renderer utilities

---

## Implementation Notes

### Value Detection Pattern
```python
# In each renderer, when handling upload field values:
def _extract_display_name(value: Any) -> str:
    """Extract display name from legacy or FileEnvelope value."""
    if isinstance(value, dict) and "filename" in value:
        return value["filename"]
    if isinstance(value, str):
        # Legacy: extract filename from URL or return as-is
        return value.rsplit("/", 1)[-1] if "/" in value else value
    return str(value)
```

### Key Constraints
- Each renderer is independent — changes are isolated per file
- All renderers MUST handle both legacy string and FileEnvelope dict values
- Do NOT break existing rendering of non-upload field types
- The Telegram renderer is in a subdirectory: `renderers/telegram/renderer.py`
- Keep changes minimal: only update the FILE/IMAGE/DROPZONE/MULTI_UPLOAD
  handling branches in each renderer
- Log warnings (not errors) if an unexpected value shape is encountered

### References in Codebase
- `renderers/html5.py` — HTML form rendering
- `renderers/pdf.py` — PDF generation
- `renderers/xforms.py` — XForms XML output
- `renderers/adaptive_card.py` — Microsoft Teams adaptive cards
- `renderers/telegram/renderer.py` — Telegram bot messages

---

## Acceptance Criteria

- [ ] html5 renderer handles FileEnvelope values for upload fields
- [ ] pdf renderer shows filename from FileEnvelope instead of raw URL
- [ ] xforms renderer extracts data_url/blob_ref from FileEnvelope
- [ ] adaptive_card renderer shows filename and thumbnail from FileEnvelope
- [ ] telegram renderer shows filename/content_type and thumbnail from FileEnvelope
- [ ] All renderers still handle legacy string values (no regression)
- [ ] No linting errors in modified files

---

## Test Specification

No dedicated test file — renderer changes are lightweight display-only updates.
Verified through integration tests in TASK-2451 and existing renderer test suites.
The implementing agent should run existing renderer tests to confirm no regression.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/raw-upload-field-types.spec.md` for full context
2. **Check dependencies** — verify TASK-2442 is completed
3. **Read each renderer file** — identify the exact methods handling upload field types
4. **Update status** in `sdd/tasks/index/raw-upload-field-types.json` → `"in-progress"`
5. **Implement** envelope-aware rendering in each file
6. **Run existing renderer tests** to verify no regression
7. **Move this file** to `sdd/tasks/completed/TASK-2449-other-renderers.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-25
**Notes**: Implemented envelope-aware value display for 3 of the 5 listed
renderers (html5.py, pdf.py, adaptive_card.py), where a live value-rendering
code path actually exists:
- **html5.py**: `_render_input` for FILE/IMAGE no longer emits an invalid
  `value=` attribute (browsers ignore/reject it on `type="file"` inputs
  anyway); instead emits `data-filename="..."` (via a new
  `_extract_display_name()` helper) and an `accept="..."` attribute derived
  from `constraints.allowed_mime_types`.
- **pdf.py**: the module-level `prefilled_value` computation now branches
  on `UPLOAD_FIELD_TYPES` (from `core.file_envelope`) to show the extracted
  filename instead of the raw dict repr as AcroForm placeholder-textfield
  fallback text.
- **adaptive_card.py**: added an explicit `elif ft in UPLOAD_FIELD_TYPES`
  branch in `_build_input_element` (before the generic fallback) showing
  the filename, and — for images — appending `thumbnail_url` to the
  displayed text when present.
- Manually verified end-to-end (see session transcript): HTML5 emits
  `data-filename`/`accept`, PDF renders without error, Adaptive Card shows
  `"photo.jpg (temp://thumb)"` for an image envelope with a thumbnail.
- Full regression sweep: `tests/unit/renderers/` + `test_renderers.py` =
  136 passed, 0 failed. No new ruff findings (21 pre-existing in these 3
  files, confirmed identical via `git stash`).

**Deviations from spec**: **xforms.py and telegram/renderer.py were left
UNCHANGED** after investigation. Both renderers structurally ignore
submitted values by design, not incidentally:
- `XFormsRenderer.render()`'s own docstring states it "ignores style /
  prefilled / errors parameters (HTML-only concerns)" — there is no value
  binding code path to make envelope-aware. The FILE/IMAGE `mediatype`
  hints (`image/*` / `*/*`) and the `("upload", "anyURI")` binding-type
  mapping were already correct and are unchanged, satisfying "upload
  binding type preserved" literally.
- `TelegramRenderer.render()` accepts a `prefilled` parameter but never
  reads it anywhere in the method body (dead parameter, same posture as
  xforms) — INLINE mode builds keyboards from field *structure*
  (options/labels), WEBAPP mode returns only a URL. No function anywhere
  in `renderers/telegram/` formats a field's *value* into displayed text,
  so there is no "upload field result" display site to update.

Implementing a new value-rendering feature in either file to give myself
something to change would be scope creep beyond "lightweight display-only
updates" (the task's own Test Specification note) and would add
disconnected, untested code. Flagging this for spec/PR review — if a
result-summary/confirmation-message feature is later added to either
renderer, it should incorporate `_extract_display_name`-equivalent logic
then.
