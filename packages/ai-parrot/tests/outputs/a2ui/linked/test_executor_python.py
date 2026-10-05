"""FEAT-636 TASK-4106 — executor python branch and transform-stage codes."""

from __future__ import annotations

import pandas as pd
import pytest

from parrot.outputs.a2ui.linked import TransformSpec
from parrot.outputs.a2ui.linked.executor import ERROR_STATUS, dependencies_of, execute_sources, map_query_error
from parrot.outputs.a2ui.linked.pytransform import (
    TRANSFORM_FAILED,
    TRANSFORM_INVALID_OUTPUT,
    TRANSFORMER_NOT_REGISTERED,
    TransformStageError,
)
from parrot.outputs.a2ui.recipes.transformers import transformer_registry

from .test_executor import _real_querysource, fake_qs  # noqa: F401 — reuse the established fixtures


@pytest.fixture
def py_registry(monkeypatch: pytest.MonkeyPatch):
    """Register an isolated transformer for executor integration tests."""
    monkeypatch.setattr(transformer_registry, "_transformers", {})
    transformer_registry.register(
        "t636_count",
        lambda inputs, params: {"result": [{"n": len(inputs["source"])}]},
    )
    return transformer_registry


@pytest.mark.asyncio
async def test_execute_sources_applies_python(fake_qs, linked_source, py_registry) -> None:
    """A linked python transform runs after its QuerySource fetch."""
    fake_qs.registry["epson_field_activity"] = pd.DataFrame({"a": [1, 2, 3]})
    src = linked_source.model_copy(
        update={"transform": TransformSpec.model_validate({"python": {"transformer": "t636_count"}})}
    )

    outcome = await execute_sources(
        {"activity": src}, pctx=None, guard=None, max_snapshot_rows=500, max_fetch_rows=5000
    )

    assert outcome.outcomes["activity"].rows == [{"n": 3}]


@pytest.mark.parametrize(
    "code",
    [TRANSFORMER_NOT_REGISTERED, TRANSFORM_FAILED, TRANSFORM_INVALID_OUTPUT],
)
def test_map_query_error_transform_stage(code: str) -> None:
    """Transform-stage errors retain their stable 422 code through exception wrapping."""
    exc = RuntimeError("wrapped")
    exc.__cause__ = TransformStageError(code, "boom")

    assert map_query_error(exc) == (422, code)
    assert ERROR_STATUS[code] == 422


@pytest.mark.asyncio
async def test_unregistered_transformer_outcome_keeps_sibling(fake_qs, linked_source) -> None:
    """An unknown transformer fails only its source with the transform-stage code."""
    missing = linked_source.model_copy(
        update={"transform": TransformSpec.model_validate({"python": {"transformer": "missing_t636"}})}
    )
    sibling = linked_source.model_copy(update={"slug": "sibling_t636", "target": "/sibling/rows"})
    fake_qs.registry[missing.slug] = pd.DataFrame({"a": [1]})
    fake_qs.registry[sibling.slug] = pd.DataFrame({"a": [2]})

    outcome = await execute_sources({"missing": missing, "sibling": sibling})

    assert outcome.outcomes["missing"].error == TRANSFORMER_NOT_REGISTERED
    assert outcome.outcomes["sibling"].rows == [{"a": 2}]


def test_dependencies_of_python_none(linked_source) -> None:
    """A python transform has no DSL dependencies."""
    src = linked_source.model_copy(
        update={"transform": TransformSpec.model_validate({"python": {"transformer": "t636_count"}})}
    )

    assert dependencies_of(src) == []


@pytest.mark.asyncio
async def test_ops_and_ref_branches_unchanged(fake_qs, linked_source, caplog) -> None:
    """Existing DSL transforms still run while renderer refs remain Python no-ops."""
    ops = linked_source.model_copy(
        update={"transform": TransformSpec.model_validate({"ops": [{"op": "select", "columns": ["a"]}]})}
    )
    ref = linked_source.model_copy(
        update={
            "slug": "ref_t636",
            "target": "/ref/rows",
            "transform": TransformSpec.model_validate(
                {"ref": {"name": "client_only@1.0.0", "integrity": "sha384-hash"}}
            ),
        }
    )
    fake_qs.registry[ops.slug] = pd.DataFrame({"a": [1], "b": [2]})
    fake_qs.registry[ref.slug] = pd.DataFrame({"a": [3]})

    outcome = await execute_sources({"ops": ops, "ref": ref})

    assert outcome.outcomes["ops"].rows == [{"a": 1}]
    assert outcome.outcomes["ref"].rows == [{"a": 3}]
    assert "ref transform client_only@1.0.0 skipped in Python" in caplog.text
