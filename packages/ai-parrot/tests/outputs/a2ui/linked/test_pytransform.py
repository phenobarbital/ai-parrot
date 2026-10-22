"""FEAT-636 TASK-4105 — pytransform gate, output selection, capped execution."""

import pandas as pd
import pytest

from parrot.outputs.a2ui.linked.models import PythonTransform
from parrot.outputs.a2ui.linked.pytransform import (
    TRANSFORM_FAILED,
    TRANSFORM_INVALID_OUTPUT,
    TRANSFORMER_NOT_REGISTERED,
    TransformStageError,
    apply_python_transform,
    select_output_frame,
    validate_python_transform,
)
from parrot.outputs.a2ui.recipes.transformers import transformer_registry


@pytest.fixture
def registered(monkeypatch: pytest.MonkeyPatch):
    """Isolate the process-wide registry: tests register into a private dict."""
    monkeypatch.setattr(transformer_registry, "_transformers", {})

    def double(inputs: dict[str, pd.DataFrame], params: dict[str, object]) -> dict[str, pd.DataFrame]:
        df = inputs["source"]
        return {"result": pd.concat([df, df], ignore_index=True)}

    transformer_registry.register("t636_double", double)
    return transformer_registry


async def test_apply_runs_and_caps(registered) -> None:
    """Registered transforms run once and output is capped after transformation."""
    frame = pd.DataFrame({"a": [1, 2, 3]})
    out = await apply_python_transform(frame, PythonTransform(transformer="t636_double"), max_rows=4)
    assert len(out) == 4


async def test_apply_unregistered(registered) -> None:
    """Unknown transformer names use the stable not-registered code."""
    with pytest.raises(TransformStageError) as info:
        await apply_python_transform(pd.DataFrame(), PythonTransform(transformer="nope"), max_rows=10)
    assert info.value.code == TRANSFORMER_NOT_REGISTERED


async def test_apply_failure(registered) -> None:
    """Transformer exceptions are wrapped as transform-stage failures."""

    def broken(inputs: dict[str, pd.DataFrame], params: dict[str, object]) -> dict[str, pd.DataFrame]:
        raise RuntimeError("broken")

    transformer_registry.register("t636_broken", broken)
    with pytest.raises(TransformStageError) as info:
        await apply_python_transform(pd.DataFrame(), PythonTransform(transformer="t636_broken"), max_rows=10)
    assert info.value.code == TRANSFORM_FAILED


def test_select_output_frame_rule() -> None:
    """Output selection follows override, result, sole-key, then ambiguity rules."""
    first = pd.DataFrame({"a": [1]})
    second = pd.DataFrame({"b": [2]})

    assert select_output_frame({"first": first, "second": second}, "second") is second
    assert select_output_frame({"first": first, "result": second}, None) is second
    assert select_output_frame({"first": first}, None) is first
    assert select_output_frame({"rows": [{"a": 1}]}, None).to_dict("records") == [{"a": 1}]
    assert select_output_frame({"rows": []}, None).empty

    for result, output in (
        ({"first": first, "second": second}, None),
        ({"first": first}, "missing"),
        ({"rows": 1}, None),
        ({"rows": {"a": 1}}, None),
        ({"rows": [1]}, None),
    ):
        with pytest.raises(TransformStageError) as info:
            select_output_frame(result, output)
        assert info.value.code == TRANSFORM_INVALID_OUTPUT


def test_validate_gate(registered) -> None:
    """The build-time gate checks registry membership and manifest aliases without execution."""
    assert validate_python_transform(PythonTransform(transformer="missing"))
    calls: list[None] = []

    def no_op(inputs: dict[str, pd.DataFrame], params: dict[str, object]) -> dict[str, pd.DataFrame]:
        calls.append(None)
        return {"result": inputs["source"]}

    transformer_registry.register("t636_single", no_op, requires_columns={"input": []})
    assert validate_python_transform(PythonTransform(transformer="t636_single")) == [
        "transformer 't636_single' expects input alias 'input'; set python.input_alias"
    ]

    transformer_registry.register("t636_multi", no_op, requires_columns={"left": [], "right": []})
    assert validate_python_transform(PythonTransform(transformer="t636_multi")) == [
        "multi-input transformer 't636_multi' is not supported for linked sources in v1"
    ]

    transformer_registry.register("t636_none", no_op)
    assert validate_python_transform(PythonTransform(transformer="t636_none")) == []
    assert calls == []
