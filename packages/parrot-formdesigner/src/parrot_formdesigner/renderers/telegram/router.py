"""Telegram form conversation router.

An aiogram Router that handles multi-step form conversations via inline
keyboards (FSMContext) and WebApp data submissions.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from ...core.schema import FormSchema
from ...services.registry import FormRegistry
from ...services.validators import FormValidator
from .models import (
    FormActionCallback,
    FormFieldCallback,
    TelegramFormPayload,
    TelegramFormStep,
    TelegramRenderMode,
)
from .renderer import TelegramRenderer

logger = logging.getLogger(__name__)


class FormFilling(StatesGroup):
    """FSM state for an active form conversation."""

    active = State()


class TelegramFormRouter(Router):
    """aiogram Router that handles form conversations.

    Supports inline keyboard multi-step flows via FSMContext and
    WebApp data reception. Can be included in any aiogram Dispatcher.

    Args:
        renderer: TelegramRenderer for rendering forms.
        registry: FormRegistry for looking up forms by ID.
        validator: Optional FormValidator. Created if not provided.
        on_submit: Optional callback invoked after successful validation.
            Signature: ``async def on_submit(form_id, data, chat_id) -> None``
    """

    def __init__(
        self,
        renderer: TelegramRenderer,
        registry: FormRegistry,
        validator: FormValidator | None = None,
        on_submit: Callable | None = None,
    ) -> None:
        super().__init__()
        self.renderer = renderer
        self.registry = registry
        self.validator = validator or FormValidator()
        self.on_submit = on_submit
        self.logger = logging.getLogger(__name__)

        # Register handlers
        self.callback_query.register(
            self._handle_field_callback, FormFieldCallback.filter()
        )
        self.callback_query.register(
            self._handle_action_callback, FormActionCallback.filter()
        )
        self.message.register(self._handle_webapp_data, F.web_app_data)

    async def start_form(
        self,
        form_id: str,
        chat_id: int,
        bot: Bot,
        state: FSMContext,
        mode: TelegramRenderMode = TelegramRenderMode.AUTO,
    ) -> None:
        """Initiate a form conversation in the given chat.

        Args:
            form_id: ID of the form to present.
            chat_id: Telegram chat ID.
            bot: aiogram Bot instance.
            state: FSMContext for this chat.
            mode: Rendering mode override.
        """
        form = await self.registry.get(form_id)
        if form is None:
            await bot.send_message(chat_id, f"Form '{form_id}' not found.")
            return

        result = await self.renderer.render(form, mode=mode)
        payload: TelegramFormPayload = result.content

        if payload.mode == TelegramRenderMode.WEBAPP:
            await self._start_webapp(payload, chat_id, bot)
        else:
            await self._start_inline(payload, form_id, chat_id, bot, state)

    async def _start_webapp(
        self,
        payload: TelegramFormPayload,
        chat_id: int,
        bot: Bot,
    ) -> None:
        """Send a WebApp button for the form.

        Args:
            payload: Rendered form payload.
            chat_id: Telegram chat ID.
            bot: aiogram Bot instance.
        """
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"Open: {payload.form_title}",
                        web_app=WebAppInfo(url=payload.webapp_url),
                    )
                ]
            ]
        )
        await bot.send_message(
            chat_id,
            f"Please fill out the form: *{payload.form_title}*",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    async def _start_inline(
        self,
        payload: TelegramFormPayload,
        form_id: str,
        chat_id: int,
        bot: Bot,
        state: FSMContext,
    ) -> None:
        """Start inline keyboard form flow.

        Args:
            payload: Rendered form payload with steps.
            form_id: Form identifier.
            chat_id: Telegram chat ID.
            bot: aiogram Bot instance.
            state: FSMContext for tracking progress.
        """
        if not payload.steps:
            await bot.send_message(chat_id, "This form has no fields to fill.")
            return

        # Store form state
        steps_data = [s.model_dump() for s in payload.steps]
        await state.set_state(FormFilling.active)
        await state.update_data(
            form_id=form_id,
            current_field_idx=0,
            answers={},
            steps=steps_data,
            multi_select_current={},
        )

        # Send first field
        step = payload.steps[0]
        await bot.send_message(
            chat_id,
            step.message_text,
            reply_markup=InlineKeyboardMarkup(**step.reply_markup),
        )

    async def _handle_field_callback(
        self,
        query: CallbackQuery,
        callback_data: FormFieldCallback,
        state: FSMContext,
    ) -> None:
        """Handle an inline keyboard field selection.

        Args:
            query: The callback query from Telegram.
            callback_data: Parsed callback data.
            state: FSMContext for this conversation.
        """
        await query.answer()

        data = await state.get_data()
        if not data:
            await query.message.edit_text("Session expired. Please start the form again.")
            return

        steps_data = data.get("steps", [])
        current_idx = data.get("current_field_idx", 0)
        answers = data.get("answers", {})
        multi_current = data.get("multi_select_current", {})

        if callback_data.fi >= len(steps_data):
            return

        step = TelegramFormStep.model_validate(steps_data[callback_data.fi])

        # Handle MULTI_SELECT toggle
        if step.field_type == "multi_select":
            field_key = step.field_id
            selected = set(multi_current.get(field_key, []))
            opt_idx = callback_data.oi

            if step.options and 0 <= opt_idx < len(step.options):
                opt_value = step.options[opt_idx][0]
                if opt_value in selected:
                    selected.discard(opt_value)
                else:
                    selected.add(opt_value)

                multi_current[field_key] = list(selected)
                await state.update_data(multi_select_current=multi_current)

                # Rebuild keyboard with checkmarks
                keyboard = self._rebuild_multiselect_keyboard(
                    step, callback_data.fh, callback_data.fi, selected
                )
                await query.message.edit_reply_markup(reply_markup=keyboard)
            return

        # Handle BOOLEAN and SELECT
        if step.field_type == "boolean":
            answers[step.field_id] = callback_data.oi == 1
        elif step.options and 0 <= callback_data.oi < len(step.options):
            answers[step.field_id] = step.options[callback_data.oi][0]

        # Advance to next field
        next_idx = current_idx + 1
        await state.update_data(current_field_idx=next_idx, answers=answers)

        if next_idx < len(steps_data):
            next_step = TelegramFormStep.model_validate(steps_data[next_idx])
            await query.message.edit_text(
                next_step.message_text,
                reply_markup=InlineKeyboardMarkup(**next_step.reply_markup),
            )
        else:
            # All fields done → show summary
            await self._show_summary(query.message, data["form_id"], answers, state)

    async def _handle_action_callback(
        self,
        query: CallbackQuery,
        callback_data: FormActionCallback,
        state: FSMContext,
    ) -> None:
        """Handle form-level actions (submit, cancel, done for multi-select).

        Args:
            query: The callback query from Telegram.
            callback_data: Parsed callback data.
            state: FSMContext for this conversation.
        """
        await query.answer()

        data = await state.get_data()
        if not data:
            await query.message.edit_text("Session expired.")
            return

        if callback_data.act == "done":
            # Finalize multi-select: move selected values to answers and advance
            multi_current = data.get("multi_select_current", {})
            answers = data.get("answers", {})
            steps_data = data.get("steps", [])
            current_idx = data.get("current_field_idx", 0)

            if current_idx < len(steps_data):
                step = TelegramFormStep.model_validate(steps_data[current_idx])
                selected = multi_current.get(step.field_id, [])
                answers[step.field_id] = selected

            next_idx = current_idx + 1
            await state.update_data(current_field_idx=next_idx, answers=answers)

            if next_idx < len(steps_data):
                next_step = TelegramFormStep.model_validate(steps_data[next_idx])
                await query.message.edit_text(
                    next_step.message_text,
                    reply_markup=InlineKeyboardMarkup(**next_step.reply_markup),
                )
            else:
                await self._show_summary(
                    query.message, data["form_id"], answers, state
                )

        elif callback_data.act == "submit":
            answers = data.get("answers", {})
            form_id = data.get("form_id")
            await self._submit_form(query.message, form_id, answers, state)

        elif callback_data.act == "cancel":
            await state.clear()
            await query.message.edit_text("Form cancelled.")

    async def _show_summary(
        self,
        message: Message,
        form_id: str,
        answers: dict[str, Any],
        state: FSMContext,
    ) -> None:
        """Show a summary of answers with Submit/Cancel buttons.

        Args:
            message: Message to edit.
            form_id: Form identifier.
            answers: Collected answers.
            state: FSMContext.
        """
        from .renderer import _form_hash

        fh = _form_hash(form_id)
        lines = ["*Summary*\n"]
        data = await state.get_data()
        steps_data = data.get("steps", [])

        for step_data in steps_data:
            step = TelegramFormStep.model_validate(step_data)
            value = answers.get(step.field_id, "—")
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value) or "—"
            label = step.message_text.rstrip(" *")
            lines.append(f"  {label}: {value}")

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Submit",
                        callback_data=FormActionCallback(fh=fh, act="submit").pack(),
                    ),
                    InlineKeyboardButton(
                        text="Cancel",
                        callback_data=FormActionCallback(fh=fh, act="cancel").pack(),
                    ),
                ]
            ]
        )

        await message.edit_text(
            "\n".join(lines), reply_markup=keyboard, parse_mode="Markdown"
        )

    async def _submit_form(
        self,
        message: Message,
        form_id: str,
        answers: dict[str, Any],
        state: FSMContext,
    ) -> None:
        """Validate and submit the form.

        Args:
            message: Message to edit with result.
            form_id: Form identifier.
            answers: Collected answers dict.
            state: FSMContext to clear on completion.
        """
        form = await self.registry.get(form_id)
        if form is None:
            await message.edit_text("Form not found. Submission failed.")
            await state.clear()
            return

        result = await self.validator.validate(form, answers)

        if result.is_valid:
            await message.edit_text("Form submitted successfully!")
            if self.on_submit:
                chat_id = message.chat.id
                try:
                    await self.on_submit(form_id, answers, chat_id)
                except Exception:
                    self.logger.exception(
                        "on_submit callback failed for form '%s'", form_id
                    )
        else:
            error_lines = ["Validation errors:\n"]
            for field_id, errs in result.errors.items():
                for err in errs:
                    error_lines.append(f"  {field_id}: {err}")
            await message.edit_text("\n".join(error_lines))

        await state.clear()

    async def _handle_webapp_data(self, message: Message, state: FSMContext) -> None:
        """Handle form submission from Telegram WebApp.

        Args:
            message: Message containing web_app_data.
            state: FSMContext (cleared after processing).
        """
        if not message.web_app_data:
            return

        try:
            payload = json.loads(message.web_app_data.data)
        except (json.JSONDecodeError, TypeError):
            await message.answer("Invalid form data received.")
            return

        form_id = payload.pop("_form_id", None)
        if not form_id:
            await message.answer("Missing form identifier in submission.")
            return

        form = await self.registry.get(form_id)
        if form is None:
            await message.answer(f"Form '{form_id}' not found.")
            return

        result = await self.validator.validate(form, payload)

        if result.is_valid:
            await message.answer("Form submitted successfully!")
            if self.on_submit:
                try:
                    await self.on_submit(form_id, payload, message.chat.id)
                except Exception:
                    self.logger.exception(
                        "on_submit callback failed for form '%s'", form_id
                    )
        else:
            error_lines = ["Validation errors:\n"]
            for field_id, errs in result.errors.items():
                for err in errs:
                    error_lines.append(f"  {field_id}: {err}")
            await message.answer("\n".join(error_lines))

        await state.clear()

    def _rebuild_multiselect_keyboard(
        self,
        step: TelegramFormStep,
        fh: str,
        field_idx: int,
        selected: set[str],
    ) -> InlineKeyboardMarkup:
        """Rebuild a multi-select keyboard with checkmarks for selected items.

        Args:
            step: The form step definition.
            fh: Form hash.
            field_idx: Field index.
            selected: Set of currently selected option values.

        Returns:
            Updated InlineKeyboardMarkup.
        """
        buttons = []
        for opt_idx, (opt_value, opt_label) in enumerate(step.options or []):
            check = "\u2705 " if opt_value in selected else ""
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"{check}{opt_label}",
                        callback_data=FormFieldCallback(
                            fh=fh, fi=field_idx, oi=opt_idx
                        ).pack(),
                    )
                ]
            )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="Done",
                    callback_data=FormActionCallback(fh=fh, act="done").pack(),
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=buttons)
