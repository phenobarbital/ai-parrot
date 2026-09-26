"""Core DSL error paths and invariants (FEAT-598 M2)."""

import pytest
from pandas.testing import assert_frame_equal

from parrot.outputs.a2ui.linked.dsl import TransformError, apply_transform, frame_from_records
from parrot.outputs.a2ui.linked.models import TransformRef, TransformSpec


def test_dsl_ref_is_skipped_in_python() -> None:
    """A renderer-owned reference preserves the exact input frame object."""
    frame = frame_from_records([{"value": 1}])
    spec = TransformSpec(ref=TransformRef(name="group_by_day@1.0.0", integrity="sha384-x"))
    assert apply_transform(frame, spec, frames={}) is frame


def test_dsl_derive_rejects_non_arith() -> None:
    """String columns cannot participate in arithmetic derivations."""
    spec = TransformSpec.model_validate({"ops": [{"op": "derive", "name": "bad", "expr": "name"}]})
    with pytest.raises(TransformError, match="not numeric") as caught:
        apply_transform(frame_from_records([{"name": "one"}]), spec, frames={})
    assert caught.value.op_index == 0


def test_select_unknown_column_raises() -> None:
    """Unknown selected columns report their operation index."""
    spec = TransformSpec.model_validate({"ops": [{"op": "select", "columns": ["missing"]}]})
    with pytest.raises(TransformError) as caught:
        apply_transform(frame_from_records([{"known": 1}]), spec, frames={})
    assert caught.value.op_index == 0


def test_apply_transform_does_not_mutate_input() -> None:
    """Each operation works on a copy of its input frame."""
    frame = frame_from_records([{"value": 1}, {"value": 2}])
    before = frame.copy(deep=True)
    spec = TransformSpec.model_validate({"ops": [{"op": "derive", "name": "plus_one", "expr": {"operator": "+", "left": "value", "right": 1}}]})
    apply_transform(frame, spec, frames={})
    assert_frame_equal(frame, before)


def test_limit_larger_than_frame_returns_all() -> None:
    """A limit above the frame length retains every row."""
    frame = frame_from_records([{"value": 1}, {"value": 2}])
    spec = TransformSpec.model_validate({"ops": [{"op": "limit", "n": 3}]})
    assert_frame_equal(apply_transform(frame, spec, frames={}), frame)


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [("eq", 3, [3]), ("ne", 3, [1]), ("gt", 1, [3]), ("le", 1, [1])],
)
def test_filter_operators_not_covered_by_golden(operator: str, value: int, expected: list[int]) -> None:
    """Cover the remaining scalar filter operations beyond the chained fixture."""
    spec = TransformSpec.model_validate({"ops": [{"op": "filter", "column": "value", "operator": operator, "value": value}]})
    result = apply_transform(frame_from_records([{"value": 1}, {"value": 3}, {"value": None}]), spec, frames={})
    assert result["value"].tolist() == expected
