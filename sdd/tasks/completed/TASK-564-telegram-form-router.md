# TASK-564: Telegram Form Router

**Feature**: FEAT-081 parrot-formdesigner-renderer-telegram
**Spec**: `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-562, TASK-563
**Assigned-to**: unassigned

---

## Context

The aiogram Router that drives form conversations — both inline keyboard multi-step
flows (via FSM) and WebApp data reception. Implements Spec Module 3. This is the
most complex task in the feature.

---

## Scope

- Implement `TelegramFormRouter(Router)` in `renderers/telegram/router.py`.
- Implement `__init__(self, renderer, registry, validator=None, on_submit=None)`.
- Implement `start_form(form_id, chat_id, bot, mode=AUTO)`:
  - Renders the form via `TelegramRenderer`.
  - If inline mode: sends first field message + keyboard, sets FSM state.
  - If WebApp mode: sends message with WebApp keyboard button.
  - If group chat (`chat.type != "private"`) and WebApp needed: send deep-link to private chat.
- Implement FSM states for inline mode:
  - Dynamic `StatesGroup` with one state per field.
  - `CallbackQuery` handler that matches `FormFieldCallback`, stores answer in FSMContext,
    advances to next field.
  - MULTI_SELECT toggle logic: track selected options, show checkmarks, "Done" button.
  - Summary step after last field: show all answers, Submit/Cancel buttons.
  - On Submit: collect data from FSMContext, run `FormValidator.validate()`, send result.
  - On Cancel: clear FSMContext, send cancellation message.
- Implement `web_app_data` handler:
  - Filter: `F.web_app_data` on the Router.
  - Deserialize JSON from `message.web_app_data.data`.
  - Run `FormValidator.validate()`.
  - Reply with success or error summary.
- Implement optional `on_submit` callback: called with `(form_id, validated_data, chat_id)` after
  successful validation.
- Write integration-style tests with mocked Bot and FSMContext.

**NOT in scope**: WebApp HTML serving (TASK-565), route registration (TASK-566).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/telegram/router.py` | CREATE | TelegramFormRouter class |
| `packages/parrot-formdesigner/tests/unit/test_telegram_router.py` | CREATE | Tests with mocked aiogram |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.formdesigner.renderers.base import AbstractFormRenderer  # renderers/base.py:14
from parrot.formdesigner.core.schema import FormSchema, RenderedForm  # core/schema.py
from parrot.formdesigner.core.types import FieldType  # core/types.py:16
from parrot.formdesigner.services.validators import FormValidator, ValidationResult  # services/validators.py:66,52
from parrot.formdesigner.services.registry import FormRegistry  # services/registry.py
# From TASK-562/563:
from parrot.formdesigner.renderers.telegram.models import (
    TelegramRenderMode, TelegramFormStep, TelegramFormPayload, FormFieldCallback
)
from parrot.formdesigner.renderers.telegram.renderer import TelegramRenderer

# aiogram imports:
from aiogram import Router, Bot, F  # aiogram 3.x
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py:52
class ValidationResult(BaseModel):
    is_valid: bool
    errors: dict[str, list[str]]

# packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py:66
class FormValidator:
    async def validate(self, form: FormSchema, data: dict) -> ValidationResult:

# packages/parrot-formdesigner/src/parrot/formdesigner/services/registry.py
class FormRegistry:
    async def get(self, form_id: str) -> FormSchema | None:

# packages/ai-parrot/src/parrot/integrations/telegram/callbacks.py:45
@dataclass
class CallbackContext:
    prefix: str
    payload: Dict[str, Any]
    chat_id: int
    user_id: int
    message_id: int
```

### Does NOT Exist
- ~~`TelegramFormRouter`~~ — does not exist yet; this task creates it
- ~~`aiogram.fsm.state.DynamicStatesGroup`~~ — does not exist; create states programmatically or use a single generic state with data tracking
- ~~`FormValidator.validate_field()`~~ — does not exist; `validate()` works on the full form only
- ~~`FormRegistry.get_form()`~~ — wrong method name; correct is `FormRegistry.get()`
- ~~`Router.register_form()`~~ — does not exist on aiogram Router

---

## Implementation Notes

### Pattern to Follow
```python
# aiogram 3.x Router + FSM pattern:
class TelegramFormRouter(Router):
    def __init__(self, renderer, registry, validator=None, on_submit=None):
        super().__init__()
        self.renderer = renderer
        self.registry = registry
        self.validator = validator or FormValidator()
        self.on_submit = on_submit

        # Register handlers
        self.callback_query.register(self._handle_field_callback, FormFieldCallback.filter())
        self.message.register(self._handle_webapp_data, F.web_app_data)
```

### Key Constraints
- FSM approach: use a SINGLE generic state (e.g., `FormFilling.active`) and track
  current field index in FSMContext data rather than creating N dynamic states.
  This avoids the complexity of dynamic StatesGroup creation.
- FSMContext data structure: `{"form_id": str, "current_field_idx": int, "answers": dict, "steps": list}`.
- For MULTI_SELECT toggle: store selected values as a set in FSMContext, re-render
  keyboard with checkmarks on each toggle, finalize on "Done" press.
- Deep-link for groups: `https://t.me/{bot_username}?start=form_{form_id}`.
- `on_submit` callback is optional — if None, just send success/error message.

---

## Acceptance Criteria

- [ ] `TelegramFormRouter` is a valid aiogram `Router` subclass
- [ ] `start_form()` sends first field for inline mode
- [ ] `start_form()` sends WebApp button for webapp mode
- [ ] Inline flow: callback handler advances through fields correctly
- [ ] Inline flow: BOOLEAN produces Yes/No buttons
- [ ] Inline flow: MULTI_SELECT toggle + Done works
- [ ] Inline flow: summary + Submit/Cancel at end
- [ ] Inline flow: Submit runs `FormValidator.validate()` and reports result
- [ ] Inline flow: Cancel clears state
- [ ] WebApp flow: `web_app_data` handler deserializes and validates
- [ ] Group chat: deep-link sent instead of WebApp button
- [ ] `on_submit` callback invoked on success
- [ ] Tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_telegram_router.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_telegram_router.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.formdesigner.renderers.telegram.router import TelegramFormRouter
from parrot.formdesigner.renderers.telegram.renderer import TelegramRenderer
from parrot.formdesigner.renderers.telegram.models import TelegramRenderMode
from parrot.formdesigner.services.registry import FormRegistry
from parrot.formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.core.options import FieldOption


@pytest.fixture
def simple_form() -> FormSchema:
    return FormSchema(
        form_id="test",
        title="Test",
        sections=[FormSection(section_id="s1", fields=[
            FormField(
                field_id="q1", field_type=FieldType.BOOLEAN, label="OK?", required=True
            ),
        ])],
    )


@pytest.fixture
def mock_registry(simple_form):
    reg = AsyncMock(spec=FormRegistry)
    reg.get.return_value = simple_form
    return reg


class TestTelegramFormRouter:
    def test_is_router(self, mock_registry):
        renderer = TelegramRenderer(base_url="https://example.com")
        router = TelegramFormRouter(renderer=renderer, registry=mock_registry)
        from aiogram import Router
        assert isinstance(router, Router)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
2. **Check dependencies** — verify TASK-562 and TASK-563 are completed
3. **Verify the Codebase Contract** — confirm all imports, especially aiogram ones
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-564-telegram-form-router.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
