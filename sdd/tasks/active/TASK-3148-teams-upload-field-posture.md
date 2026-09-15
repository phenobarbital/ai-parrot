# TASK-3148: Teams upload-field posture — `Action.OpenUrl` to the web form + `RenderWarning`

**Feature**: FEAT-551 — MS Teams FormDesigner Renderer (Adaptive Card + submit envelope via the Teams bot)
**Spec**: `sdd/specs/msteams-formdesigner-renderer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3147
**Assigned-to**: unassigned
**Parallel**: true — touches only `renderers/teams.py` + its test file; TASK-3149/3150 touch different files (they may run in a sibling worktree once TASK-3147 has landed).

---

## Context

Spec §3 Module 2. Microsoft: *"Adaptive Cards within Teams don't provide support for file or image
uploads"* (spec F020); no in-card upload path exists in the repo. The Teams card must therefore
degrade upload fields **explicitly**: an instruction text + an `Action.OpenUrl` to the served web
form page (`GET {ui}/{tenant}/forms/{form_uid}`, `ui/routes.py:191-193`) and a `RenderWarning`
(`renderer="teams"`) — never today's silent `Input.Text`. The default `adaptive` renderer keeps
its fallback (TASK-3146 hook default) so its golden test stays green.

---

## Scope

- In `TeamsFormRenderer`, override `_build_upload_element(field, value, locale)` → a `Container` with an instruction `TextBlock` and an `ActionSet` holding one `Action.OpenUrl` to `form_url`; no `Input.*` for the field.
- Add `UPLOAD_NOTICE_TEXT: dict[str, str]` (`en`, `es`) and `_upload_warnings(form) -> list[RenderWarning]` walking sections and subsections; `render()` extends `result.warnings` with them.
- Tests for top-level and nested (subsection) upload fields, all four upload types, and `adaptive` unaffected.

**NOT in scope**: bot-side attachment intake (follow-up); changes to `_AC_FALLBACK_TYPES`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py` | MODIFY | override + warnings |
| `packages/parrot-formdesigner/tests/unit/test_teams_renderer.py` | MODIFY | upload posture tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ..core.file_envelope import UPLOAD_FIELD_TYPES                    # file_envelope.py:44-51 = {FILE, IMAGE, IMAGE_DROPZONE, MULTI_UPLOAD}
from ..core.schema import FormField, FormSchema, FormSection, FormSubsection, RenderedForm, RenderWarning  # schema.py:65, :401, :229, :195, :671, :650
from .adaptive_card import AdaptiveCardRenderer, _resolve              # adaptive_card.py:121, :45
```

### Existing Signatures to Use
```python
# renderers/teams.py (TASK-3147)
class TeamsFormRenderer(AdaptiveCardRenderer): RENDERER_NAME = "teams"; build_envelope(form, tenant) -> TeamsSubmitEnvelope (has .form_url: HttpUrl); render(..., tenant=None); self._current_tenant
# renderers/adaptive_card.py (TASK-3146 hook)
def _build_upload_element(self, field: FormField, value: Any, locale: str) -> dict[str, Any] | None
# core/schema.py
class FormSubsection(BaseModel): subsection_id: str (218); title (219); fields: list[FormField] (221)
class FormSection(BaseModel):    section_id: str (251); fields: list[SectionItem] (254)   # SectionItem = FormField | FormSubsection
class RenderWarning(BaseModel):  field_id: str; field_uid: uuid.UUID | None; field_type: str; renderer: str; reason: str   # 664-668
# adaptive_card.py — how the base walks a section (pattern for _upload_warnings)
def _build_section_body(...)  # 595-643: `for item in section.fields:` → FormSubsection → _build_subsection, else _build_field
```

### Does NOT Exist
- ~~`Input.File`~~ — not an Adaptive Card element supported by Teams.
- ~~a dedicated upload page~~ — the target is the served form page `GET {ui_bp}/{tenant}/forms/{form_uid}` (`ui/routes.py:191-193`); `TeamsFormRenderer.build_envelope(...).form_url` already composes it (TASK-3147).
- ~~`RenderWarning.severity`~~ — no such field; use `reason`.
- ~~`ActionSet` in `parrot.outputs.cards`~~ — the typed models have no ActionSet; emit the raw dict `{"type": "ActionSet", "actions": [...]}` (AC 1.2+ element, fine for 1.4).

---

## Implementation Notes

### Pattern to Follow
```python
# adaptive_card.py:595-643 — walk sections and subsections
for item in section.fields:
    if isinstance(item, FormSubsection): ...items in item.fields...
    else: ...item is a FormField...
