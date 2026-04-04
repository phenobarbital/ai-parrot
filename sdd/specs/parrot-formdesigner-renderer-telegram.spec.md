# Feature Specification: Telegram Form Renderer for parrot-formdesigner

**Feature ID**: FEAT-081
**Date**: 2026-04-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.2.0
**Brainstorm**: `sdd/proposals/parrot-formdesigner-renderer-telegram.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

parrot-formdesigner renders forms to HTML5, JSON Schema, and Adaptive Cards, but has no
Telegram renderer. Developers building Telegram bots with parrot must manually translate
FormSchema definitions into Telegram messages, keyboards, and conversation flows — this
is error-prone, duplicates validation logic, and bypasses the existing submission pipeline.

### Goals
- Render any FormSchema as native Telegram interactions (inline keyboards or WebApp).
- Auto-select rendering mode based on form complexity, with explicit override.
- Reuse `HTML5Renderer` for WebApp mode — no duplicate HTML rendering logic.
- Provide a standalone aiogram 3.x Router that any bot can include.
- Ensure all submissions pass through `FormValidator` for consistent validation.
- Be compatible with `parrot.integrations.telegram.TelegramAgentWrapper`.

### Non-Goals (explicitly out of scope)
- Replacing or modifying the existing Telegram integration architecture.
- Supporting aiogram 2.x.
- Implementing dynamic option loading (`OptionsSource`) during inline keyboard flow.
- Custom Telegram bot creation — this is a renderer, not a bot framework.

---

## 2. Architectural Design

### Overview

A dual-mode `TelegramRenderer` that extends `AbstractFormRenderer`. It analyzes a
FormSchema and produces either:
- **Inline mode**: A list of `TelegramFormStep` objects representing sequential
  field prompts with inline keyboard markups.
- **WebApp mode**: A URL pointing to an aiohttp-served HTML form with the Telegram
  WebApp JS SDK embedded.

A companion `TelegramFormRouter` (aiogram `Router` subclass) drives the conversation
for inline mode via FSMContext, and handles `web_app_data` messages for WebApp mode.

### Component Diagram
```
FormSchema
    │
    ▼
TelegramRenderer.render(form, mode=auto|inline|webapp)
    │
    ├─ [inline mode] ──→ TelegramFormPayload(steps=[TelegramFormStep, ...])
    │                           │
    │                           ▼
    │                     TelegramFormRouter (aiogram Router)
    │                           │
    │                     FSMContext per chat
    │                           │
    │                     CallbackQuery handlers
    │                           │
    │                           ▼
    │                     FormValidator.validate()
    │
    └─ [webapp mode] ──→ TelegramFormPayload(webapp_url="/forms/{id}/telegram")
                                │
                                ▼
                          aiohttp handler serves HTML
                          (HTML5Renderer + telegram-web-app.js)
                                │
                                ▼
                          sendData() → web_app_data handler
                                │
                                ▼
                          FormValidator.validate()
                          (or REST fallback for >4 KB payloads)
```

### Auto-Decision Logic

| Condition | Mode |
|-----------|------|
| Any field is TEXT, TEXT_AREA, NUMBER, INTEGER, DATE, DATETIME, TIME, EMAIL, URL, PHONE, PASSWORD, COLOR, GROUP, or ARRAY | WebApp |
| Any field is FILE or IMAGE | WebApp |
| Any SELECT/MULTI_SELECT has >5 options | WebApp |
| All fields are SELECT (<=5 opts), MULTI_SELECT (<=5 opts), BOOLEAN, or HIDDEN | Inline |
| Caller passes `mode="webapp"` or `mode="inline"` | Forced (with file-field safety: inline + file → WebApp + log warning) |

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractFormRenderer` | extends | TelegramRenderer inherits render() |
| `HTML5Renderer` | uses | Reused for WebApp HTML generation |
| `FormValidator` | uses | Both modes validate submissions |
| `FormRegistry` | uses | Lookup forms by ID for WebApp serving |
| `setup_form_routes()` | extends | Add `/forms/{id}/telegram` route |
| `TelegramAgentWrapper` | compatible | TelegramFormRouter can be included in its Dispatcher |
| `CallbackRegistry` | pattern reference | Follow same callback_data encoding conventions |

