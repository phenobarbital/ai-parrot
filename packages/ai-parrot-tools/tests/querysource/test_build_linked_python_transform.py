"""FEAT-636 TASK-4109 — build-time python-transform gate."""

from __future__ import annotations

import pytest

from parrot.outputs.a2ui.recipes.transformers import transformer_registry
from parrot_tools.querysource.errors import InvalidConditionsError
from parrot_tools.querysource.toolkit import QuerysourceToolkit

from .test_build_linked_surface_tool import fake_core_qs  # noqa: F401 — established fixture

COMPONENT = {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]}
SLUG = "epson_field_activity"


@pytest.fixture
def py_registry(monkeypatch):
    monkeypatch.setattr(transformer_registry, "_transformers", {})
    transformer_registry.register("t636_identity", lambda inputs, params: {"result": inputs["source"]})
    return transformer_registry


async def test_unregistered_transformer_rejected(fake_core_qs, py_registry):
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    with pytest.raises(InvalidConditionsError, match="invalid python transform"):
        await toolkit.build_linked_surface(SLUG, COMPONENT, transform={"python": {"transformer": "nope"}})


async def test_registered_transformer_accepted(fake_core_qs, py_registry):
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    result = await toolkit.build_linked_surface(SLUG, COMPONENT, transform={"python": {"transformer": "t636_identity"}})
    source = result["a2ui_envelope"]["metadata"]["extensions"]["parrot_data_sources"][SLUG]
    assert source["transform"]["python"]["transformer"] == "t636_identity"


async def test_alias_mismatch_rejected(fake_core_qs, py_registry):
    transformer_registry.register(
        "t636_df", lambda inputs, params: {"result": inputs["df"]}, requires_columns={"df": ["day"]}
    )
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    with pytest.raises(InvalidConditionsError, match="input alias"):
        await toolkit.build_linked_surface(SLUG, COMPONENT, transform={"python": {"transformer": "t636_df"}})


async def test_derived_widget_python_rejected(fake_core_qs, py_registry):
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    with pytest.raises(InvalidConditionsError):
        await toolkit.build_linked_dashboard(
            [
                {
                    "key": "w1",
                    "source": "base",
                    "component": COMPONENT,
                    "transform": {"python": {"transformer": "t636_identity"}},
                }
            ],
            sources={"base": {"slug": SLUG}},
        )
