"""Unit tests for FieldType.REST fallback in AdaptiveCardRenderer — FEAT-170."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer


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
# Adaptive Card fallback REST rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adaptive_card_rest_fallback_warns(form_with_rest: FormSchema) -> None:
    """AdaptiveCardRenderer must emit RenderWarning for FieldType.REST."""
    out = await AdaptiveCardRenderer().render(form_with_rest)
    assert isinstance(out, RenderedForm)
    rest_warnings = [w for w in out.warnings if w.field_type == "rest"]
    assert len(rest_warnings) >= 1


@pytest.mark.asyncio
async def test_adaptive_card_rest_warning_field_id(form_with_rest: FormSchema) -> None:
    """RenderWarning must reference the correct field_id."""
    out = await AdaptiveCardRenderer().render(form_with_rest)
    rest_warnings = [w for w in out.warnings if w.field_type == "rest"]
    assert rest_warnings[0].field_id == "upload_photo"


@pytest.mark.asyncio
async def test_adaptive_card_rest_warning_renderer(form_with_rest: FormSchema) -> None:
    """RenderWarning must identify renderer as 'adaptive_card'."""
    out = await AdaptiveCardRenderer().render(form_with_rest)
    rest_warnings = [w for w in out.warnings if w.field_type == "rest"]
    assert rest_warnings[0].renderer == "adaptive_card"


@pytest.mark.asyncio
async def test_adaptive_card_rest_still_produces_card(form_with_rest: FormSchema) -> None:
    """AdaptiveCardRenderer must still produce a valid card dict with REST field."""
    out = await AdaptiveCardRenderer().render(form_with_rest)
    assert out.content_type == "application/vnd.microsoft.card.adaptive"
    assert isinstance(out.content, dict)
    assert out.content.get("type") == "AdaptiveCard"
