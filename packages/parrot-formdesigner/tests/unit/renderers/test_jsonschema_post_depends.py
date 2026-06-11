"""Tests for FEAT-234 TASK-1527: JsonSchemaRenderer emits x-post-depends + serialized operations."""

import pytest

from parrot_formdesigner.core import (
    ConditionOperator,
    DependencyOperation,
    DependencyRule,
    FieldCondition,
    FieldType,
    FormField,
    FormSchema,
    FormSection,
    PostDependency,
)
from parrot_formdesigner.renderers import JsonSchemaRenderer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field(
    field_id: str,
    field_type: FieldType = FieldType.TEXT,
    *,
    depends_on: DependencyRule | None = None,
    post_depends: list[PostDependency] | None = None,
) -> FormField:
    return FormField(
        field_id=field_id,
        field_type=field_type,
        label=field_id,
        depends_on=depends_on,
        post_depends=post_depends,
    )


def _form(*fields: FormField) -> FormSchema:
    return FormSchema(
        form_id="test",
        title="Test",
        sections=[FormSection(section_id="s1", fields=list(fields))],
    )


def _cond(field_id: str = "f1") -> FieldCondition:
    return FieldCondition(field_id=field_id, operator=ConditionOperator.EQ, value="x")


@pytest.fixture
def renderer() -> JsonSchemaRenderer:
    return JsonSchemaRenderer()


# ---------------------------------------------------------------------------
# x-post-depends emission
# ---------------------------------------------------------------------------


class TestJsonSchemaPostDepends:
    @pytest.mark.asyncio
    async def test_emits_x_post_depends(self, renderer: JsonSchemaRenderer) -> None:
        """A field with post_depends emits 'x-post-depends' in the rendered property."""
        f1 = _field(
            "f1",
            post_depends=[PostDependency(target="f2", effect="show")],
        )
        f2 = _field("f2")
        form = _form(f1, f2)

        result = await renderer.render(form)
        schema = result.content
        props = schema["properties"]

        assert "x-post-depends" in props["f1"], (
            "'x-post-depends' key missing from rendered f1 property"
        )
        post_list = props["f1"]["x-post-depends"]
        assert isinstance(post_list, list)
        assert len(post_list) == 1
        assert post_list[0]["target"] == "f2"
        assert post_list[0]["effect"] == "show"

    @pytest.mark.asyncio
    async def test_no_post_depends_key_when_absent(self, renderer: JsonSchemaRenderer) -> None:
        """A field without post_depends does NOT have 'x-post-depends' in output."""
        f1 = _field("f1")
        form = _form(f1)

        result = await renderer.render(form)
        props = result.content["properties"]
        assert "x-post-depends" not in props["f1"]

    @pytest.mark.asyncio
    async def test_x_post_depends_serializes_operation(self, renderer: JsonSchemaRenderer) -> None:
        """post_depends with a set/calc operation serializes the operation dict."""
        f1 = _field(
            "f1",
            post_depends=[
                PostDependency(
                    target="f2",
                    effect="set",
                    operation=DependencyOperation(op="copy", operands=["f1"], target="f2"),
                )
            ],
        )
        f2 = _field("f2")
        form = _form(f1, f2)

        result = await renderer.render(form)
        post_list = result.content["properties"]["f1"]["x-post-depends"]
        assert len(post_list) == 1
        entry = post_list[0]
        assert entry["effect"] == "set"
        assert entry["operation"] is not None
        assert entry["operation"]["op"] == "copy"

    @pytest.mark.asyncio
    async def test_multiple_post_depends_serialized(self, renderer: JsonSchemaRenderer) -> None:
        """Multiple post_depends entries are all serialized in order."""
        f1 = _field(
            "f1",
            post_depends=[
                PostDependency(target="f2", effect="show"),
                PostDependency(target="f3", effect="cascade_clear"),
            ],
        )
        f2 = _field("f2")
        f3 = _field("f3")
        form = _form(f1, f2, f3)

        result = await renderer.render(form)
        post_list = result.content["properties"]["f1"]["x-post-depends"]
        assert len(post_list) == 2
        assert post_list[0]["target"] == "f2"
        assert post_list[1]["target"] == "f3"


# ---------------------------------------------------------------------------
# Legacy x-depends-on unchanged
# ---------------------------------------------------------------------------


class TestLegacyXDependsOnUnchanged:
    @pytest.mark.asyncio
    async def test_x_depends_on_present_and_unchanged(self, renderer: JsonSchemaRenderer) -> None:
        """Existing x-depends-on emission is unchanged when post_depends is absent."""
        f1 = _field("f1")
        f2 = _field(
            "f2",
            depends_on=DependencyRule(
                conditions=[_cond("f1")],
                logic="and",
                effect="show",
            ),
        )
        form = _form(f1, f2)

        result = await renderer.render(form)
        props = result.content["properties"]

        assert "x-depends-on" in props["f2"]
        dep = props["f2"]["x-depends-on"]
        assert dep["logic"] == "and"
        assert dep["effect"] == "show"
        assert dep["conditions"][0]["field_id"] == "f1"
        # No x-post-depends on f2 (it has no post_depends)
        assert "x-post-depends" not in props["f2"]

    @pytest.mark.asyncio
    async def test_operations_in_x_depends_on_serialized(self, renderer: JsonSchemaRenderer) -> None:
        """DependencyRule.operations appear inside the x-depends-on dump."""
        f1 = _field("f1", field_type=FieldType.NUMBER)
        f2 = _field("f2", field_type=FieldType.NUMBER)
        f3 = _field(
            "f3",
            field_type=FieldType.NUMBER,
            depends_on=DependencyRule(
                conditions=[_cond("f1")],
                operations=[
                    DependencyOperation(op="add", operands=["f1", "f2"], target="f3")
                ],
            ),
        )
        form = _form(f1, f2, f3)
        result = await renderer.render(form)
        dep = result.content["properties"]["f3"]["x-depends-on"]
        assert "operations" in dep
        assert dep["operations"] is not None
        assert len(dep["operations"]) == 1
        assert dep["operations"][0]["op"] == "add"

    @pytest.mark.asyncio
    async def test_both_x_depends_on_and_x_post_depends(self, renderer: JsonSchemaRenderer) -> None:
        """A field with both depends_on and post_depends emits both x- keys."""
        f1 = _field("f1")
        f2 = _field(
            "f2",
            depends_on=DependencyRule(conditions=[_cond("f1")], logic="xor"),
            post_depends=[PostDependency(target="f3", effect="hide")],
        )
        f3 = _field("f3")
        form = _form(f1, f2, f3)

        result = await renderer.render(form)
        props = result.content["properties"]

        assert "x-depends-on" in props["f2"]
        assert "x-post-depends" in props["f2"]
        assert props["f2"]["x-depends-on"]["logic"] == "xor"
        assert props["f2"]["x-post-depends"][0]["effect"] == "hide"
