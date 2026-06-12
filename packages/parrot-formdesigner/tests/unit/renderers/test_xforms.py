"""Unit tests for ``parrot_formdesigner.renderers.xforms.XFormsRenderer``."""

from __future__ import annotations

import pytest
from lxml import etree

from parrot_formdesigner.core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldCondition,
    FieldConstraints,
    FieldRefCondition,
)
from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSection,
    RenderedForm,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.base import AbstractFormRenderer
from parrot_formdesigner.renderers.xforms import XFormsRenderer


XF = "{http://www.w3.org/2002/xforms}"


@pytest.fixture
def simple_form() -> FormSchema:
    return FormSchema(
        form_id="t",
        title={"en": "Test"},
        sections=[
            FormSection(
                section_id="s1",
                title={"en": "Section 1"},
                fields=[
                    FormField(
                        field_id="name",
                        field_type=FieldType.TEXT,
                        label={"en": "Name"},
                        required=True,
                    ),
                    FormField(
                        field_id="age",
                        field_type=FieldType.INTEGER,
                        label={"en": "Age"},
                        constraints=FieldConstraints(min_value=0, max_value=120),
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
    assert issubclass(XFormsRenderer, AbstractFormRenderer)


async def test_render_returns_xml(simple_form):
    out = await XFormsRenderer().render(simple_form)
    assert isinstance(out, RenderedForm)
    assert out.content_type == "application/xml"
    root = etree.fromstring(out.content)
    assert root.nsmap.get("xf") == "http://www.w3.org/2002/xforms"


async def test_section_emits_xf_group(simple_form):
    out = await XFormsRenderer().render(simple_form)
    root = etree.fromstring(out.content)
    groups = root.findall(f"./{XF}group")
    assert len(groups) == 1
    assert groups[0].get("id") == "s1"


async def test_required_field_has_bind(simple_form):
    out = await XFormsRenderer().render(simple_form)
    root = etree.fromstring(out.content)
    binds = root.findall(f".//{XF}bind[@required='true()']")
    assert len(binds) >= 1
    assert any(b.get("nodeset", "").endswith("name") for b in binds)


async def test_constraint_min_max(simple_form):
    out = await XFormsRenderer().render(simple_form)
    root = etree.fromstring(out.content)
    bind = next(
        b
        for b in root.findall(f".//{XF}bind")
        if b.get("nodeset", "").endswith("age")
    )
    constraint = bind.get("constraint", "")
    assert ">= 0" in constraint
    assert "<= 120" in constraint
    assert " and " in constraint


async def test_max_length_constraint():
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(
                        field_id="comment",
                        field_type=FieldType.TEXT,
                        label={"en": "Comment"},
                        constraints=FieldConstraints(max_length=10),
                    ),
                ],
            )
        ],
    )
    out = await XFormsRenderer().render(form)
    root = etree.fromstring(out.content)
    bind = next(
        b
        for b in root.findall(f".//{XF}bind")
        if b.get("nodeset", "").endswith("comment")
    )
    assert "string-length(.) <= 10" in bind.get("constraint", "")


async def test_select_emits_select1(simple_form):
    out = await XFormsRenderer().render(simple_form)
    root = etree.fromstring(out.content)
    select1 = root.findall(f".//{XF}select1")
    assert len(select1) == 1
    items = select1[0].findall(f"{XF}item")
    assert len(items) == 2


async def test_multi_select_emits_select():
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(
                        field_id="skills",
                        field_type=FieldType.MULTI_SELECT,
                        label={"en": "Skills"},
                        options=[
                            FieldOption(value="py", label={"en": "Python"}),
                        ],
                    ),
                ],
            )
        ],
    )
    out = await XFormsRenderer().render(form)
    root = etree.fromstring(out.content)
    select = root.findall(f".//{XF}select")
    assert len(select) == 1


async def test_file_emits_xf_upload():
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s",
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
    out = await XFormsRenderer().render(form)
    root = etree.fromstring(out.content)
    uploads = root.findall(f".//{XF}upload")
    assert len(uploads) == 1


async def test_image_upload_has_mediatype():
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(
                        field_id="photo",
                        field_type=FieldType.IMAGE,
                        label={"en": "Photo"},
                    ),
                ],
            )
        ],
    )
    out = await XFormsRenderer().render(form)
    root = etree.fromstring(out.content)
    uploads = root.findall(f".//{XF}upload")
    assert uploads[0].get("mediatype") == "image/*"


async def test_relevant_xpath_for_simple_dependency():
    form = FormSchema(
        form_id="t",
        title={"en": "T"},
        sections=[
            FormSection(
                section_id="s",
                fields=[
                    FormField(
                        field_id="parent",
                        field_type=FieldType.TEXT,
                        label={"en": "Parent"},
                    ),
                    FormField(
                        field_id="child",
                        field_type=FieldType.TEXT,
                        label={"en": "Child"},
                        depends_on=DependencyRule(
                            conditions=[
                                FieldRefCondition(
                                    field_id="parent",
                                    operator=ConditionOperator.EQ,
                                    value="show",
                                )
                            ]
                        ),
                    ),
                ],
            )
        ],
    )
    out = await XFormsRenderer().render(form)
    root = etree.fromstring(out.content)
    bind = next(
        b
        for b in root.findall(f".//{XF}bind")
        if b.get("nodeset", "").endswith("child")
    )
    rel = bind.get("relevant", "")
    assert "parent" in rel
    assert "show" in rel


async def test_xsd_types_in_binds(simple_form):
    out = await XFormsRenderer().render(simple_form)
    root = etree.fromstring(out.content)
    binds = root.findall(f".//{XF}bind")
    types = {b.get("type") for b in binds}
    assert "xs:string" in types
    assert "xs:integer" in types


async def test_passes_lxml_parse(simple_form):
    """Output is well-formed XML."""
    out = await XFormsRenderer().render(simple_form)
    parsed = etree.fromstring(out.content)
    assert parsed is not None
