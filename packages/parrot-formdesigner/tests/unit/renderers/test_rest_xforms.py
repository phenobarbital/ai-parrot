"""Unit tests for FieldType.REST fallback in XFormsRenderer — FEAT-170."""

from __future__ import annotations

import pytest
from lxml import etree

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.xforms import XFormsRenderer


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
# XForms fallback REST rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_xforms_rest_produces_xml(form_with_rest: FormSchema) -> None:
    """XFormsRenderer must produce valid XML bytes with REST field."""
    out = await XFormsRenderer().render(form_with_rest)
    assert isinstance(out, RenderedForm)
    assert out.content_type == "application/xml"
    # Must parse without error
    root = etree.fromstring(out.content)
    assert root is not None


@pytest.mark.asyncio
async def test_xforms_rest_field_in_data_tree(form_with_rest: FormSchema) -> None:
    """XForms data tree must include the REST field_id node."""
    out = await XFormsRenderer().render(form_with_rest)
    root = etree.fromstring(out.content)
    # The data tree is in the xf:model/xf:instance/data/<section_id>/<field_id>
    ns = {"xf": "http://www.w3.org/2002/xforms"}
    nodes = root.findall(".//upload_photo")
    assert len(nodes) >= 1


@pytest.mark.asyncio
async def test_xforms_rest_in_field_to_xforms_map() -> None:
    """FieldType.REST must be present in the _FIELD_TO_XFORMS mapping."""
    from parrot_formdesigner.renderers.xforms import _FIELD_TO_XFORMS

    assert FieldType.REST in _FIELD_TO_XFORMS