### Data Models

```python
class TelegramRenderMode(str, Enum):
    """Rendering mode for Telegram forms."""
    INLINE = "inline"
    WEBAPP = "webapp"
    AUTO = "auto"


class TelegramFormStep(BaseModel):
    """A single step in an inline keyboard form conversation."""
    field_id: str
    message_text: str  # prompt text for this field
    reply_markup: dict  # serialized InlineKeyboardMarkup
    field_type: FieldType
    required: bool = False


class TelegramFormPayload(BaseModel):
    """Output of TelegramRenderer.render()."""
    mode: TelegramRenderMode
    form_id: str
    form_title: str
    steps: list[TelegramFormStep] | None = None  # inline mode
    webapp_url: str | None = None  # webapp mode
    summary_text: str | None = None  # pre-submit summary template
    total_fields: int
```

### New Public Interfaces

```python
class TelegramRenderer(AbstractFormRenderer):
    """Renders FormSchema as Telegram interactions."""

    def __init__(
        self,
        base_url: str | None = None,
        html_renderer: HTML5Renderer | None = None,
    ) -> None: ...

    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
        mode: TelegramRenderMode = TelegramRenderMode.AUTO,
    ) -> RenderedForm: ...

    def analyze_form(self, form: FormSchema) -> TelegramRenderMode:
        """Determine optimal rendering mode for a form."""
        ...


class TelegramFormRouter(Router):
    """aiogram Router that handles form conversations."""

    def __init__(
        self,
        renderer: TelegramRenderer,
        registry: FormRegistry,
        validator: FormValidator | None = None,
        on_submit: Callable | None = None,  # optional callback after successful submission
    ) -> None: ...

    async def start_form(
        self,
        form_id: str,
        chat_id: int,
        bot: Bot,
        mode: TelegramRenderMode = TelegramRenderMode.AUTO,
    ) -> None:
        """Initiate a form conversation in the given chat."""
        ...
```

---

## 3. Module Breakdown

### Module 1: Telegram Form Models
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/telegram/models.py`
- **Responsibility**: Pydantic models for `TelegramRenderMode`, `TelegramFormStep`,
  `TelegramFormPayload`, and aiogram `CallbackData` factories for inline buttons.
- **Depends on**: `parrot.formdesigner.core.types.FieldType`

### Module 2: Telegram Renderer
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/telegram/renderer.py`
- **Responsibility**: `TelegramRenderer` class implementing `AbstractFormRenderer`.
  Analyzes form fields, auto-selects mode, produces `TelegramFormPayload` as
  `RenderedForm.content`. For inline mode, generates `TelegramFormStep` list.
  For WebApp mode, generates webapp URL.
- **Depends on**: Module 1, `AbstractFormRenderer`, `HTML5Renderer`, `FormSchema`

### Module 3: Telegram Form Router (inline + WebApp handler)
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/telegram/router.py`
- **Responsibility**: aiogram `Router` subclass with:
  - FSM states for inline keyboard multi-step flow.
  - `CallbackQuery` handlers for button presses.
  - `web_app_data` handler for WebApp submissions.
  - Summary/confirmation step before final submission.
  - Integration with `FormValidator`.
- **Depends on**: Module 1, Module 2, `FormValidator`, `FormRegistry`, aiogram 3.x

### Module 4: WebApp HTML Handler & Template
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/telegram.py`
- **Template**: `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/templates/telegram_webapp.html.j2`
- **Responsibility**: aiohttp handler serving the form HTML at `/forms/{id}/telegram`.
  Wraps `HTML5Renderer` output in a page with `telegram-web-app.js` embedded.
  Includes JS that serializes form data and calls `Telegram.WebApp.sendData()`,
  with a REST fallback for payloads exceeding 4 KB.
- **Depends on**: Module 2, `HTML5Renderer`, `FormRegistry`, `setup_form_routes()`