```

### Key Constraints
- Reuse `self.build_envelope(form, self._current_tenant).form_url` for the URL — do not recompose it.
- `_build_upload_element` has no access to `form`; take `form_url` from a per-render attribute `self._current_form_url` set in `render()` right after `_current_tenant` (same synchronous window; spec §7).
- Warning text: `"file/image upload unsupported in Teams cards — web form link rendered"`.

---

## Implementation Blueprint

### Steps (in order)
1. In `render()`, compute `env = self.build_envelope(form, resolved)` BEFORE `super().render(...)` and store `self._current_form_url = str(env.form_url)` — *why*: the upload hook runs inside the base render and needs the URL.
2. Override `_build_upload_element` — *why*: spec §3 M2 element shape.
3. Add `UPLOAD_NOTICE_TEXT`, `_upload_warnings`, and extend `result.warnings` in `render()` — *why*: AC "one RenderWarning(renderer='teams') per upload field, nested included".
4. Tests; run `pytest packages/parrot-formdesigner/tests/unit/test_teams_renderer.py packages/parrot-formdesigner/tests/unit/test_renderers.py -q`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3147: grep -c '^class TeamsRenderConfigError' renderers/teams.py)
# BEFORE — insert above `class TeamsRenderConfigError(ValueError):`
UPLOAD_NOTICE_TEXT: dict[str, str] = {
    "en": "Attachments can't be uploaded from Teams. Open the web form to add files.",
    "es": "No se pueden adjuntar archivos desde Teams. Abre el formulario web para agregarlos.",
}
UPLOAD_WARNING_REASON: str = "file/image upload unsupported in Teams cards — web form link rendered"

# Inside class TeamsFormRenderer — add:
    def _build_upload_element(self, field: FormField, value: Any, locale: str) -> dict[str, Any] | None:
        """Teams cannot upload files: render a notice + Action.OpenUrl to the web form (spec §3 M2)."""
        lang = locale.split("-")[0]
        notice = UPLOAD_NOTICE_TEXT.get(lang, UPLOAD_NOTICE_TEXT["en"])
        title = _resolve(field.label, locale) or "Open web form"
        return {
            "type": "Container",
            "items": [
                {"type": "TextBlock", "text": notice, "isSubtle": True, "wrap": True, "size": "Small"},
                {"type": "ActionSet", "actions": [{"type": "Action.OpenUrl", "title": title, "url": self._current_form_url}]},
            ],
        }

    def _upload_warnings(self, form: FormSchema) -> list[RenderWarning]:
        """One warning per upload-type field, walking sections and subsections."""
        warnings: list[RenderWarning] = []
        # FILL IN: for section in form.sections: for item in section.fields: if FormSubsection -> iterate item.fields
        #   else treat as FormField; for each field with field_type in UPLOAD_FIELD_TYPES append
        #   RenderWarning(field_id=..., field_uid=..., field_type=field.field_type.value, renderer=self.RENDERER_NAME,
        #   reason=UPLOAD_WARNING_REASON) — bounded by _build_section_body walk (adaptive_card.py:595-643).
        return warnings

# In render() (TASK-3147 body): set `self._current_form_url = str(self.build_envelope(form, resolved).form_url)`
# immediately after `self._current_tenant = resolved`, and after super().render(...) do
# `result.warnings = [*result.warnings, *self._upload_warnings(form)]`.
```
**Why**: the container carries the OpenUrl inline next to the field label the base already emits (`_build_field` :689-756 still renders label/description), so the user sees where to go; warnings surface through `?with_meta=true` (TASK-3149).

### `packages/parrot-formdesigner/tests/unit/test_teams_renderer.py` (MODIFY)
```python
# AFTER — append at end of file
@pytest.fixture
def upload_form(form) -> FormSchema:
    # FILL IN: copy `form` adding an IMAGE field at top level and a FILE field inside a FormSubsection — bounded by schema.py:195-254
    raise NotImplementedError


async def test_teams_upload_fields_openurl_and_warning(renderer, upload_form):
    result = await renderer.render(upload_form, tenant="navigator")
    body = json.dumps(result.content)
    assert '"Input.Text"' not in body.split('"actions"')[0] or True  # FILL IN: assert no Input.* element has id of an upload field
    opens = [a for a in _walk(result.content["body"]) if a.get("type") == "Action.OpenUrl"]
    assert len(opens) == 2 and all(o["url"] == f"https://forms.test/navigator/forms/{upload_form.form_uid}" for o in opens)
    teams_warnings = [w for w in result.warnings if w.renderer == "teams"]
    assert sorted(w.field_type for w in teams_warnings) == ["file", "image"]


async def test_adaptive_upload_fallback_unchanged(upload_form):
    result = await AdaptiveCardRenderer().render(upload_form)
    assert not [w for w in result.warnings if w.field_type in ("file", "image")]
    # FILL IN: assert the IMAGE field still renders as {"type": "Input.Text", "id": <field_id>, ...} — bounded by TASK-3146 hook default
```
**Why**: covers all AC bullets of spec §4 for M2 (nested field, all types, `adaptive` unchanged). `_walk` is a tiny recursive helper over `items`/`actions` lists (write it in the test module).

### FILL IN checklist
- [ ] `teams.py::_upload_warnings` — nested walk; bounded by adaptive_card.py:595-643.
- [ ] `test_teams_renderer.py::upload_form` + assertions on absence of `Input.*` for upload ids; bounded by AC "no Input.* is emitted for it".
- [ ] Parametrise the OpenUrl test over all four upload types.

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_teams_renderer.py packages/parrot-formdesigner/tests/unit/test_renderers.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/renderers/teams.py`
- [ ] Every upload-type field yields exactly one `Action.OpenUrl` (to `form_url`) and one `RenderWarning(renderer="teams")`, including fields inside subsections
- [ ] `AdaptiveCardRenderer` output and warnings for upload fields are unchanged (golden test green)

---

## Test Specification

See blueprint; parametrise `test_teams_upload_fields_openurl_and_warning` over `[FieldType.FILE, FieldType.IMAGE, FieldType.IMAGE_DROPZONE, FieldType.MULTI_UPLOAD]`.

---

## Agent Instructions

1. Read the spec §3 M2 and §7 (Teams constraints).
2. Check TASK-3147 is in `sdd/tasks/completed/`.
3. Verify the contract anchors (`grep -n "_build_upload_element" renderers/`).
4. Update index status → `"in-progress"`.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Verify acceptance criteria.
7. Move this file to `sdd/tasks/completed/TASK-3148-teams-upload-field-posture.md`; index → `"done"`; fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
