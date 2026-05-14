"""Unit tests for FieldType.REST in TelegramRenderer — FEAT-170."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.telegram.renderer import (
    TelegramRenderer,
    TelegramRenderMode,
    _WEBAPP_FIELD_TYPES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rest_field() -> FormField:
    return FormField(
        field_id="upload_photo",
        field_type=FieldType.REST,
        label={"en": "Upload Photo"},
        required=False,
        meta={
            "rest": {
                "mode": "callback",
                "callback_ref": "photo_analysis",
            }
        },
    )


@pytest.fixture
def form_with_rest(rest_field: FormField) -> FormSchema:
    return FormSchema(
        form_id="demo",
        title={"en": "Demo"},
        sections=[FormSection(section_id="s1", fields=[rest_field])],
    )


# ---------------------------------------------------------------------------
# Telegram WebApp redirect for REST
# ---------------------------------------------------------------------------


def test_rest_in_webapp_field_types() -> None:
    """FieldType.REST must be in _WEBAPP_FIELD_TYPES (force WebApp mode)."""
    assert FieldType.REST in _WEBAPP_FIELD_TYPES


def test_analyze_form_rest_returns_webapp(form_with_rest: FormSchema) -> None:
    """analyze_form must return WEBAPP mode when form contains REST field."""
    renderer = TelegramRenderer(base_url="https://example.com")
    mode = renderer.analyze_form(form_with_rest)
    assert mode == TelegramRenderMode.WEBAPP


@pytest.mark.asyncio
async def test_telegram_rest_renders_webapp(form_with_rest: FormSchema) -> None:
    """TelegramRenderer must produce WEBAPP payload for forms with REST fields."""
    renderer = TelegramRenderer(base_url="https://example.com")
    out = await renderer.render(form_with_rest)
    assert isinstance(out, RenderedForm)
    payload = out.content
    assert payload.mode == TelegramRenderMode.WEBAPP


@pytest.mark.asyncio
async def test_telegram_rest_does_not_crash(form_with_rest: FormSchema) -> None:
    """TelegramRenderer must not crash when rendering a form with REST field."""
    renderer = TelegramRenderer(base_url="https://example.com")
    out = await renderer.render(form_with_rest)
    assert out is not None
