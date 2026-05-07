"""Unit tests for ``parrot_formdesigner.renderers.pdf.PdfRenderer``."""

from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfReader

from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSection,
    RenderedForm,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.base import AbstractFormRenderer
from parrot_formdesigner.renderers.pdf import PdfRenderer


@pytest.fixture
def form_with_unsupported() -> FormSchema:
    return FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "Name"},
                    ),
                    FormField(
                        field_id="active",
                        field_type=FieldType.BOOLEAN,
                        label={"en": "Active"},
                    ),
                    FormField(
                        field_id="avatar",
                        field_type=FieldType.FILE,
                        label={"en": "Avatar"},
                    ),
                    FormField(
                        field_id="role",
                        field_type=FieldType.SELECT,
                        label={"en": "Role"},
                        options=[
                            FieldOption(value="admin", label={"en": "Admin"}),
                            FieldOption(value="user", label={"en": "User"}),
                        ],
                    ),
                ],
            )
        ],
    )


def test_renderer_is_abstract_subclass():
    assert issubclass(PdfRenderer, AbstractFormRenderer)


async def test_returns_pdf(form_with_unsupported):
    out = await PdfRenderer().render(form_with_unsupported)
    assert isinstance(out, RenderedForm)
    assert out.content_type == "application/pdf"
    reader = PdfReader(BytesIO(out.content))
    assert len(reader.pages) >= 1


async def test_acroform_present(form_with_unsupported):
    out = await PdfRenderer().render(form_with_unsupported)
    reader = PdfReader(BytesIO(out.content))
    root = reader.trailer["/Root"]
    assert "/AcroForm" in root


async def test_unsupported_field_listed_in_metadata(form_with_unsupported):
    out = await PdfRenderer().render(form_with_unsupported)
    unsupported = out.metadata["unsupported_fields"]
    types = {f["field_type"] for f in unsupported}
    assert "file" in types
    ids = {f["field_id"] for f in unsupported}
    assert "avatar" in ids


async def test_text_field_in_acroform(form_with_unsupported):
    out = await PdfRenderer().render(form_with_unsupported)
    reader = PdfReader(BytesIO(out.content))
    fields = reader.get_fields() or {}
    assert "name" in fields


async def test_supported_form_with_only_text():
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "Name"},
                    ),
                ],
            )
        ],
    )
    out = await PdfRenderer().render(form)
    assert out.metadata["unsupported_fields"] == []


async def test_image_array_group_all_unsupported():
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(
                        field_id="img",
                        field_type=FieldType.IMAGE,
                        label={"en": "Image"},
                    ),
                    FormField(
                        field_id="arr",
                        field_type=FieldType.ARRAY,
                        label={"en": "Array"},
                        item_template=FormField(
                            field_id="row",
                            field_type=FieldType.TEXT,
                            label={"en": "Row"},
                        ),
                    ),
                    FormField(
                        field_id="grp",
                        field_type=FieldType.GROUP,
                        label={"en": "Group"},
                        children=[
                            FormField(
                                field_id="inner",
                                field_type=FieldType.TEXT,
                                label={"en": "Inner"},
                            ),
                        ],
                    ),
                ],
            )
        ],
    )
    out = await PdfRenderer().render(form)
    types = {f["field_type"] for f in out.metadata["unsupported_fields"]}
    assert types == {"image", "array", "group"}


async def test_select_renders_choice():
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(
                        field_id="role",
                        field_type=FieldType.SELECT,
                        label={"en": "Role"},
                        options=[
                            FieldOption(value="a", label={"en": "A"}),
                            FieldOption(value="b", label={"en": "B"}),
                        ],
                    ),
                ],
            )
        ],
    )
    out = await PdfRenderer().render(form)
    reader = PdfReader(BytesIO(out.content))
    fields = reader.get_fields() or {}
    assert "role" in fields


async def test_unsupported_meta_carries_section_id():
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="personal",
                fields=[
                    FormField(
                        field_id="resume",
                        field_type=FieldType.FILE,
                        label={"en": "Resume"},
                    ),
                ],
            )
        ],
    )
    out = await PdfRenderer().render(form)
    entry = out.metadata["unsupported_fields"][0]
    assert entry["section_id"] == "personal"
    assert entry["field_id"] == "resume"
    assert entry["field_type"] == "file"
