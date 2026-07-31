"""Tests for FEAT-234 TASK-1528: EditToolkit dependency CRUD.

FEAT-393 (TASK-2000): dependency tools address the owning field by
``field_uid`` (str UUID); rule/post dicts still reference OTHER fields by
authored ``field_id`` (LLM ergonomics) — resolved to ``field_uid`` internally
via ``core.resolution.resolve_rule_references`` before the rule-integrity
check runs.
"""

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
            str(f2.field_uid),
            {"conditions": [_cond("f1")], "logic": "and", "effect": "show"},
        )
        assert result.get("success") is True
        assert result["depends_on"]["logic"] == "and"
        assert toolkit.form.sections[0].fields[1].depends_on is not None  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_add_dependency_on_group_child_field_persists(self) -> None:
        """FEAT-393 code review regression: add_dependency on a field
        nested inside a GROUP's children must actually persist the rule
        (previously, ``_replace_field_in_form`` only searched top-level
        section fields and one level into subsections, so a GROUP-child
        target silently no-opped while still reporting success=True)."""
        trigger = _field("trigger")
        child = _field("child")
        group = FormField(
            field_id="group", field_type=FieldType.GROUP, label="group", children=[child]
        )
        form = _form(trigger, group)
        toolkit = EditToolkit(form)

        result = await toolkit.add_dependency(
            str(child.field_uid),
            {"conditions": [_cond("trigger")], "logic": "and", "effect": "show"},
        )
        assert result.get("success") is True

        persisted_child = next(
            f for f in toolkit.form.iter_fields_recursive() if f.field_id == "child"
        )
        assert persisted_child.depends_on is not None
        assert persisted_child.depends_on.conditions[0].field_id == "trigger"

    @pytest.mark.asyncio
    async def test_add_dependency_invalid_rule_returns_error(self) -> None:
        """An invalid rule (bad logic) returns an error and does not mutate the form."""
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.add_dependency(
            str(f2.field_uid),
            {"conditions": [_cond("f1")], "logic": "invalid_value", "effect": "show"},
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
            str(f2.field_uid),
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
            str(f1.field_uid), {"conditions": [_cond("f2")], "logic": "and"}
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_add_dependency_field_not_found(self) -> None:
        form = _form(_field("f1"))
        toolkit = EditToolkit(form)
        result = await toolkit.add_dependency(
            "00000000-0000-0000-0000-000000000000", {"conditions": [_cond("f1")]}
        )
        assert "error" in result

    @pytest.mark.asyncio
    async def test_add_dependency_invalid_uuid_returns_error(self) -> None:
        form = _form(_field("f1"))
        toolkit = EditToolkit(form)
        result = await toolkit.add_dependency("not-a-uuid", {"conditions": [_cond("f1")]})
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

        result = await toolkit.update_dependency(str(f2.field_uid), {"logic": "xor"})
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

        result = await toolkit.remove_dependency(str(f2.field_uid))
        assert result.get("success") is True
        updated = toolkit.form.sections[0].fields[1]
        assert isinstance(updated, FormField)
        assert updated.depends_on is None

    @pytest.mark.asyncio
    async def test_remove_dependency_field_not_found(self) -> None:
        form = _form(_field("f1"))
        toolkit = EditToolkit(form)
        result = await toolkit.remove_dependency("00000000-0000-0000-0000-000000000000")
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
            str(f1.field_uid), {"target": "f2", "effect": "show"}
        )
        assert result.get("success") is True
        updated = toolkit.form.sections[0].fields[0]
        assert isinstance(updated, FormField)
        assert updated.post_depends is not None
        # target is resolved to f2's field_uid (FEAT-393) — authored as "f2".
        assert updated.post_depends[0].target == str(f2.field_uid)

    @pytest.mark.asyncio
    async def test_add_post_dependency_ordering_violation(self) -> None:
        """post_depends targeting an earlier field is rejected."""
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        # f2 targets f1 (earlier) — violation
        result = await toolkit.add_post_dependency(
            str(f2.field_uid), {"target": "f1", "effect": "show"}
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
            str(f1.field_uid), {"target": "f2", "effect": "set"}  # missing operation
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

        await toolkit.add_post_dependency(str(f1.field_uid), {"target": "f2", "effect": "show"})
        result = await toolkit.add_post_dependency(
            str(f1.field_uid), {"target": "f3", "effect": "cascade_clear"}
        )
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
        f2 = _field("f2")
        f1 = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="f1",
            post_depends=[PostDependency(target=str(f2.field_uid), effect="show")],
        )
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.remove_post_dependency(str(f1.field_uid), str(f2.field_uid))
        assert result.get("success") is True
        updated = toolkit.form.sections[0].fields[0]
        assert isinstance(updated, FormField)
        assert updated.post_depends is None

    @pytest.mark.asyncio
    async def test_remove_post_dependency_matches_non_canonical_uuid_case(self) -> None:
        """FEAT-393 code review regression: target matching must compare
        as UUIDs, not raw strings — a non-canonical-case (but valid and
        equal) UUID string must still match the stored canonical target."""
        f2 = _field("f2")
        f1 = FormField(
            field_id="f1",
            field_type=FieldType.TEXT,
            label="f1",
            post_depends=[PostDependency(target=str(f2.field_uid), effect="show")],
        )
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.remove_post_dependency(
            str(f1.field_uid), str(f2.field_uid).upper()
        )
        assert result.get("success") is True
        updated = toolkit.form.sections[0].fields[0]
        assert isinstance(updated, FormField)
        assert updated.post_depends is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_post_dependency_errors(self) -> None:
        f1 = _field("f1")
        form = _form(f1)
        toolkit = EditToolkit(form)

        result = await toolkit.remove_post_dependency(
            str(f1.field_uid), "00000000-0000-0000-0000-000000000000"
        )
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
            {"field_uid": str(f2.field_uid), "rule": {"conditions": [_cond("f1")], "logic": "and"}},
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

        result = await toolkit.execute_tool(
            "remove_dependency", {"field_uid": str(f2.field_uid)}
        )
        assert result.get("success") is True

    @pytest.mark.asyncio
    async def test_add_post_dependency_via_execute_tool(self) -> None:
        f1 = _field("f1")
        f2 = _field("f2")
        form = _form(f1, f2)
        toolkit = EditToolkit(form)

        result = await toolkit.execute_tool(
            "add_post_dependency",
            {"field_uid": str(f1.field_uid), "post": {"target": "f2", "effect": "cascade_clear"}},
        )
        assert result.get("success") is True