### Module 5: Package Integration & Exports
- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/telegram/__init__.py`
- **Responsibility**: Export `TelegramRenderer`, `TelegramFormRouter`, models.
  Update `renderers/__init__.py` to include Telegram exports.
  Register `/forms/{id}/telegram` route in `setup_form_routes()`.
  Add `aiogram>=3.12` to `pyproject.toml` dependencies.
- **Depends on**: Modules 1-4

### Module 6: Tests
- **Path**: `packages/parrot-formdesigner/tests/unit/test_telegram_renderer.py`
- **Responsibility**: Unit tests for form analysis, mode detection, step generation,
  WebApp URL generation, payload model serialization.
- **Depends on**: Modules 1-2

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_analyze_form_selects_only` | Module 2 | SELECT-only form → inline mode |
| `test_analyze_form_with_text` | Module 2 | Form with TEXT field → webapp mode |
| `test_analyze_form_with_file` | Module 2 | Form with FILE field → webapp mode |
| `test_analyze_form_many_options` | Module 2 | SELECT with >5 options → webapp mode |
| `test_analyze_form_boolean_only` | Module 2 | BOOLEAN-only form → inline mode |
| `test_analyze_form_mixed` | Module 2 | Mix of BOOLEAN + SELECT <=5 → inline mode |
| `test_explicit_mode_override` | Module 2 | `mode=webapp` forces webapp regardless |
| `test_inline_forced_with_file_fallback` | Module 2 | `mode=inline` + file field → webapp + warning |
| `test_render_inline_steps` | Module 2 | Inline render produces correct TelegramFormStep list |
| `test_render_inline_boolean_buttons` | Module 2 | BOOLEAN field produces Yes/No buttons |
| `test_render_inline_select_buttons` | Module 2 | SELECT field produces option buttons |
| `test_render_inline_multiselect_toggles` | Module 2 | MULTI_SELECT produces toggle buttons + Done |
| `test_render_webapp_url` | Module 2 | WebApp render produces correct URL |
| `test_payload_serialization` | Module 1 | TelegramFormPayload serializes/deserializes correctly |
| `test_callback_data_within_64_bytes` | Module 1 | CallbackData stays within 64-byte limit |
| `test_step_count_matches_fields` | Module 2 | Number of steps matches non-hidden field count |

### Integration Tests
| Test | Description |
|---|---|
| `test_webapp_handler_serves_html` | GET `/forms/{id}/telegram` returns HTML with telegram-web-app.js |
| `test_webapp_handler_404` | GET `/forms/{id}/telegram` with unknown ID returns 404 |
| `test_form_router_inline_flow` | Simulate full inline conversation with mocked Bot/FSMContext |
| `test_form_router_webapp_submit` | Simulate web_app_data message and validation |
| `test_rest_fallback_endpoint` | POST to REST fallback with large payload validates correctly |

### Test Data / Fixtures
```python
@pytest.fixture
def simple_select_form() -> FormSchema:
    """Form with 2 SELECT fields, <=5 options each — should render inline."""

@pytest.fixture
def complex_text_form() -> FormSchema:
    """Form with TEXT + SELECT + FILE fields — should render as webapp."""

@pytest.fixture
def boolean_only_form() -> FormSchema:
    """Form with 3 BOOLEAN fields — should render inline."""
```

---

## 5. Acceptance Criteria

