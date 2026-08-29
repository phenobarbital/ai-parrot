"""Tests for `export_functions`/`agent_capabilities` (FEAT-469 TASK-2571)."""

from __future__ import annotations

import jsonschema
import pytest
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, FunctionDefinition
from parrot.outputs.a2ui.catalog.basic import load_spec, schema_registry
from parrot.outputs.a2ui.catalog.export import (
    agent_capabilities,
    export_catalog_definition,
    export_functions,
)


class _FakeExecutor:
    """A minimal `FunctionExecutor` double — only `list_functions()` is used here."""

    def __init__(self, functions: list[FunctionDefinition]):
        self._functions = functions

    async def call(self, name, args, ctx):  # pragma: no cover - not exercised here
        raise NotImplementedError

    def list_functions(self):
        return self._functions


def _validate_against(schema_name: str, doc: dict) -> None:
    schema = load_spec(schema_name)
    registry = schema_registry()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls(schema, registry=registry).validate(doc)


@pytest.fixture
def executor():
    return _FakeExecutor(
        [
            FunctionDefinition(
                name="get_weather",
                catalog_id=DEFAULT_CATALOG_ID,
                args_schema={"type": "object", "properties": {"location": {"type": "string"}}},
                return_type="string",
                allowed_callers="rendererOrAgent",
                requires_user_activation=False,
            )
        ]
    )


@pytest.fixture
def executor_with_hidden_tool(executor):
    # a2ui_hidden filtering happens upstream (ToolManagerExecutor, TASK-2570) —
    # a hidden tool never reaches export_functions() at all, so it is
    # represented here simply by NOT including it in list_functions().
    return executor


@pytest.fixture
def executor_colliding():
    return _FakeExecutor(
        [
            FunctionDefinition(
                name="openUrl",  # collides with a Basic Catalog function
                catalog_id=DEFAULT_CATALOG_ID,
                args_schema={"type": "object"},
                return_type="void",
            )
        ]
    )


@pytest.fixture
def executor_dashed():
    return _FakeExecutor(
        [
            FunctionDefinition(
                name="get-weather",
                catalog_id=DEFAULT_CATALOG_ID,
                args_schema={"type": "object"},
                return_type="any",
                allowed_callers="rendererOrAgent",
            )
        ]
    )


@pytest.fixture
def executor_two_dashed():
    return _FakeExecutor(
        [
            FunctionDefinition(name="get-weather", catalog_id=DEFAULT_CATALOG_ID, args_schema={}, return_type="any"),
            FunctionDefinition(name="get.weather", catalog_id=DEFAULT_CATALOG_ID, args_schema={}, return_type="any"),
        ]
    )


class TestExportFunctions:
    def test_hidden_tool_is_omitted(self, executor_with_hidden_tool):
        assert "danger_drop_table" not in export_functions(executor_with_hidden_tool)

    def test_allowed_callers_and_activation(self, executor):
        fn = export_functions(executor)["get_weather"]
        assert fn["allowedCallers"] == "rendererOrAgent"
        assert fn["requiresUserActivation"] is False

    def test_requires_user_activation_forces_renderer_only(self):
        """catalog_definition.json's FunctionDefinition: requiresUserActivation:true
        forces allowedCallers to "rendererOnly" (verified against the schema's
        third allOf branch, and the Basic Catalog's own `openUrl`)."""
        executor = _FakeExecutor(
            [
                FunctionDefinition(
                    name="open_native_share_sheet",
                    catalog_id=DEFAULT_CATALOG_ID,
                    args_schema={},
                    return_type="void",
                    requires_user_activation=True,
                )
            ]
        )
        fn = export_functions(executor)["open_native_share_sheet"]
        assert fn["allowedCallers"] == "rendererOnly"
        assert fn["requiresUserActivation"] is True

    def test_merged_definition_validates(self, executor):
        doc = export_catalog_definition(executor=executor)
        _validate_against("catalog_definition", doc)
        assert "get_weather" in doc["functions"]

    def test_basic_catalog_functions_survive_merge(self, executor):
        """Basic functions are copied verbatim — a $ref does not satisfy
        unevaluatedProperties:false. Merging tools must not drop them."""
        doc = export_catalog_definition(executor=executor)
        assert "returnType" in doc["functions"]["required"]
        assert "openUrl" in doc["functions"]

    def test_collision_with_basic_function_raises(self, executor_colliding):
        with pytest.raises(ValueError, match="collision"):
            export_functions(executor_colliding)

    def test_collision_via_export_catalog_definition_raises(self, executor_colliding):
        with pytest.raises(ValueError, match="collision"):
            export_catalog_definition(executor=executor_colliding)


class TestUAX31:
    def test_non_identifier_name_sanitized_with_warning(self, executor_dashed, caplog):
        with caplog.at_level("WARNING"):
            fns = export_functions(executor_dashed)
        assert all(n.isidentifier() for n in fns)
        assert "sanitiz" in caplog.text.lower()

    def test_sanitization_collision_raises(self, executor_two_dashed):
        with pytest.raises(ValueError):
            export_functions(executor_two_dashed)


class TestAgentCapabilities:
    def test_shape(self):
        caps = agent_capabilities([DEFAULT_CATALOG_ID])
        assert caps["v1.0"]["supportedCatalogIds"] == [DEFAULT_CATALOG_ID]
        assert caps["v1.0"]["acceptsInlineCatalogs"] is False
        _validate_against("agent_capabilities", caps)
