# TASK-563: Telegram Renderer

**Feature**: FEAT-081 parrot-formdesigner-renderer-telegram
**Spec**: `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-562
**Assigned-to**: unassigned

---

## Context

Core renderer class that analyzes FormSchema fields and produces either inline-mode
steps or a WebApp URL. Implements Spec Module 2.

---

## Scope

- Implement `TelegramRenderer(AbstractFormRenderer)` in `renderers/telegram/renderer.py`.
- Implement `__init__(self, base_url=None, html_renderer=None)` — accepts optional base URL
  (falls back to config) and optional HTML5Renderer instance.
- Implement `analyze_form(form) -> TelegramRenderMode` — auto-detection logic:
  - Inline: all fields are SELECT (<=5 opts), MULTI_SELECT (<=5 opts), BOOLEAN, or HIDDEN.
  - WebApp: any TEXT, TEXT_AREA, NUMBER, INTEGER, DATE, DATETIME, TIME, EMAIL, URL, PHONE,
    PASSWORD, COLOR, FILE, IMAGE, GROUP, ARRAY, or SELECT/MULTI_SELECT with >5 options.
- Implement `render()` method:
  - Inline mode: flatten fields, generate `TelegramFormStep` per non-hidden field with
    correct `reply_markup` dict (InlineKeyboardMarkup structure). BOOLEAN → Yes/No buttons.
    SELECT → one button per option. MULTI_SELECT → toggle buttons + Done button.
  - WebApp mode: generate `webapp_url` as `{base_url}/forms/{form_id}/telegram`.
  - Return `RenderedForm(content=TelegramFormPayload(...), content_type="application/x-telegram-form")`.
- Handle explicit `mode` override parameter via `**kwargs` or extra render param.
- Handle safety fallback: `mode=inline` + file fields → WebApp + log warning.
- Write unit tests for auto-detection logic and both render paths.

**NOT in scope**: aiogram Router/FSM, WebApp HTML handler, route registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/telegram/renderer.py` | CREATE | TelegramRenderer class |
| `packages/parrot-formdesigner/tests/unit/test_telegram_renderer.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.formdesigner.renderers.base import AbstractFormRenderer  # renderers/base.py:14
from parrot.formdesigner.renderers.html5 import HTML5Renderer  # renderers/html5.py:73
from parrot.formdesigner.core.schema import FormSchema, FormField, FormSection, RenderedForm  # core/schema.py
from parrot.formdesigner.core.types import FieldType, LocalizedString  # core/types.py:13-38
from parrot.formdesigner.core.options import FieldOption  # core/options.py:12
from parrot.formdesigner.core.style import StyleSchema  # core/style.py
# From TASK-562:
from parrot.formdesigner.renderers.telegram.models import (
    TelegramRenderMode, TelegramFormStep, TelegramFormPayload, FormFieldCallback
)
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/renderers/base.py:14
class AbstractFormRenderer(ABC):
    @abstractmethod
    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:  # line 25

# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:19
class FormField(BaseModel):
    field_id: str
    field_type: FieldType
    label: LocalizedString
    options: list[FieldOption] | None = None
    required: bool = False
    default: Any = None
    meta: dict[str, Any] | None = None
    children: list[FormField] | None = None

# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:66
class FormSection(BaseModel):
    section_id: str
    fields: list[FormField]

# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:105
class FormSchema(BaseModel):
    form_id: str
    title: LocalizedString
    sections: list[FormSection]

# packages/parrot-formdesigner/src/parrot/formdesigner/core/options.py:12
class FieldOption(BaseModel):
    value: str
    label: LocalizedString
    disabled: bool = False
```

### Does NOT Exist
- ~~`AbstractFormRenderer.analyze_form()`~~ — does not exist on the base class; this is a new method on TelegramRenderer only
- ~~`FormSchema.flatten_fields()`~~ — does not exist; must iterate `form.sections[*].fields` manually
- ~~`FormField.is_simple()`~~ — does not exist; analyze `field_type` directly
- ~~`FieldType.is_text_input()`~~ — does not exist; compare against FieldType enum values

---

## Implementation Notes

