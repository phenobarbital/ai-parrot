"""Registry + fail-fast gate tests for FEAT-324 Module 2
(`parrot.outputs.a2ui.recipes.transformers`)."""

import pandas as pd
import pytest

from parrot.outputs.a2ui.recipes import infographic_transformer
from parrot.outputs.a2ui.recipes.models import TransformStep
from parrot.outputs.a2ui.recipes.transformers import TransformerRegistry, validate_inputs


def test_register_and_manifest():
    registry = TransformerRegistry()

    def _double(inputs, params):
        return {"result": inputs["value"] * params.get("factor", 2)}

    registry.register(
        "double",
        _double,
        requires_columns={"snap": ["value"]},
        description="Doubles a value.",
        params_schema={"factor": {"type": "number"}},
    )

    manifest = registry.manifest("double")
    assert manifest.name == "double"
    assert manifest.requires_columns == {"snap": ["value"]}
    assert manifest.description == "Doubles a value."

    registered = registry.get("double")
    assert registered({"value": 3}, {"factor": 4}) == {"result": 12}

    manifests = registry.list()
    assert manifests == [manifest]


def test_duplicate_registration_same_function_is_noop():
    registry = TransformerRegistry()

    def _noop(inputs, params):
        return {}

    registry.register("noop", _noop)
    registry.register("noop", _noop)  # must not raise
    assert registry.get("noop").func is _noop


def test_duplicate_registration_different_function_raises():
    registry = TransformerRegistry()

    def _a(inputs, params):
        return {}

    def _b(inputs, params):
        return {}

    registry.register("dup", _a)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("dup", _b)


def test_unknown_transformer_lists_available():
    registry = TransformerRegistry()
    registry.register("known", lambda inputs, params: {})

    with pytest.raises(KeyError, match=r"'known'"):
        registry.get("unknown")


def test_decorator_registers_on_global_registry():
    @infographic_transformer(
        "test_decorator_transform", requires_columns={"snap": ["a"]}
    )
    def _fn(inputs, params):
        return {"a": inputs["snap"]}

    from parrot.outputs.a2ui.recipes.transformers import transformer_registry

    manifest = transformer_registry.manifest("test_decorator_transform")
    assert manifest.requires_columns == {"snap": ["a"]}


def _make_step(transformer: str, inputs: list[str]) -> TransformStep:
    return TransformStep(transformer=transformer, inputs=inputs, params={}, output_key="out")


def test_gate_missing_columns_fail_fast():
    from parrot.outputs.a2ui.recipes.transformers import transformer_registry

    transformer_registry.register(
        "gate_missing_cols",
        lambda inputs, params: {},
        requires_columns={"snap": ["rev_actual", "rev_budget"]},
    )
    step = _make_step("gate_missing_cols", ["snap"])
    df = pd.DataFrame({"division": ["A"], "rev_actual": [1.0]})  # rev_budget missing

    errors = validate_inputs(step, {"snap": df}, recipe_name="test-recipe")

    assert len(errors) == 1
    assert errors[0].stage == "gate"
    assert errors[0].transformer == "gate_missing_cols"
    assert errors[0].dataset == "snap"
    assert "rev_budget" in errors[0].missing_columns


def test_gate_empty_dataset_fail_fast():
    from parrot.outputs.a2ui.recipes.transformers import transformer_registry

    transformer_registry.register(
        "gate_empty", lambda inputs, params: {}, requires_columns={"snap": []}
    )
    step = _make_step("gate_empty", ["snap"])
    df = pd.DataFrame(columns=["division"])

    errors = validate_inputs(step, {"snap": df}, recipe_name="test-recipe")

    assert len(errors) == 1
    assert errors[0].stage == "gate"
    assert "empty" in errors[0].detail.lower()


def test_gate_unknown_transformer():
    step = _make_step("does-not-exist", ["snap"])
    errors = validate_inputs(step, {"snap": pd.DataFrame({"a": [1]})})
    assert len(errors) == 1
    assert errors[0].stage == "gate"
    assert "Unknown transformer" in errors[0].detail


def test_gate_missing_alias():
    from parrot.outputs.a2ui.recipes.transformers import transformer_registry

    transformer_registry.register("gate_missing_alias", lambda inputs, params: {})
    step = _make_step("gate_missing_alias", ["missing_alias"])

    errors = validate_inputs(step, {})

    assert len(errors) == 1
    assert errors[0].dataset == "missing_alias"


def test_gate_collects_all_problems():
    from parrot.outputs.a2ui.recipes.transformers import transformer_registry

    transformer_registry.register(
        "gate_multi",
        lambda inputs, params: {},
        requires_columns={"a": ["col_a"], "b": ["col_b"]},
    )
    step = _make_step("gate_multi", ["a", "b"])
    frames = {
        "a": pd.DataFrame({"other": [1]}),
        "b": pd.DataFrame(columns=["other"]),
    }

    errors = validate_inputs(step, frames)

    # missing col_a on "a", plus empty + missing col_b on "b" == 3 errors
    assert len(errors) == 3
