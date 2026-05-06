"""Telegram form renderer.

Analyzes a FormSchema and produces either inline keyboard steps
or a WebApp URL, returned as a TelegramFormPayload inside RenderedForm.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from ...core.options import FieldOption
from ...core.schema import FormField, FormSchema, FormSection, RenderedForm
from ...core.style import StyleSchema
from ...core.types import FieldType, LocalizedString
from ..base import AbstractFormRenderer
from .models import (
    FormFieldCallback,
    TelegramFormPayload,
    TelegramFormStep,
    TelegramRenderMode,
)

logger = logging.getLogger(__name__)

# Field types that can be rendered as inline keyboards
_INLINE_FIELD_TYPES = {
    FieldType.SELECT,
    FieldType.MULTI_SELECT,
    FieldType.BOOLEAN,
    FieldType.HIDDEN,
}

# Field types that force WebApp mode
_WEBAPP_FIELD_TYPES = {
    FieldType.TEXT,
    FieldType.TEXT_AREA,
    FieldType.NUMBER,
    FieldType.INTEGER,
    FieldType.DATE,
    FieldType.DATETIME,
    FieldType.TIME,
    FieldType.EMAIL,
    FieldType.URL,
    FieldType.PHONE,
    FieldType.PASSWORD,
    FieldType.COLOR,
    FieldType.FILE,
    FieldType.IMAGE,
    FieldType.GROUP,
    FieldType.ARRAY,
}

# File-type fields that cannot be handled inline even if forced
_FILE_FIELD_TYPES = {FieldType.FILE, FieldType.IMAGE}

# Maximum number of options for inline mode
_MAX_INLINE_OPTIONS = 5


def _resolve(value: LocalizedString | None, locale: str = "en") -> str:
    """Resolve a LocalizedString to a plain string.

    Args:
        value: str or locale dict.
        locale: BCP 47 locale tag.

    Returns:
        Resolved plain string.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if locale in value:
        return value[locale]
    lang = locale.split("-")[0]
    if lang in value:
        return value[lang]
    if "en" in value:
        return value["en"]
    return next(iter(value.values()), "")


def _form_hash(form_id: str) -> str:
    """Produce a short hash of a form_id for callback data.

    Args:
        form_id: The form identifier.

    Returns:
        8-character hex hash.
    """
    return hashlib.md5(form_id.encode()).hexdigest()[:8]


def _flatten_fields(form: FormSchema) -> list[FormField]:
    """Flatten all fields from all sections, excluding HIDDEN.

    Args:
        form: The form schema.

    Returns:
        Ordered list of visible fields.
    """
    fields: list[FormField] = []
    for section in form.sections:
        for field in section.fields:
            if field.field_type != FieldType.HIDDEN:
                fields.append(field)
    return fields


