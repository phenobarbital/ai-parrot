"""Unit tests for TelegramFormRouter."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram import Router

from parrot.formdesigner.core.options import FieldOption
from parrot.formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.renderers.telegram.models import TelegramRenderMode
from parrot.formdesigner.renderers.telegram.renderer import TelegramRenderer
from parrot.formdesigner.renderers.telegram.router import TelegramFormRouter
from parrot.formdesigner.services.registry import FormRegistry
from parrot.formdesigner.services.validators import FormValidator, ValidationResult


@pytest.fixture
def boolean_form() -> FormSchema:
    return FormSchema(
        form_id="test-bool",
        title="Boolean Test",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="q1",
                        field_type=FieldType.BOOLEAN,
                        label="Accept?",
                        required=True,
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def select_form() -> FormSchema:
    return FormSchema(
        form_id="test-sel",
        title="Select Test",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="color",
                        field_type=FieldType.SELECT,
                        label="Pick color",
                        options=[
                            FieldOption(value="red", label="Red"),
                            FieldOption(value="blue", label="Blue"),
                        ],
                    ),
                ],
            )
        ],
    )


@pytest.fixture
def mock_registry(boolean_form):
    reg = AsyncMock(spec=FormRegistry)
    reg.get = AsyncMock(return_value=boolean_form)
    return reg


@pytest.fixture
def mock_validator():
    v = AsyncMock(spec=FormValidator)
    v.validate = AsyncMock(
        return_value=ValidationResult(is_valid=True, errors={}, sanitized_data={})
    )
    return v


class TestTelegramFormRouter:
    def test_is_router(self, mock_registry):
        renderer = TelegramRenderer(base_url="https://example.com")
        router = TelegramFormRouter(renderer=renderer, registry=mock_registry)
        assert isinstance(router, Router)

    def test_has_handlers_registered(self, mock_registry):
        renderer = TelegramRenderer(base_url="https://example.com")
        router = TelegramFormRouter(renderer=renderer, registry=mock_registry)
        # Router should have callback_query and message observers
        assert router.callback_query is not None
        assert router.message is not None

    @pytest.mark.asyncio
    async def test_start_form_not_found(self, mock_registry):
        mock_registry.get = AsyncMock(return_value=None)
        renderer = TelegramRenderer(base_url="https://example.com")
        router = TelegramFormRouter(renderer=renderer, registry=mock_registry)

        bot = AsyncMock()
        state = AsyncMock()

        await router.start_form("nonexistent", 123, bot, state)
        bot.send_message.assert_called_once()
        assert "not found" in bot.send_message.call_args[0][1]

    @pytest.mark.asyncio
    async def test_start_form_inline_sends_message(self, mock_registry, boolean_form):
        renderer = TelegramRenderer(base_url="https://example.com")
        router = TelegramFormRouter(renderer=renderer, registry=mock_registry)

        bot = AsyncMock()
        state = AsyncMock()
        state.get_data = AsyncMock(return_value={})

        await router.start_form("test-bool", 123, bot, state)

        bot.send_message.assert_called_once()
        call_args = bot.send_message.call_args
        assert call_args[0][0] == 123  # chat_id
        assert "Accept?" in call_args[0][1]  # message text
        state.set_state.assert_called_once()
        state.update_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_form_webapp_sends_button(self, mock_registry):
        text_form = FormSchema(
            form_id="test-text",
            title="Text Test",
            sections=[
                FormSection(
                    section_id="s1",
                    fields=[
                        FormField(
                            field_id="name",
                            field_type=FieldType.TEXT,
                            label="Your name",
                        )
                    ],
                )
            ],
        )
        mock_registry.get = AsyncMock(return_value=text_form)
        renderer = TelegramRenderer(base_url="https://example.com")
        router = TelegramFormRouter(renderer=renderer, registry=mock_registry)

        bot = AsyncMock()
        state = AsyncMock()

        await router.start_form("test-text", 123, bot, state)

        bot.send_message.assert_called_once()
        call_kwargs = bot.send_message.call_args[1]
        assert call_kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_submit_form_valid(self, mock_registry, mock_validator):
        renderer = TelegramRenderer(base_url="https://example.com")
        on_submit = AsyncMock()
        router = TelegramFormRouter(
            renderer=renderer,
            registry=mock_registry,
            validator=mock_validator,
            on_submit=on_submit,
        )

        message = AsyncMock()
        message.chat.id = 123
        state = AsyncMock()

        await router._submit_form(message, "test-bool", {"q1": True}, state)

        mock_validator.validate.assert_called_once()
        message.edit_text.assert_called_once()
        assert "successfully" in message.edit_text.call_args[0][0].lower()
        on_submit.assert_called_once_with("test-bool", {"q1": True}, 123)
        state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_form_invalid(self, mock_registry):
        validator = AsyncMock(spec=FormValidator)
        validator.validate = AsyncMock(
            return_value=ValidationResult(
                is_valid=False,
                errors={"q1": ["This field is required"]},
                sanitized_data={},
            )
        )
        renderer = TelegramRenderer(base_url="https://example.com")
        router = TelegramFormRouter(
            renderer=renderer, registry=mock_registry, validator=validator
        )

        message = AsyncMock()
        message.chat.id = 123
        state = AsyncMock()

        await router._submit_form(message, "test-bool", {}, state)

        message.edit_text.assert_called_once()
        assert "error" in message.edit_text.call_args[0][0].lower()
        state.clear.assert_called_once()
