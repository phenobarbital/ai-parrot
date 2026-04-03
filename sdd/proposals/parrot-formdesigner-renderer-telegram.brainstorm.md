# Brainstorm: Telegram Form Renderer for parrot-formdesigner

**Date**: 2026-04-04
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

parrot-formdesigner can render forms to HTML5, JSON Schema, and Adaptive Cards, but there
is no way to present a FormSchema to Telegram users as an interactive experience. Developers
building Telegram bots with parrot need to manually translate form definitions into Telegram
messages, keyboards, and conversation flows. This is error-prone, duplicates logic, and
cannot leverage the existing validation/submission pipeline.

**Who is affected**: Developers using parrot-formdesigner who deploy Telegram bots
(via `parrot.integrations.telegram` or standalone aiogram bots).

**Why now**: The formdesigner package is stabilizing (renderers for HTML5, JSON Schema,
and Adaptive Cards exist). Telegram is a primary integration channel for parrot bots.

## Constraints & Requirements

- Must subclass `AbstractFormRenderer` and follow the existing renderer pattern.
- Must support **all 20 FieldType values** (some via WebApp fallback).
- Two rendering modes:
  - **Inline keyboard mode**: For simple forms (only SELECT/MULTI_SELECT/BOOLEAN fields, <=5 options each, no text input fields, no file fields).
  - **WebApp mode**: For complex forms (text inputs, file uploads, many fields). Uses HTML served via aiohttp with Telegram WebApp JS SDK.
- Auto-decision logic: push to WebApp if form has text inputs, file fields, or >5 options; use inline keyboards otherwise. Caller can explicitly override.
- Must be **self-contained** (usable with any aiogram 3.x bot) AND **compatible** with `parrot.integrations.telegram.TelegramAgentWrapper`.
- aiogram 3.x (currently v3.26.0) — use Router pattern, FSMContext for inline mode state.
- WebApp `sendData()` has a **4 KB payload limit** — forms with many fields must handle this.
- aiogram `callback_data` has a **64-byte limit** — must use compact encoding for inline buttons.

---

## Options Explored

### Option A: Dual-Mode Renderer with Shared Submission Pipeline

A single `TelegramRenderer` class that implements `AbstractFormRenderer.render()` and
returns a `RenderedForm` containing either:
- A list of `TelegramFormStep` objects (inline mode) — each step has a message text, reply markup, and field mapping.
- A WebApp URL + keyboard button (WebApp mode) — pointing to a `/forms/{id}/telegram` endpoint.

The renderer auto-selects the mode based on form analysis but accepts an explicit `mode` override.
For inline mode, a companion `TelegramFormRouter` (aiogram Router subclass) handles the
multi-step conversation using FSMContext. For WebApp mode, an aiohttp handler serves the
HTML5-rendered form with the Telegram WebApp JS SDK embedded, and a `web_app_data` handler
receives the submission.

Both modes feed submissions into `FormValidator` for validation, producing a unified
submission dict compatible with the existing pipeline.

Pros:
- Single renderer class, consistent API with other renderers.
- Auto-mode selection keeps the developer API simple.
- Reuses `HTML5Renderer` for WebApp mode — no duplicate rendering logic.
- `TelegramFormRouter` is a standalone aiogram Router that can be included in any bot.
- Submissions always go through `FormValidator`, maintaining data integrity.

Cons:
- More complex than a single-mode solution — two code paths to maintain.
- Inline mode requires FSM state management which adds complexity.
- 4 KB `sendData()` limit may need chunking or REST fallback for very large forms.

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `aiogram>=3.12` | Telegram Bot API, Router, FSMContext, WebAppInfo | Already installed v3.26.0 |
| `jinja2>=3.1` | Template rendering for WebApp HTML | Already a dependency |
| `aiohttp>=3.9` | Serve WebApp HTML pages | Already a dependency |

Existing Code to Reuse:
- `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/base.py` — `AbstractFormRenderer` base class
- `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/html5.py` — `HTML5Renderer` for WebApp HTML generation
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py` — `FormValidator` for submission validation
- `packages/ai-parrot/src/parrot/integrations/telegram/callbacks.py` — `CallbackRegistry`, `CallbackContext` for inline button handling patterns
- `packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py` — `TelegramAgentWrapper` for integration compatibility

---

### Option B: WebApp-Only Renderer

A simpler renderer that always uses Telegram WebApp mode. Every form is served as an HTML
page via aiohttp with the Telegram JS SDK embedded. The renderer produces a `RenderedForm`
with content containing the WebApp URL and a keyboard button to launch it.

No inline keyboard mode, no FSM state management. All forms open as mini-apps.

Pros:
- Significantly simpler — one code path, no FSM, no inline keyboard logic.
- Supports all field types natively (full HTML form).
- No callback_data 64-byte limit concern.
- Easier to maintain and test.

Cons:
- Poor UX for simple forms — a 2-button yes/no confirmation shouldn't require opening a WebApp.
- Requires HTTPS URL for WebApp (Telegram enforces this in production).
- Higher latency — user must wait for WebApp to load even for trivial forms.
- Doesn't leverage Telegram's native inline keyboard UX which users are familiar with.

Effort: Low

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `aiogram>=3.12` | WebAppInfo, web_app_data handler | Already installed |
| `jinja2>=3.1` | HTML template rendering | Already a dependency |
| `aiohttp>=3.9` | Serve WebApp pages | Already a dependency |

Existing Code to Reuse:
- `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/base.py` — `AbstractFormRenderer`
- `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/html5.py` — `HTML5Renderer`
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py` — `FormValidator`