class TelegramRenderer(AbstractFormRenderer):
    """Renders FormSchema as Telegram interactions.

    Supports two modes:
    - **inline**: Sequential inline keyboard prompts for simple forms.
    - **webapp**: A URL to a Telegram WebApp serving the full HTML form.

    Auto-selects the mode based on form complexity, with explicit override.

    Args:
        base_url: Base URL for WebApp pages (e.g., "https://example.com").
            Falls back to config if None.
        html_renderer: Optional HTML5Renderer for WebApp mode.
    """

    def __init__(
        self,
        base_url: str | None = None,
        html_renderer: Any | None = None,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.html_renderer = html_renderer
        self.logger = logging.getLogger(__name__)

    def analyze_form(self, form: FormSchema) -> TelegramRenderMode:
        """Determine optimal rendering mode for a form.

        Rules:
        - If any field is a text-input, file, or complex type → WEBAPP.
        - If any SELECT/MULTI_SELECT has >5 options → WEBAPP.
        - If all fields are SELECT (<=5), MULTI_SELECT (<=5), BOOLEAN, or HIDDEN → INLINE.

        Args:
            form: The form schema to analyze.

        Returns:
            The recommended TelegramRenderMode.
        """
        for section in form.sections:
            for field in section.fields:
                if field.field_type in _WEBAPP_FIELD_TYPES:
                    return TelegramRenderMode.WEBAPP
                if field.field_type in (FieldType.SELECT, FieldType.MULTI_SELECT):
                    n_options = len(field.options) if field.options else 0
                    if n_options > _MAX_INLINE_OPTIONS:
                        return TelegramRenderMode.WEBAPP
        return TelegramRenderMode.INLINE

    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
        mode: TelegramRenderMode = TelegramRenderMode.AUTO,
    ) -> RenderedForm:
        """Render a FormSchema for Telegram.

        Args:
            form: The form schema to render.
            style: Optional style configuration (unused in Telegram renderer).
            locale: BCP 47 locale tag for i18n.
            prefilled: Pre-filled field values.
            errors: Validation errors.
            mode: Rendering mode. AUTO auto-detects.

        Returns:
            RenderedForm with TelegramFormPayload as content.
        """
        # Determine effective mode
        if mode == TelegramRenderMode.AUTO:
            effective_mode = self.analyze_form(form)
        else:
            effective_mode = mode

        # Safety check: inline forced but form has file fields
        if effective_mode == TelegramRenderMode.INLINE:
            has_files = any(
                field.field_type in _FILE_FIELD_TYPES
                for section in form.sections
                for field in section.fields
            )
            if has_files:
                self.logger.warning(
                    "Form '%s' has file fields but inline mode was requested. "
                    "Falling back to WebApp mode.",
                    form.form_id,
                )
                effective_mode = TelegramRenderMode.WEBAPP

        title = _resolve(form.title, locale)
        visible_fields = _flatten_fields(form)

        if effective_mode == TelegramRenderMode.INLINE:
            steps = self._build_inline_steps(form, visible_fields, locale)
            payload = TelegramFormPayload(
                mode=TelegramRenderMode.INLINE,
                form_id=form.form_id,
                form_title=title,
                steps=steps,
                total_fields=len(visible_fields),
            )
        else:
            webapp_url = f"{self.base_url}/forms/{form.form_id}/telegram"
            payload = TelegramFormPayload(
                mode=TelegramRenderMode.WEBAPP,
                form_id=form.form_id,
                form_title=title,
                webapp_url=webapp_url,
                total_fields=len(visible_fields),
            )

        return RenderedForm(
            content=payload,
            content_type="application/x-telegram-form",
            metadata={
                "mode": effective_mode.value,
                "form_id": form.form_id,
                "field_count": len(visible_fields),
            },
        )

    def _build_inline_steps(
        self,
        form: FormSchema,
        fields: list[FormField],
        locale: str,
    ) -> list[TelegramFormStep]:
        """Build inline keyboard steps for each visible field.

        Args:
            form: The form schema.
            fields: Flattened visible fields.
            locale: Locale for label resolution.

        Returns:
            List of TelegramFormStep objects.
        """
        fh = _form_hash(form.form_id)
        steps: list[TelegramFormStep] = []

        for idx, field in enumerate(fields):
            label = _resolve(field.label, locale) or field.field_id
            required_mark = " *" if field.required else ""
            message_text = f"{label}{required_mark}"

            if field.field_type == FieldType.BOOLEAN:
                keyboard = self._build_boolean_keyboard(fh, idx)
                options_list = [("true", "Yes"), ("false", "No")]
            elif field.field_type in (FieldType.SELECT, FieldType.MULTI_SELECT):
                keyboard = self._build_select_keyboard(
                    fh, idx, field.options or [], locale,
                    multi=field.field_type == FieldType.MULTI_SELECT,
                )
                options_list = [
                    (opt.value, _resolve(opt.label, locale) or opt.value)
                    for opt in (field.options or [])
                    if not opt.disabled
                ]
            else:
                continue

            steps.append(
                TelegramFormStep(
                    field_id=field.field_id,
                    message_text=message_text,
                    reply_markup=keyboard,
                    field_type=field.field_type,
                    required=field.required,
                    options=options_list,
                )
            )

        return steps

    def _build_boolean_keyboard(self, fh: str, field_idx: int) -> dict:
        """Build inline keyboard for a BOOLEAN field.

        Args:
            fh: Form hash.
            field_idx: Field index.

        Returns:
            Serialized InlineKeyboardMarkup dict.
        """
        return {
            "inline_keyboard": [
                [
                    {
                        "text": "Yes",
                        "callback_data": FormFieldCallback(
                            fh=fh, fi=field_idx, oi=1
                        ).pack(),
                    },
                    {
                        "text": "No",
                        "callback_data": FormFieldCallback(
                            fh=fh, fi=field_idx, oi=0
                        ).pack(),
                    },
                ]
            ]
        }

    def _build_select_keyboard(
        self,
        fh: str,
        field_idx: int,
        options: list[FieldOption],
        locale: str,
        multi: bool = False,
    ) -> dict:
        """Build inline keyboard for SELECT/MULTI_SELECT fields.

        Args:
            fh: Form hash.
            field_idx: Field index.
            options: Field options.
            locale: Locale for label resolution.
            multi: Whether this is a multi-select field.

        Returns:
            Serialized InlineKeyboardMarkup dict.
        """
        buttons = []
        for opt_idx, opt in enumerate(options):
            if opt.disabled:
                continue
            label = _resolve(opt.label, locale) or opt.value
            buttons.append(
                [
                    {
                        "text": label,
                        "callback_data": FormFieldCallback(
                            fh=fh, fi=field_idx, oi=opt_idx
                        ).pack(),
                    }
                ]
            )

        if multi:
            from .models import FormActionCallback

            buttons.append(
                [
                    {
                        "text": "Done",
                        "callback_data": FormActionCallback(
                            fh=fh, act="done"
                        ).pack(),
                    }
                ]
            )

        return {"inline_keyboard": buttons}