### Pattern to Follow
```python
# Follow AdaptiveCardRenderer pattern for render() structure:
# 1. Apply defaults (style, prefilled, errors)
# 2. Process fields
# 3. Return RenderedForm

# For auto-detection, define sets:
_INLINE_FIELD_TYPES = {FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.BOOLEAN, FieldType.HIDDEN}
_MAX_INLINE_OPTIONS = 5
```

### Key Constraints
- `render()` signature must match `AbstractFormRenderer.render()`. Pass `mode` via `**kwargs`
  or add it as a keyword-only parameter after the base class params.
- Use `_resolve()` helper (from `html5.py:49`) pattern to resolve `LocalizedString` for
  message text generation. Reimplement or import from a shared location.
- `reply_markup` in `TelegramFormStep` must be a plain dict matching aiogram
  `InlineKeyboardMarkup` structure: `{"inline_keyboard": [[{"text": ..., "callback_data": ...}]]}`.
- Log warnings with `self.logger.warning()` when falling back from inline to WebApp.

---

## Acceptance Criteria

- [ ] `TelegramRenderer` subclasses `AbstractFormRenderer`
- [ ] `analyze_form()` returns INLINE for SELECT/BOOLEAN-only forms (<=5 options)
- [ ] `analyze_form()` returns WEBAPP for forms with text inputs
- [ ] `analyze_form()` returns WEBAPP for forms with file fields
- [ ] `analyze_form()` returns WEBAPP for SELECT with >5 options
- [ ] `render()` inline mode produces correct TelegramFormStep list
- [ ] `render()` webapp mode produces correct URL in TelegramFormPayload
- [ ] Explicit mode override works
- [ ] Inline + file fields → WebApp fallback with warning logged
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_telegram_renderer.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_telegram_renderer.py
import pytest
from parrot.formdesigner.renderers.telegram.renderer import TelegramRenderer
from parrot.formdesigner.renderers.telegram.models import TelegramRenderMode
from parrot.formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.core.options import FieldOption


def _make_form(fields: list[FormField], form_id: str = "test") -> FormSchema:
    return FormSchema(
        form_id=form_id,
        title="Test Form",
        sections=[FormSection(section_id="s1", fields=fields)],
    )


def _select_field(n_options: int = 3) -> FormField:
    return FormField(
        field_id="sel",
        field_type=FieldType.SELECT,
        label="Pick one",
        options=[FieldOption(value=f"v{i}", label=f"Option {i}") for i in range(n_options)],
    )


class TestAnalyzeForm:
    def test_select_only_inline(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_select_field(3)])
        assert renderer.analyze_form(form) == TelegramRenderMode.INLINE

    def test_text_field_webapp(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([FormField(field_id="name", field_type=FieldType.TEXT, label="Name")])
        assert renderer.analyze_form(form) == TelegramRenderMode.WEBAPP

    def test_file_field_webapp(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([FormField(field_id="doc", field_type=FieldType.FILE, label="Upload")])
        assert renderer.analyze_form(form) == TelegramRenderMode.WEBAPP

    def test_many_options_webapp(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_select_field(10)])
        assert renderer.analyze_form(form) == TelegramRenderMode.WEBAPP

    def test_boolean_inline(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([FormField(field_id="ok", field_type=FieldType.BOOLEAN, label="OK?")])
        assert renderer.analyze_form(form) == TelegramRenderMode.INLINE


class TestRender:
    @pytest.mark.asyncio
    async def test_inline_render_produces_steps(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_select_field(3)])
        result = await renderer.render(form, mode=TelegramRenderMode.INLINE)
        payload = result.content
        assert payload.mode == TelegramRenderMode.INLINE
        assert len(payload.steps) == 1

    @pytest.mark.asyncio
    async def test_webapp_render_produces_url(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([FormField(field_id="name", field_type=FieldType.TEXT, label="Name")])
        result = await renderer.render(form)
        payload = result.content
        assert payload.mode == TelegramRenderMode.WEBAPP
        assert "telegram" in payload.webapp_url
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
2. **Check dependencies** — verify TASK-562 is completed
3. **Verify the Codebase Contract** — confirm all imports
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-563-telegram-renderer.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