---

### Option C: Inline-Only Renderer with Conversation Flow

A renderer that converts every form into a sequential conversation flow using aiogram
FSMContext. Each field becomes a conversation step — SELECT fields use inline keyboards,
text fields prompt the user to type, file fields ask for document uploads.

No WebApp mode at all. Everything happens within the Telegram chat as a guided conversation.

Pros:
- Fully native Telegram experience — no external pages.
- No HTTPS requirement.
- Works in group chats (WebApp buttons don't).
- Feels natural for chatbot interactions.

Cons:
- Very tedious for long forms (20+ fields = 20+ messages).
- Poor UX for forms with many text fields (user types one value at a time).
- Complex state management — must handle cancellation, back-navigation, timeouts.
- Difficult to show form "overview" before submission.
- Multi-select with many options is awkward as sequential toggles.
- File uploads mid-conversation require careful state handling.

Effort: High

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `aiogram>=3.12` | Router, FSMContext, InlineKeyboard | Already installed |

Existing Code to Reuse:
- `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/base.py` — `AbstractFormRenderer`
- `packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py` — `FormValidator`
- `packages/ai-parrot/src/parrot/integrations/telegram/callbacks.py` — `CallbackRegistry`

---

## Recommendation

**Option A** is recommended because:

- It provides the best UX by matching the rendering mode to form complexity — simple
  selection forms stay native in Telegram (fast, familiar), while complex forms get the
  full HTML treatment via WebApp.
- The auto-decision logic is straightforward and deterministic (has text input or file → WebApp;
  only selections with <=5 options → inline), with explicit override for edge cases.
- It reuses `HTML5Renderer` for WebApp mode, avoiding duplicate rendering logic.
- The `TelegramFormRouter` as a standalone aiogram Router makes it pluggable into any bot,
  not just parrot's `TelegramAgentWrapper`.
- The tradeoff is higher initial complexity vs Option B, but Option B's UX for simple forms
  (forcing WebApp for a yes/no question) would frustrate users. Option C's complexity is
  not justified given WebApp handles complex forms better.

---

## Feature Description

### User-Facing Behavior

**Simple form (inline mode):**
1. Bot sends a message: "Please select the type of visit:" with inline keyboard buttons
   (one per option).
2. User taps a button → bot acknowledges, moves to next field.
3. For BOOLEAN fields: two buttons "Yes" / "No".
4. For MULTI_SELECT: toggle buttons with checkmark indicators, plus a "Done" button.
5. After the last field, bot shows a summary and "Submit" / "Cancel" buttons.
6. On submit, bot validates and either confirms success or reports errors.

**Complex form (WebApp mode):**
1. Bot sends a message: "Please fill out the form:" with a "Open Form" button.
2. User taps → Telegram WebApp opens showing the full HTML form (styled for mobile).
3. User fills fields, taps Submit → `sendData()` sends JSON to bot.
4. Bot validates submission, replies with success or error summary.

**Explicit mode override:**
- Developer can force `mode="webapp"` or `mode="inline"` regardless of auto-detection.
- If `mode="inline"` is forced but form has file fields, renderer warns in logs and
  falls back to WebApp with a logged warning.

### Internal Behavior

**Renderer (`TelegramRenderer`):**
1. `render(form, style, mode=None)` analyzes the form:
   - Flattens all fields across sections.
   - Checks each field type: if any is TEXT, TEXT_AREA, NUMBER, INTEGER, DATE, DATETIME,
     TIME, EMAIL, URL, PHONE, PASSWORD, COLOR, FILE, IMAGE, GROUP, or ARRAY → WebApp mode.
   - If all fields are SELECT (<=5 options), MULTI_SELECT (<=5 options), BOOLEAN, or
     HIDDEN → inline mode.
   - Explicit `mode` parameter overrides auto-detection (with file-field safety check).
2. Returns `RenderedForm` with:
   - `content`: `TelegramFormPayload` (dataclass) containing mode, steps (inline) or
     webapp_url (webapp), and form metadata.
   - `content_type`: `"application/x-telegram-form"`
   - `metadata`: includes `mode`, `field_count`, `form_id`.

**Inline mode flow (`TelegramFormRouter`):**
1. Router is an aiogram `Router` with FSM states dynamically generated per form.
2. `start_form(form_id, chat_id, bot)` sends the first field as a message + inline keyboard.
3. Callback handler receives button press → stores answer in FSMContext data → sends next field.
4. After last field → sends summary message with Submit/Cancel keyboard.
5. On Submit → collects all data from FSMContext → runs `FormValidator.validate()` →
   sends result.

**WebApp mode flow:**
1. Renderer generates a URL: `{base_url}/forms/{form_id}/telegram`.
2. An aiohttp handler serves the HTML (from `HTML5Renderer`) wrapped in a Telegram WebApp
   template that includes `telegram-web-app.js` and a submit handler that calls
   `Telegram.WebApp.sendData(JSON.stringify(formData))`.
3. A `web_app_data` handler on the Router deserializes the JSON, runs `FormValidator`,
   and replies.

### Edge Cases & Error Handling

- **sendData() 4 KB limit**: For large forms, the WebApp submit handler checks payload
  size before calling `sendData()`. If over limit, falls back to POSTing to a REST endpoint
  and notifying the bot via internal callback.
- **Inline callback_data 64-byte limit**: Use compact encoding: `f:{form_id_short}:{field_idx}:{option_idx}`.
  Form ID is truncated/hashed to fit.
- **User cancels mid-form (inline)**: FSMContext is cleared, bot sends "Form cancelled" message.
- **Timeout (inline)**: If user doesn't respond within configurable timeout, FSMContext
  auto-expires (aiogram FSM storage TTL).
- **Invalid WebApp data**: If `sendData()` payload fails JSON parse or validation, bot
  replies with error summary and offers to reopen the form.
- **Form not found**: If form_id is not in registry when WebApp loads, show error page.
- **Group chat limitation**: WebApp buttons only work in private chats. If form is sent
  in a group, force inline mode or send a deep-link to private chat.

---

## Capabilities

### New Capabilities
- `telegram-form-renderer`: TelegramRenderer class implementing AbstractFormRenderer with dual-mode output
- `telegram-form-router`: Standalone aiogram Router for handling inline keyboard form conversations
- `telegram-webapp-handler`: aiohttp handler serving forms as Telegram WebApps with JS SDK
- `telegram-form-models`: Pydantic models for TelegramFormStep, TelegramFormPayload, and FSM state

### Modified Capabilities
- `formdesigner-renderers`: Add TelegramRenderer to `renderers/__init__.py` exports
- `formdesigner-handlers-routes`: Add `/forms/{id}/telegram` WebApp endpoint

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot.formdesigner.renderers` | extends | New TelegramRenderer added to renderer package |
| `parrot.formdesigner.handlers.routes` | extends | New `/forms/{id}/telegram` route for WebApp serving |
| `parrot.formdesigner.handlers.templates` | extends | New `telegram_webapp_page()` template function |
| `parrot.integrations.telegram.wrapper` | optional integration | TelegramFormRouter can be included in wrapper's dispatcher |
| `packages/parrot-formdesigner/pyproject.toml` | modifies | Add `aiogram>=3.12` as optional dependency `[telegram]` |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/parrot-formdesigner/src/parrot/formdesigner/renderers/base.py:14
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
        ...

# From packages/parrot-formdesigner/src/parrot/formdesigner/renderers/html5.py:73
class HTML5Renderer(AbstractFormRenderer):
    def __init__(self, template_dir: str | Path | None = None) -> None:  # line 92
    async def render(self, form, style=None, *, locale="en", prefilled=None, errors=None) -> RenderedForm:  # line 108

# From packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:133
class RenderedForm(BaseModel):
    content: Any
    content_type: str
    style_output: Any | None = None
    metadata: dict[str, Any] | None = None

# From packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:19
class FormField(BaseModel):
    field_id: str
    field_type: FieldType
    label: LocalizedString
    options: list[FieldOption] | None = None
    meta: dict[str, Any] | None = None
    # ... (20 fields total)

# From packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:105
class FormSchema(BaseModel):
    form_id: str
    title: LocalizedString
    sections: list[FormSection]
    submit: SubmitAction | None = None
    meta: dict[str, Any] | None = None

# From packages/ai-parrot/src/parrot/integrations/telegram/wrapper.py:48
class TelegramAgentWrapper:
    def __init__(self, agent, bot: Bot, config: TelegramAgentConfig, agent_commands=None):  # line 66
    # router: Router — aiogram Router with registered handlers
    # _callback_registry: CallbackRegistry

# From packages/ai-parrot/src/parrot/integrations/telegram/callbacks.py:232
class CallbackRegistry:
    def register(self, prefix: str, handler: Callable, description: str = "") -> None:
    def match(self, callback_data: str) -> Optional[tuple[CallbackMetadata, Dict[str, Any]]]:

# From packages/ai-parrot/src/parrot/integrations/telegram/callbacks.py:45
@dataclass
class CallbackContext:
    prefix: str
    payload: Dict[str, Any]
    chat_id: int
    user_id: int
    message_id: int
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.formdesigner.renderers.base import AbstractFormRenderer  # renderers/base.py:14
from parrot.formdesigner.renderers.html5 import HTML5Renderer  # renderers/html5.py:73
from parrot.formdesigner.renderers import HTML5Renderer, JsonSchemaRenderer, AdaptiveCardRenderer  # renderers/__init__.py
from parrot.formdesigner.core.schema import FormSchema, FormField, RenderedForm  # core/schema.py
from parrot.formdesigner.core.types import FieldType  # core/types.py:16
from parrot.formdesigner.services.validators import FormValidator  # services/validators.py
from parrot.formdesigner.services.registry import FormRegistry  # services/registry.py
from parrot.integrations.telegram import TelegramAgentWrapper, TelegramBotManager  # telegram/__init__.py
from parrot.integrations.telegram.callbacks import CallbackRegistry, CallbackContext  # callbacks.py
```

#### Key Attributes & Constants
- `FieldType` enum has 20 values: TEXT, TEXT_AREA, NUMBER, INTEGER, BOOLEAN, DATE, DATETIME, TIME, SELECT, MULTI_SELECT, FILE, IMAGE, COLOR, URL, EMAIL, PHONE, PASSWORD, HIDDEN, GROUP, ARRAY (`core/types.py:16-38`)
- `FormField.options` → `list[FieldOption] | None` — each FieldOption has `.value` and `.label` (`core/options.py`)
- `CallbackRegistry` uses 64-byte callback_data limit (`callbacks.py`)
- aiogram installed: v3.26.0
- Telegram WebApp `sendData()` limit: 4096 bytes

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.formdesigner.renderers.telegram`~~ — does not exist yet, this is what we're building
- ~~`TelegramAgentWrapper.form_handler`~~ — no form handling in current telegram wrapper
- ~~`parrot.formdesigner.handlers.telegram`~~ — no telegram-specific handlers exist
- ~~`FormSchema.to_telegram()`~~ — no telegram conversion method on the model
- ~~`parrot.integrations.telegram.webapp`~~ — no WebApp module exists in telegram integration
- ~~`HTML5Renderer.render_for_telegram()`~~ — no telegram-specific render method; reuse standard `render()`

---

## Parallelism Assessment

- **Internal parallelism**: Yes — the feature decomposes into 4 independent units:
  1. `TelegramRenderer` class + models (renderer layer, no aiogram dependency)
  2. `TelegramFormRouter` for inline keyboard mode (aiogram Router + FSM)
  3. WebApp HTML template + aiohttp handler (extends existing handlers)
  4. Integration glue with `TelegramAgentWrapper` (optional, depends on 2 + 3)
  Tasks 1-3 can run in parallel; task 4 depends on 2 and 3.
- **Cross-feature independence**: No conflicts with in-flight specs. Touches new files only,
  except minor additions to `renderers/__init__.py` and `handlers/routes.py`.
- **Recommended isolation**: `per-spec` — the tasks are tightly coupled (shared models,
  shared form analysis logic) and benefit from sequential implementation in one worktree.
- **Rationale**: While 3 of 4 tasks could theoretically parallelize, the shared
  `TelegramFormPayload` model and form-analysis logic mean parallel workers would
  likely conflict on model definitions. Sequential in one worktree is safer.

---

## Open Questions

- [x] **HTTPS for WebApp**: Telegram requires HTTPS URLs for WebApps in production. Should
  the renderer accept a `base_url` parameter, or should it read from app config? — *Owner: Jesus Lara*: both, receives a base_url but if null, read from config.
- [x] **Group chat forms**: WebApp buttons don't work in groups. Should we auto-detect group
  context and switch to inline mode or send a deep-link to private chat? — *Owner: Jesus Lara*: send a deep-link to private chat.
- [x] **sendData() overflow**: For forms exceeding 4 KB payload, should we implement a REST
  fallback endpoint or limit WebApp mode to forms under a certain size? — *Owner: Jesus Lara*: implement a REST fallback endpoint.
- [x] **aiogram as optional dep**: Should `aiogram` be an optional dependency of
  parrot-formdesigner (`pip install parrot-formdesigner[telegram]`) or a hard requirement? — *Owner: Jesus Lara*: hard requirement.