- [ ] `TelegramRenderer` subclasses `AbstractFormRenderer` and passes type checks.
- [ ] Auto-detection correctly selects inline for SELECT/BOOLEAN-only forms (<=5 options).
- [ ] Auto-detection correctly selects WebApp for forms with text inputs or file fields.
- [ ] Explicit `mode` parameter overrides auto-detection.
- [ ] `mode="inline"` with file fields falls back to WebApp with a logged warning.
- [ ] Inline mode produces `TelegramFormStep` list with correct keyboard markups.
- [ ] Inline mode callback_data stays within 64-byte Telegram limit.
- [ ] WebApp mode produces correct URL and aiohttp handler serves HTML with `telegram-web-app.js`.
- [ ] WebApp `sendData()` payload is validated by `FormValidator`.
- [ ] REST fallback endpoint handles payloads exceeding 4 KB `sendData()` limit.
- [ ] `TelegramFormRouter` is a standalone aiogram Router usable in any bot.
- [ ] `TelegramFormRouter` is compatible with `TelegramAgentWrapper`'s Dispatcher.
- [ ] Group chat detection sends deep-link to private chat instead of WebApp button.
- [ ] All unit tests pass.
- [ ] `TelegramRenderer` is exported from `parrot.formdesigner.renderers`.
- [ ] `aiogram>=3.12` added to `pyproject.toml` dependencies.
- [ ] No breaking changes to existing renderers or handlers.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
# These imports have been confirmed to work (2026-04-04):
from parrot.formdesigner.renderers.base import AbstractFormRenderer  # renderers/base.py:14
from parrot.formdesigner.renderers.html5 import HTML5Renderer  # renderers/html5.py:73
from parrot.formdesigner.renderers import HTML5Renderer, JsonSchemaRenderer, AdaptiveCardRenderer  # renderers/__init__.py:9-12
from parrot.formdesigner.core.schema import FormSchema, FormField, FormSection, RenderedForm  # core/schema.py
from parrot.formdesigner.core.types import FieldType, LocalizedString  # core/types.py:13-38
from parrot.formdesigner.core.options import FieldOption, OptionsSource  # core/options.py:12,30
from parrot.formdesigner.services.validators import FormValidator, ValidationResult  # services/validators.py:66,52
from parrot.formdesigner.services.registry import FormRegistry  # services/registry.py
from parrot.formdesigner.handlers.routes import setup_form_routes  # handlers/routes.py:20
from parrot.integrations.telegram import TelegramAgentWrapper, TelegramBotManager  # telegram/__init__.py
from parrot.integrations.telegram.callbacks import CallbackRegistry, CallbackContext  # callbacks.py:232,45
```

### Existing Class Signatures
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/renderers/base.py
class AbstractFormRenderer(ABC):  # line 14
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

# packages/parrot-formdesigner/src/parrot/formdesigner/renderers/html5.py
class HTML5Renderer(AbstractFormRenderer):  # line 73
    def __init__(self, template_dir: str | Path | None = None) -> None:  # line 92
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm:  # line 108

# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py
class RenderedForm(BaseModel):  # line 133
    content: Any
    content_type: str
    style_output: Any | None = None
    metadata: dict[str, Any] | None = None

class FormField(BaseModel):  # line 19
    field_id: str
    field_type: FieldType
    label: LocalizedString
    options: list[FieldOption] | None = None
    required: bool = False
    default: Any = None
    meta: dict[str, Any] | None = None
    children: list[FormField] | None = None

class FormSchema(BaseModel):  # line 105
    form_id: str
    title: LocalizedString
    sections: list[FormSection]
    submit: SubmitAction | None = None
    meta: dict[str, Any] | None = None

class FormSection(BaseModel):  # line 66
    section_id: str
    title: LocalizedString | None = None
    fields: list[FormField]

# packages/parrot-formdesigner/src/parrot/formdesigner/core/options.py
class FieldOption(BaseModel):  # line 12
    value: str
    label: LocalizedString
    disabled: bool = False

# packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py
class ValidationResult(BaseModel):  # line 52
    is_valid: bool
    errors: dict[str, list[str]]

class FormValidator:  # line 66
    async def validate(self, form: FormSchema, data: dict) -> ValidationResult:  # (main method)

# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py
def setup_form_routes(  # line 20
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    api_key: str | None = None,
    prefix: str = "",
) -> None:

# packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:  # line 48
    router: Router  # aiogram Router
    _callback_registry: CallbackRegistry  # line 95

# packages/ai-parrot/src/parrot/integrations/telegram/callbacks.py
class CallbackRegistry:  # line 232
    def register(self, prefix: str, handler: Callable, description: str = "") -> None:
    def match(self, callback_data: str) -> Optional[tuple[CallbackMetadata, Dict[str, Any]]]:
```

