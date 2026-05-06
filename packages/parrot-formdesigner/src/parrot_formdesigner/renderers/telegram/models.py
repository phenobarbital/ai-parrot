"""Data models for the Telegram form renderer.

Defines enums, Pydantic models, and aiogram CallbackData factories
used by TelegramRenderer and TelegramFormRouter.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from aiogram.filters.callback_data import CallbackData
from pydantic import BaseModel

from ...core.types import FieldType


class TelegramRenderMode(str, Enum):
    """Rendering mode for Telegram forms."""

    INLINE = "inline"
    WEBAPP = "webapp"
    AUTO = "auto"


class TelegramFormStep(BaseModel):
    """A single step in an inline keyboard form conversation.

    Attributes:
        field_id: The field this step collects data for.
        message_text: Prompt text sent to the user.
        reply_markup: Serialized InlineKeyboardMarkup dict.
        field_type: The FieldType of the underlying form field.
        required: Whether this field is required.
        options: List of (value, label) pairs for select-type fields.
    """

    field_id: str
    message_text: str
    reply_markup: dict[str, Any]
    field_type: FieldType
    required: bool = False
    options: list[tuple[str, str]] | None = None


class TelegramFormPayload(BaseModel):
    """Output of TelegramRenderer.render(), stored in RenderedForm.content.

    Attributes:
        mode: The rendering mode selected.
        form_id: Form identifier.
        form_title: Human-readable form title.
        steps: List of inline form steps (inline mode only).
        webapp_url: URL to the WebApp page (webapp mode only).
        summary_text: Pre-submit summary template.
        total_fields: Total number of renderable fields.
    """

    mode: TelegramRenderMode
    form_id: str
    form_title: str
    steps: list[TelegramFormStep] | None = None
    webapp_url: str | None = None
    summary_text: str | None = None
    total_fields: int


class FormFieldCallback(CallbackData, prefix="ff"):
    """Compact callback data for inline form field selections.

    Encodes form hash, field index, and option index within the
    64-byte Telegram callback_data limit.

    Attributes:
        fh: Short hash of form_id (max 8 chars).
        fi: Field index in the flattened field list.
        oi: Selected option index (-1 for special actions like 'done').
    """

    fh: str
    fi: int
    oi: int


class FormActionCallback(CallbackData, prefix="fa"):
    """Callback data for form-level actions (submit, cancel).

    Attributes:
        fh: Short hash of form_id (max 8 chars).
        act: Action identifier ('submit', 'cancel', 'done').
    """

    fh: str
    act: str
