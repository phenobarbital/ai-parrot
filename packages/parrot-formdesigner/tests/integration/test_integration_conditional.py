"""Integration tests for FEAT-234 ISSUE-4: conditional-sections end-to-end flows.

These tests exercise the full pipeline:
  EditToolkit → FormValidator → JsonSchemaRenderer → RuleEvaluator

and verify that:
1. A form authored via EditToolkit with xor/calc rules validates and renders correctly.
2. A legacy form without post_depends/operations is unaffected.
3. CreateFormTool (mocked LLM) emits valid depends_on/post_depends in its output.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

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
from parrot_formdesigner.services import FormValidator, RuleEvaluator
from parrot_formdesigner.tools import EditToolkit
from parrot_formdesigner.tools.create_form import CreateFormTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _field(field_id: str, field_type: FieldType = FieldType.TEXT, **kwargs: Any) -> FormField:
    return FormField(field_id=field_id, field_type=field_type, label=field_id, **kwargs)


def _form(*fields: FormField) -> FormSchema:
    return FormSchema(
        form_id="test-conditional",
        title="Test Conditional Form",
        sections=[FormSection(section_id="s1", fields=list(fields))],
    )


# ---------------------------------------------------------------------------
# ISSUE-4 test 1: authored form with xor + calc validates and renders
# ---------------------------------------------------------------------------


class TestAuthoredFormWithRulesValidatesAndRenders:
    """Build a form via EditToolkit with logic='xor' and effect='calc', then
    run it through FormValidator, JsonSchemaRenderer, and RuleEvaluator."""

    @pytest.fixture
    def form_with_rules(self) -> FormSchema:
        """Form: trigger_a + trigger_b control whether 'derived' is calculated."""
        trigger_a = _field("trigger_a")
        trigger_b = _field("trigger_b")
        # source_value feeds into the calc operation
        source_value = _field("source_value", FieldType.NUMBER)
        # derived receives the computed value
        derived = _field("derived", FieldType.NUMBER)
        return _form(trigger_a, trigger_b, source_value, derived)

    @pytest.mark.asyncio
    async def test_add_xor_dependency_via_toolkit(self, form_with_rules: FormSchema) -> None:
        """EditToolkit can add a depends_on with logic='xor' successfully."""
        toolkit = EditToolkit(form_with_rules)
        result = await toolkit.add_dependency(
            "derived",
            {
                "conditions": [
                    {"field_id": "trigger_a", "operator": "eq", "value": "yes"},
                    {"field_id": "trigger_b", "operator": "eq", "value": "yes"},
                ],
                "logic": "xor",
                "effect": "show",
            },
        )
        assert result.get("success") is True, f"Expected success, got: {result}"
        field = next(
            f for s in toolkit.form.sections for f in s.fields if f.field_id == "derived"
        )
        assert field.depends_on is not None
        assert field.depends_on.logic == "xor"

    @pytest.mark.asyncio
    async def test_add_calc_post_dependency_via_toolkit(self, form_with_rules: FormSchema) -> None:
        """EditToolkit can add a post_depends with effect='calc' successfully.

        trigger_b.post_depends targets derived; the operand is trigger_a (an earlier
        field), so there is no circular dependency.
        """
        toolkit = EditToolkit(form_with_rules)
        # trigger_b (2nd field) targets derived (4th field); operand = trigger_a (1st field)
        # Dependency graph: trigger_b -> derived (forward) + trigger_b -> trigger_a (op read)
        # No cycle.
        result = await toolkit.add_post_dependency(
            "trigger_b",
            {
                "target": "derived",
                "effect": "calc",
                "operation": {
                    "op": "copy",
                    "operands": ["trigger_a"],
                    "target": "derived",
                },
            },
        )
        assert result.get("success") is True, f"Expected success, got: {result}"
        field = next(
            f for s in toolkit.form.sections for f in s.fields if f.field_id == "trigger_b"
        )
        assert field.post_depends is not None
        assert len(field.post_depends) == 1
        assert field.post_depends[0].effect == "calc"

    def test_validator_passes_on_valid_rules(self) -> None:
        """FormValidator.validate_rules() accepts a form with valid depends_on and calc post_depends."""
        # flag → source → result (all forward references)
        flag = FormField(
            field_id="flag",
            field_type=FieldType.TEXT,
            label="flag",
        )
        source = FormField(
            field_id="source",
            field_type=FieldType.NUMBER,
            label="source",
            post_depends=[
                PostDependency(
                    target="result",
                    effect="calc",
                    conditions=[
                        FieldCondition(
                            field_id="flag",
                            operator=ConditionOperator.EQ,
                            value="yes",
                        )
                    ],
                    logic="and",
                    operation=DependencyOperation(
                        op="copy",
                        operands=["source"],
                        target="result",
                    ),
                )
            ],
        )
        result_field = FormField(
            field_id="result",
            field_type=FieldType.NUMBER,
            label="result",
            depends_on=DependencyRule(
                conditions=[
                    FieldCondition(
                        field_id="flag",
                        operator=ConditionOperator.EQ,
                        value="yes",
                    )
                ],
                logic="and",
                effect="show",
            ),
        )
        form = FormSchema(
            form_id="calc-form",
            title="Calc Form",
            sections=[FormSection(section_id="s1", fields=[flag, source, result_field])],
        )
        validator = FormValidator()
        errors = validator.validate_rules(form)
        assert errors == [], f"Expected no rule errors, got: {errors}"

    @pytest.mark.asyncio
    async def test_renderer_emits_x_post_depends(self) -> None:
        """JsonSchemaRenderer emits x-post-depends for a field with post_depends."""
        source = FormField(
            field_id="source",
            field_type=FieldType.NUMBER,
            label="source",
            post_depends=[
                PostDependency(
                    target="result",
                    effect="calc",
                    operation=DependencyOperation(
                        op="add",
                        operands=["source"],
                        target="result",
                    ),
                )
            ],
        )
        result_field = _field("result", FieldType.NUMBER)
        form = FormSchema(
            form_id="render-form",
            title="Render Form",
            sections=[FormSection(section_id="s1", fields=[source, result_field])],
        )
        renderer = JsonSchemaRenderer()
        rendered = await renderer.render(form)
        # The rendered output has a "properties" key at top level or nested per section
        props = rendered.content.get("properties", {})
        assert "source" in props, "Expected 'source' field in rendered properties"
        assert "x-post-depends" in props["source"], (
            "Expected 'x-post-depends' in rendered source field"
        )
        post_list = props["source"]["x-post-depends"]
        assert isinstance(post_list, list) and len(post_list) == 1
        assert post_list[0]["effect"] == "calc"
        assert post_list[0]["target"] == "result"

    @pytest.mark.asyncio
    async def test_rule_evaluator_resolves_calc_with_answers(self) -> None:
        """RuleEvaluator.resolve() correctly computes a calc post_depends value."""
        source = FormField(
            field_id="source",
            field_type=FieldType.NUMBER,
            label="source",
            post_depends=[
                PostDependency(
                    target="result",
                    effect="calc",
                    operation=DependencyOperation(
                        op="add",
                        operands=["source"],
                        target="result",
                    ),
                )
            ],
        )
        result_field = _field("result", FieldType.NUMBER)
        form = FormSchema(
            form_id="eval-form",
            title="Eval Form",
            sections=[FormSection(section_id="s1", fields=[source, result_field])],
        )
        evaluator = RuleEvaluator()
        resolution = await evaluator.resolve(form, {"source": 7.0})
        assert resolution.computed.get("result") == 7.0, (
            f"Expected result=7.0, got {resolution.computed}"
        )


# ---------------------------------------------------------------------------
# ISSUE-4 test 2: legacy form without rules is unaffected
# ---------------------------------------------------------------------------


class TestImportedLegacyFormUnaffected:
    """Load a form without post_depends/operations; verify it validates cleanly
    and the renderer does NOT inject any new keys."""

    @pytest.fixture
    def legacy_form(self) -> FormSchema:
        """Minimal form with no dependency rules whatsoever."""
        return FormSchema(
            form_id="legacy-form",
            title="Legacy Form",
            sections=[
                FormSection(
                    section_id="main",
                    fields=[
                        FormField(
                            field_id="name",
                            field_type=FieldType.TEXT,
                            label="Name",
                            required=True,
                        ),
                        FormField(
                            field_id="age",
                            field_type=FieldType.INTEGER,
                            label="Age",
                        ),
                        FormField(
                            field_id="email",
                            field_type=FieldType.EMAIL,
                            label="Email",
                        ),
                    ],
                )
            ],
        )

    def test_legacy_form_validates_cleanly(self, legacy_form: FormSchema) -> None:
        """FormValidator.validate_rules() accepts a legacy form with no dependency rules."""
        validator = FormValidator()
        errors = validator.validate_rules(legacy_form)
        assert errors == [], f"Legacy form should have no rule errors, got: {errors}"

    @pytest.mark.asyncio
    async def test_legacy_form_renderer_no_new_keys(self, legacy_form: FormSchema) -> None:
        """Renderer does not inject x-post-depends or x-depends-on for legacy fields."""
        renderer = JsonSchemaRenderer()
        rendered = await renderer.render(legacy_form)
        props = rendered.content.get("properties", {})
        for field_id, prop in props.items():
            assert "x-post-depends" not in prop, (
                f"Field '{field_id}' unexpectedly received x-post-depends"
            )

    @pytest.mark.asyncio
    async def test_legacy_form_evaluator_all_visible(self, legacy_form: FormSchema) -> None:
        """RuleEvaluator returns all fields visible and no computed/cleared entries."""
        evaluator = RuleEvaluator()
        resolution = await evaluator.resolve(legacy_form, {})
        for field_id in ["name", "age", "email"]:
            assert resolution.visible.get(field_id) is True
        assert resolution.computed == {}
        assert resolution.cleared == []


# ---------------------------------------------------------------------------
# ISSUE-4 test 3: CreateFormTool (mocked LLM) emits valid rules
# ---------------------------------------------------------------------------


_FORM_WITH_RULES_JSON = json.dumps({
    "form_id": "conditional-demo",
    "title": "Conditional Demo",
    "sections": [
        {
            "section_id": "main",
            "fields": [
                {
                    "field_id": "category",
                    "field_type": "select",
                    "label": "Category",
                    "options": [
                        {"value": "a", "label": "A"},
                        {"value": "b", "label": "B"},
                    ],
                },
                {
                    "field_id": "subcategory",
                    "field_type": "text",
                    "label": "Subcategory",
                    "depends_on": {
                        "conditions": [
                            {"field_id": "category", "operator": "eq", "value": "a"}
                        ],
                        "logic": "and",
                        "effect": "show",
                    },
                    "post_depends": None,
                },
                {
                    "field_id": "total_price",
                    "field_type": "number",
                    "label": "Total Price",
                    "post_depends": None,
                },
            ],
        }
    ],
})


class TestCreateFormToolEmitsRules:
    """CreateFormTool (with mocked LLM) returns a form that contains valid
    depends_on and post_depends fields."""

    @pytest.fixture
    def mock_client(self):
        """Mock LLM client returning a form with depends_on."""
        client = AsyncMock()
        client.completion = AsyncMock(return_value=_FORM_WITH_RULES_JSON)
        return client

    @pytest.fixture
    def tool(self, mock_client):
        return CreateFormTool(client=mock_client)

    @pytest.mark.asyncio
    async def test_create_form_tool_returns_success(self, tool) -> None:
        """execute() returns success=True and form in metadata."""
        result = await tool.execute(prompt="Create a form with category conditional")
        assert result.success is True, f"Expected success, got: {result}"
        assert "form" in result.metadata

    @pytest.mark.asyncio
    async def test_create_form_tool_output_has_depends_on(self, tool) -> None:
        """The output form schema contains a valid depends_on field."""
        result = await tool.execute(prompt="Create a form with category conditional")
        assert result.success is True
        form_dict = result.metadata["form"]
        # Reconstruct as FormSchema to confirm it validates
        form = FormSchema(**form_dict)
        # Find the subcategory field which should have depends_on
        all_fields = {f.field_id: f for s in form.sections for f in s.fields}
        assert "subcategory" in all_fields, "Expected 'subcategory' field in form"
        subcategory = all_fields["subcategory"]
        assert subcategory.depends_on is not None, (
            "Expected subcategory to have depends_on"
        )
        assert subcategory.depends_on.logic == "and"
        assert len(subcategory.depends_on.conditions) == 1
        assert subcategory.depends_on.conditions[0].field_id == "category"

    @pytest.mark.asyncio
    async def test_create_form_tool_output_validates(self, tool) -> None:
        """The form emitted by CreateFormTool passes FormValidator.validate_rules()."""
        result = await tool.execute(prompt="Create a form with category conditional")
        assert result.success is True
        form = FormSchema(**result.metadata["form"])
        validator = FormValidator()
        errors = validator.validate_rules(form)
        assert errors == [], f"FormValidator rejected generated form: {errors}"
