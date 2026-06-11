"""Tests for FEAT-234 TASK-1528: EditToolkit dependency CRUD."""

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
from parrot_formdesigner.tools import EditToolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field(field_id: str, field_type: FieldType = FieldType.TEXT) -> FormField:
    return FormField(field_id=field_id, field_type=field_type, label=field_id)


def _form(*fields: FormField) -> FormSchema:
    return FormSchema(
        form_id="test",
        title="Test",
        sections=[FormSection(section_id="s1", fields=list(fields))],
    )


def _cond(field_id: str) -> dict:
    return {"field_id": field_id, "operator": "eq", "value": "x"}


# ---------------------------------------------------------------------------
# add_dependency
# ---------------------------------------------------------------------------


class TestAddDependency:
    @pytest.mark.asyncio
    async def test_add_valid_dependency(self) -> None:
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.add_dependency(
            "f2", {"conditions": [_cond("f1")], "logic": "and", "effect": "show"}
        )
        assert result.get("success") is True
        assert result["depends_on"]["logic"] == "and"
        assert toolkit.form.sections[0].fields[1].depends_on is not None  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_add_dependency_invalid_rule_returns_error(self) -> None:
        """An invalid rule (bad logic) returns an error and does not mutate the form."""
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.add_dependency(
            "f2", {"conditions": [_cond("f1")], "logic": "invalid_value", "effect": "show"}
        )
        assert "error" in result
        # form must be unchanged
        assert toolkit.form.sections[0].fields[1].depends_on is None  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_add_dependency_unknown_field_id_returns_error(self) -> None:
        """Rule referencing unknown field_id is rejected."""
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.add_dependency(
            "f2",
            {"conditions": [{"field_id": "ghost", "operator": "eq", "value": "x"}], "logic": "and"},
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_add_dependency_ordering_violation_rejected(self) -> None:
        """depends_on referencing a later field is rejected."""
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        # f1 references f2 (later) — ordering violation
        result = await toolkit.add_dependency(
            "f1", {"conditions": [_cond("f2")], "logic": "and"}
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_add_dependency_field_not_found(self) -> None:
        form = _form(_field("f1"))
        toolkit = EditToolkit(form)
        result = await toolkit.add_dependency("ghost", {"conditions": [_cond("f1")]})
        assert "error" in result


# ---------------------------------------------------------------------------
# update_dependency
# ---------------------------------------------------------------------------


class TestUpdateDependency:
    @pytest.mark.asyncio
    async def test_update_existing_dependency(self) -> None:
        f1 = _field("f1")
        f2 = FormField(
            field_id="f2",
            field_type=FieldType.TEXT,
            label="f2",
            depends_on=DependencyRule(
                conditions=[FieldCondition(field_id="f1", operator=ConditionOperator.EQ, value="x")],
                logic="and",
                effect="show",
            ),
        )
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.update_dependency("f2", {"logic": "xor"})
        assert result.get("success") is True
        updated = toolkit.form.sections[0].fields[1]
        assert isinstance(updated, FormField)
        assert updated.depends_on is not None
        assert updated.depends_on.logic == "xor"


# ---------------------------------------------------------------------------
# remove_dependency
# ---------------------------------------------------------------------------


class TestRemoveDependency:
    @pytest.mark.asyncio
    async def test_remove_dependency(self) -> None:
        f1 = _field("f1")
        f2 = FormField(
            field_id="f2",
            field_type=FieldType.TEXT,
            label="f2",
            depends_on=DependencyRule(
                conditions=[FieldCondition(field_id="f1", operator=ConditionOperator.EQ, value="x")],
            ),
        )
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.remove_dependency("f2")
        assert result.get("success") is True
        updated = toolkit.form.sections[0].fields[1]
        assert isinstance(updated, FormField)
        assert updated.depends_on is None

    @pytest.mark.asyncio
    async def test_remove_dependency_field_not_found(self) -> None:
        form = _form(_field("f1"))
        toolkit = EditToolkit(form)
        result = await toolkit.remove_dependency("ghost")
        assert "error" in result


# ---------------------------------------------------------------------------
# add_post_dependency
# ---------------------------------------------------------------------------


class TestAddPostDependency:
    @pytest.mark.asyncio
    async def test_add_valid_post_dependency(self) -> None:
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.add_post_dependency(
            "f1", {"target": "f2", "effect": "show"}
        )
        assert result.get("success") is True
        updated = toolkit.form.sections[0].fields[0]
        assert isinstance(updated, FormField)
        assert updated.post_depends is not None
        assert updated.post_depends[0].target == "f2"

    @pytest.mark.asyncio
    async def test_add_post_dependency_ordering_violation(self) -> None:
        """post_depends targeting an earlier field is rejected."""
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        # f2 targets f1 (earlier) — violation
        result = await toolkit.add_post_dependency(
            "f2", {"target": "f1", "effect": "show"}
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_add_post_dependency_set_requires_operation(self) -> None:
        """PostDependency with effect='set' but no operation is rejected by model validation."""
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.add_post_dependency(
            "f1", {"target": "f2", "effect": "set"}  # missing operation
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_add_multiple_post_depends(self) -> None:
        """Two consecutive add_post_dependency calls accumulate entries."""
        f1 = _field("f1")
        f2 = _field("f2")
        f3 = _field("f3")
        form = _form(f1, f2, f3)
        toolkit = EditToolkit(form)

        await toolkit.add_post_dependency("f1", {"target": "f2", "effect": "show"})
        result = await toolkit.add_post_dependency("f1", {"target": "f3", "effect": "cascade_clear"})
        assert result.get("success") is True
        updated = toolkit.form.sections[0].fields[0]
        assert isinstance(updated, FormField)
        assert len(updated.post_depends) == 2  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# remove_post_dependency
# ---------------------------------------------------------------------------


class TestRemovePostDependency:
    @pytest.mark.asyncio
    async def test_remove_post_dependency(self) -> None:
        f1 = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="f1",
            post_depends=[PostDependency(target="f2", effect="show")],
        )
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.remove_post_dependency("f1", "f2")
        assert result.get("success") is True
        updated = toolkit.form.sections[0].fields[0]
        assert isinstance(updated, FormField)
        assert updated.post_depends is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_post_dependency_errors(self) -> None:
        f1 = _field("f1")
        form = _form(f1)
        toolkit = EditToolkit(form)

        result = await toolkit.remove_post_dependency("f1", "ghost")
        assert "error" in result


# ---------------------------------------------------------------------------
# execute_tool dispatch
# ---------------------------------------------------------------------------


class TestExecuteToolDispatch:
    @pytest.mark.asyncio
    async def test_add_dependency_via_execute_tool(self) -> None:
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.execute_tool(
            "add_dependency",
            {"field_id": "f2", "rule": {"conditions": [_cond("f1")], "logic": "and"}},
        )
        assert result.get("success") is True

    @pytest.mark.asyncio
    async def test_remove_dependency_via_execute_tool(self) -> None:
        f1 = _field("f1")
        f2 = FormField(
            field_id="f2",
            field_type=FieldType.TEXT,
            label="f2",
            depends_on=DependencyRule(
                conditions=[FieldCondition(field_id="f1", operator=ConditionOperator.EQ, value="x")]
            ),
        )
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.execute_tool("remove_dependency", {"field_id": "f2"})
        assert result.get("success") is True

    @pytest.mark.asyncio
    async def test_add_post_dependency_via_execute_tool(self) -> None:
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.execute_tool(
            "add_post_dependency",
            {"field_id": "f1", "post": {"target": "f2", "effect": "cascade_clear"}},
        )
        assert result.get("success") is True
