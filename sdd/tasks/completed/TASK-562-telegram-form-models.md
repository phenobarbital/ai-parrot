# TASK-562: Telegram Form Models

**Feature**: FEAT-081 parrot-formdesigner-renderer-telegram
**Spec**: `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task creates the foundational data models for the Telegram renderer. All other
tasks depend on these models. Implements Spec Module 1.

---

## Scope

- Create the `renderers/telegram/` package with `__init__.py`.
- Implement `TelegramRenderMode` enum (`INLINE`, `WEBAPP`, `AUTO`).
- Implement `TelegramFormStep` Pydantic model (field_id, message_text, reply_markup dict,
  field_type, required).
- Implement `TelegramFormPayload` Pydantic model (mode, form_id, form_title, steps,
  webapp_url, summary_text, total_fields).
- Implement aiogram `CallbackData` factory for inline form buttons with compact encoding
  that stays within the 64-byte `callback_data` limit.
- Write unit tests for model serialization and callback_data size constraints.

**NOT in scope**: Renderer logic, Router/FSM logic, WebApp handler, route registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/telegram/__init__.py` | CREATE | Package init (empty for now, Module 5 populates exports) |
| `packages/parrot-formdesigner/src/parrot/formdesigner/renderers/telegram/models.py` | CREATE | All Pydantic models and CallbackData factories |
| `packages/parrot-formdesigner/tests/unit/test_telegram_models.py` | CREATE | Unit tests for models |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.formdesigner.core.types import FieldType  # core/types.py:16
from parrot.formdesigner.core.schema import RenderedForm  # core/schema.py:133
from pydantic import BaseModel  # pydantic v2
from enum import Enum
# aiogram CallbackData:
from aiogram.filters.callback_data import CallbackData  # aiogram 3.x
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/core/types.py:16
class FieldType(str, Enum):
    TEXT = "text"
    TEXT_AREA = "text_area"
    # ... 20 values total through ARRAY = "array" (line 38)

# packages/parrot-formdesigner/src/parrot/formdesigner/core/schema.py:133
class RenderedForm(BaseModel):
    content: Any
    content_type: str
    style_output: Any | None = None
    metadata: dict[str, Any] | None = None
```

### Does NOT Exist
- ~~`parrot.formdesigner.renderers.telegram`~~ — does not exist yet; this task creates it
- ~~`parrot.formdesigner.renderers.telegram.models`~~ — does not exist yet
- ~~`aiogram.types.CallbackData`~~ — wrong import path; correct is `aiogram.filters.callback_data.CallbackData`

---

## Implementation Notes

### Pattern to Follow
```python
# Reference: aiogram CallbackData factory pattern
from aiogram.filters.callback_data import CallbackData

class FormFieldCallback(CallbackData, prefix="ff"):
    """Compact callback data for form field selections."""
    form_hash: str   # short hash of form_id (keep <=8 chars)
    field_idx: int   # field index in flattened list
    option_idx: int  # selected option index (-1 for special actions)
```

### Key Constraints
- `CallbackData.pack()` output MUST stay under 64 bytes. Test with worst-case values.
- Use `str(Enum)` for `TelegramRenderMode` — follow same pattern as `FieldType(str, Enum)`.
- `TelegramFormStep.reply_markup` is `dict` (serialized `InlineKeyboardMarkup`) to avoid
  hard-coupling the model to aiogram types.

---

## Acceptance Criteria

- [ ] `TelegramRenderMode` enum has INLINE, WEBAPP, AUTO values
- [ ] `TelegramFormStep` model serializes/deserializes correctly
- [ ] `TelegramFormPayload` model serializes/deserializes correctly
- [ ] `FormFieldCallback.pack()` output is <=64 bytes for worst-case inputs
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/test_telegram_models.py -v`
- [ ] Import works: `from parrot.formdesigner.renderers.telegram.models import TelegramRenderMode, TelegramFormStep, TelegramFormPayload`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_telegram_models.py
import pytest
from parrot.formdesigner.renderers.telegram.models import (
    TelegramRenderMode,
    TelegramFormStep,
    TelegramFormPayload,
    FormFieldCallback,
)
from parrot.formdesigner.core.types import FieldType


class TestTelegramRenderMode:
    def test_enum_values(self):
        assert TelegramRenderMode.INLINE == "inline"
        assert TelegramRenderMode.WEBAPP == "webapp"
        assert TelegramRenderMode.AUTO == "auto"


class TestTelegramFormStep:
    def test_serialization(self):
        step = TelegramFormStep(
            field_id="visit_type",
            message_text="Select visit type:",
            reply_markup={"inline_keyboard": [[{"text": "A", "callback_data": "x"}]]},
            field_type=FieldType.SELECT,
            required=True,
        )
        data = step.model_dump()
        assert data["field_id"] == "visit_type"
        restored = TelegramFormStep.model_validate(data)
        assert restored.field_type == FieldType.SELECT


class TestTelegramFormPayload:
    def test_inline_payload(self):
        payload = TelegramFormPayload(
            mode=TelegramRenderMode.INLINE,
            form_id="test-form",
            form_title="Test",
            steps=[],
            total_fields=0,
        )
        assert payload.webapp_url is None

    def test_webapp_payload(self):
        payload = TelegramFormPayload(
            mode=TelegramRenderMode.WEBAPP,
            form_id="test-form",
            form_title="Test",
            webapp_url="https://example.com/forms/test-form/telegram",
            total_fields=5,
        )
        assert payload.steps is None


class TestFormFieldCallback:
    def test_pack_within_64_bytes(self):
        cb = FormFieldCallback(form_hash="abcdefgh", field_idx=99, option_idx=99)
        packed = cb.pack()
        assert len(packed.encode("utf-8")) <= 64

    def test_roundtrip(self):
        original = FormFieldCallback(form_hash="abc", field_idx=2, option_idx=3)
        packed = original.pack()
        restored = FormFieldCallback.unpack(packed)
        assert restored.field_idx == 2
        assert restored.option_idx == 3
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/parrot-formdesigner-renderer-telegram.spec.md`
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm imports still work
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-562-telegram-form-models.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