### Key Constants & Limits
- `FieldType` enum: 20 values (TEXT, TEXT_AREA, NUMBER, INTEGER, BOOLEAN, DATE, DATETIME, TIME, SELECT, MULTI_SELECT, FILE, IMAGE, COLOR, URL, EMAIL, PHONE, PASSWORD, HIDDEN, GROUP, ARRAY) — `core/types.py:16-38`
- Telegram `callback_data` limit: **64 bytes**
- Telegram `sendData()` limit: **4096 bytes (4 KB)**
- aiogram installed: **v3.26.0**
- WebApp JS SDK: `https://telegram.org/js/telegram-web-app.js`

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `TelegramRenderer` | `AbstractFormRenderer` | inheritance | `renderers/base.py:14` |
| `TelegramRenderer` | `HTML5Renderer.render()` | method call (WebApp mode) | `renderers/html5.py:108` |
| `TelegramFormRouter` | `FormValidator.validate()` | method call | `services/validators.py:66` |
| `TelegramFormRouter` | `FormRegistry.get()` | method call | `services/registry.py` |
| WebApp handler | `setup_form_routes()` | route registration | `handlers/routes.py:20` |
| `TelegramFormRouter` | `TelegramAgentWrapper.router` | Router inclusion | `wrapper.py:48` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.formdesigner.renderers.telegram`~~ — does not exist yet; this is what we're building
- ~~`TelegramAgentWrapper.form_handler`~~ — no form handling in current telegram wrapper
- ~~`parrot.formdesigner.handlers.telegram`~~ — no telegram-specific handlers exist yet
- ~~`FormSchema.to_telegram()`~~ — no telegram conversion method on the model
- ~~`parrot.integrations.telegram.webapp`~~ — no WebApp module exists
- ~~`HTML5Renderer.render_for_telegram()`~~ — does not exist; reuse standard `render()`
- ~~`FormField.telegram_config`~~ — not a real attribute
- ~~`RenderedForm.telegram_payload`~~ — not a real attribute

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Subclass `AbstractFormRenderer` exactly as `HTML5Renderer` and `AdaptiveCardRenderer` do.
- Use Pydantic `BaseModel` for all data models (`TelegramFormStep`, `TelegramFormPayload`).
- Use aiogram's `CallbackData` factory for type-safe inline button data encoding.
- Use aiogram's `StatesGroup` / `State` for FSM-based inline form flow.
- Use `self.logger = logging.getLogger(__name__)` for all logging.
- The Jinja2 template for WebApp should use `autoescape=True` and `| safe` only for
  trusted renderer output (same pattern as `form.html.j2`).

### Resolved Decisions (from brainstorm)
- **base_url**: Accepts `base_url` parameter; falls back to app config if None.
- **Group chats**: Send deep-link to private chat when form needs WebApp in a group.
- **sendData() overflow**: Implement a REST fallback endpoint at `/api/v1/forms/{id}/telegram-submit`.
- **aiogram dependency**: Hard requirement in `pyproject.toml`, not optional.

### Known Risks / Gotchas
- **64-byte callback_data**: Use compact encoding `f:{hash}:{field_idx}:{opt_idx}`. Test
  that the longest possible callback_data stays under limit.
- **4 KB sendData()**: Large forms with many prefilled values may exceed this. The REST
  fallback must be tested with realistic form sizes.
- **WebApp in groups**: WebApp buttons silently fail in groups. Must detect group context
  (`chat.type != "private"`) before sending WebApp buttons.
- **FSM state expiry**: If user abandons an inline form, FSMContext data persists until
  storage TTL. Implement a `/cancel` handler and consider reasonable TTLs.
- **Concurrent forms**: A user starting a second inline form while one is active should
  cancel the first. FSMContext state replacement handles this naturally.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `aiogram` | `>=3.12` | Telegram Bot API, Router, FSMContext, WebAppInfo, CallbackData |
| `jinja2` | `>=3.1` | WebApp HTML template rendering (already a dependency) |
| `aiohttp` | `>=3.9` | WebApp HTML serving (already a dependency) |

---

## 8. Open Questions

All questions from brainstorm have been resolved. No remaining open questions.

---

## Worktree Strategy

- **Default isolation**: `per-spec` — all tasks run sequentially in one worktree.
- **Rationale**: Modules 1-5 share `TelegramFormPayload` and form analysis logic.
  Parallel implementation would cause model definition conflicts. Module 6 (tests)
  depends on all other modules.
- **Cross-feature dependencies**: None. This feature touches only new files, plus
  minor additions to `renderers/__init__.py` and `handlers/routes.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-04 | Jesus Lara | Initial draft from brainstorm |
