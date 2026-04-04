"""Unit tests for TelegramRenderer."""

import logging

import pytest

from parrot.formdesigner.core.options import FieldOption
from parrot.formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot.formdesigner.core.types import FieldType
from parrot.formdesigner.renderers.telegram.models import TelegramRenderMode
from parrot.formdesigner.renderers.telegram.renderer import TelegramRenderer


def _make_form(fields: list[FormField], form_id: str = "test") -> FormSchema:
    return FormSchema(
        form_id=form_id,
        title="Test Form",
        sections=[FormSection(section_id="s1", fields=fields)],
    )


def _select_field(n_options: int = 3, field_id: str = "sel") -> FormField:
    return FormField(
        field_id=field_id,
        field_type=FieldType.SELECT,
        label="Pick one",
        options=[
            FieldOption(value=f"v{i}", label=f"Option {i}") for i in range(n_options)
        ],
    )


def _multi_select_field(n_options: int = 3, field_id: str = "msel") -> FormField:
    return FormField(
        field_id=field_id,
        field_type=FieldType.MULTI_SELECT,
        label="Pick many",
        options=[
            FieldOption(value=f"v{i}", label=f"Option {i}") for i in range(n_options)
        ],
    )


class TestAnalyzeForm:
    def test_select_only_inline(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_select_field(3)])
        assert renderer.analyze_form(form) == TelegramRenderMode.INLINE

    def test_boolean_only_inline(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form(
            [FormField(field_id="ok", field_type=FieldType.BOOLEAN, label="OK?")]
        )
        assert renderer.analyze_form(form) == TelegramRenderMode.INLINE

    def test_multi_select_inline(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_multi_select_field(4)])
        assert renderer.analyze_form(form) == TelegramRenderMode.INLINE

    def test_text_field_webapp(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form(
            [FormField(field_id="name", field_type=FieldType.TEXT, label="Name")]
        )
        assert renderer.analyze_form(form) == TelegramRenderMode.WEBAPP

    def test_file_field_webapp(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form(
            [FormField(field_id="doc", field_type=FieldType.FILE, label="Upload")]
        )
        assert renderer.analyze_form(form) == TelegramRenderMode.WEBAPP

    def test_many_options_webapp(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_select_field(10)])
        assert renderer.analyze_form(form) == TelegramRenderMode.WEBAPP

    def test_boundary_5_options_inline(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_select_field(5)])
        assert renderer.analyze_form(form) == TelegramRenderMode.INLINE

    def test_boundary_6_options_webapp(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_select_field(6)])
        assert renderer.analyze_form(form) == TelegramRenderMode.WEBAPP

    def test_mixed_boolean_select_inline(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([
            FormField(field_id="ok", field_type=FieldType.BOOLEAN, label="OK?"),
            _select_field(3),
        ])
        assert renderer.analyze_form(form) == TelegramRenderMode.INLINE

    def test_mixed_text_select_webapp(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([
            _select_field(3),
            FormField(field_id="name", field_type=FieldType.TEXT, label="Name"),
        ])
        assert renderer.analyze_form(form) == TelegramRenderMode.WEBAPP

    def test_hidden_only_inline(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form(
            [FormField(field_id="h1", field_type=FieldType.HIDDEN, label="")]
        )
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
        assert payload.steps[0].field_id == "sel"

    @pytest.mark.asyncio
    async def test_inline_boolean_buttons(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form(
            [FormField(field_id="ok", field_type=FieldType.BOOLEAN, label="OK?")]
        )
        result = await renderer.render(form, mode=TelegramRenderMode.INLINE)
        step = result.content.steps[0]
        buttons = step.reply_markup["inline_keyboard"][0]
        assert len(buttons) == 2
        assert buttons[0]["text"] == "Yes"
        assert buttons[1]["text"] == "No"

    @pytest.mark.asyncio
    async def test_inline_multiselect_has_done(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_multi_select_field(3)])
        result = await renderer.render(form, mode=TelegramRenderMode.INLINE)
        step = result.content.steps[0]
        keyboard = step.reply_markup["inline_keyboard"]
        last_row = keyboard[-1]
        assert last_row[0]["text"] == "Done"

    @pytest.mark.asyncio
    async def test_webapp_render_produces_url(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form(
            [FormField(field_id="name", field_type=FieldType.TEXT, label="Name")]
        )
        result = await renderer.render(form)
        payload = result.content
        assert payload.mode == TelegramRenderMode.WEBAPP
        assert payload.webapp_url == "https://example.com/forms/test/telegram"

    @pytest.mark.asyncio
    async def test_explicit_webapp_override(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_select_field(3)])
        result = await renderer.render(form, mode=TelegramRenderMode.WEBAPP)
        assert result.content.mode == TelegramRenderMode.WEBAPP

    @pytest.mark.asyncio
    async def test_inline_forced_with_file_falls_back(self, caplog):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form(
            [FormField(field_id="f", field_type=FieldType.FILE, label="File")]
        )
        with caplog.at_level(logging.WARNING):
            result = await renderer.render(form, mode=TelegramRenderMode.INLINE)
        assert result.content.mode == TelegramRenderMode.WEBAPP
        assert "file fields" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_content_type(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_select_field(3)])
        result = await renderer.render(form)
        assert result.content_type == "application/x-telegram-form"

    @pytest.mark.asyncio
    async def test_metadata_populated(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([_select_field(3)])
        result = await renderer.render(form)
        assert result.metadata["form_id"] == "test"
        assert result.metadata["field_count"] == 1

    @pytest.mark.asyncio
    async def test_hidden_fields_excluded_from_steps(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([
            FormField(field_id="h", field_type=FieldType.HIDDEN, label=""),
            _select_field(3),
        ])
        result = await renderer.render(form, mode=TelegramRenderMode.INLINE)
        assert len(result.content.steps) == 1
        assert result.content.steps[0].field_id == "sel"

    @pytest.mark.asyncio
    async def test_required_field_marker(self):
        renderer = TelegramRenderer(base_url="https://example.com")
        form = _make_form([
            FormField(
                field_id="q",
                field_type=FieldType.BOOLEAN,
                label="Required?",
                required=True,
            )
        ])
        result = await renderer.render(form, mode=TelegramRenderMode.INLINE)
        assert result.content.steps[0].message_text == "Required? *"
