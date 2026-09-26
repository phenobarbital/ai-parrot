"""Relational DSL ops — semantics fixed in spec §7 (FEAT-598 M2)."""

import json
from pathlib import Path

import pytest
from pandas.testing import assert_frame_equal

import parrot.outputs.a2ui.linked
from parrot.outputs.a2ui.linked.dsl import TransformError, apply_transform, frame_from_records, frame_to_records
from parrot.outputs.a2ui.linked.models import TransformSpec


def _run(
    rows: list[dict[str, object]],
    ops: list[dict[str, object]],
    frames: dict[str, list[dict[str, object]]] | None = None,
) -> list[dict[str, object]]:
    """Execute one relational transform with record-shaped sibling frames."""
    spec = TransformSpec.model_validate({"ops": ops})
    siblings = {key: frame_from_records(value) for key, value in (frames or {}).items()}
    return frame_to_records(apply_transform(frame_from_records(rows), spec, frames=siblings))


DSL_DIR = Path(parrot.outputs.a2ui.linked.__file__).parent / "contract" / "fixtures" / "dsl"
RELATIONAL_FIXTURES = [
    "group_by_sum",
    "group_by_all_aggs",
    "pivot_basic",
    "join_inner",
    "join_left_null_never_matches",
    "join_prefix_on_collision",
    "union_matching_columns",
]


@pytest.mark.parametrize("fixture_name", RELATIONAL_FIXTURES)
def test_dsl_golden_relational(fixture_name: str) -> None:
    """Run each relational shared-contract fixture through the Python executor."""
    case = json.loads((DSL_DIR / f"{fixture_name}.json").read_text())
    assert _run(case["input"], case["ops"], case.get("frames")) == case["expected"]


def test_dsl_join_null_never_matches() -> None:
    """A left null key survives but cannot match a null sibling key."""
    result = _run(
        [{"key": None, "left": 1}],
        [{"op": "join", "with": "right", "how": "left", "on": [{"left": "key", "right": "key"}]}],
        {"right": [{"key": None, "value": 2}]},
    )
    assert result == [{"key": None, "left": 1, "value": None}]


def test_dsl_join_prefix_on_collision() -> None:
    """A colliding right non-key column is deterministically sibling-prefixed."""
    result = _run(
        [{"key": "a", "value": 1}],
        [{"op": "join", "with": "right", "on": [{"left": "key", "right": "key"}]}],
        {"right": [{"key": "a", "value": 2}]},
    )
    assert result == [{"key": "a", "value": 1, "right_value": 2}]


def test_dsl_union_by_matching_columns() -> None:
    """Union uses only intersecting columns in the own frame's column order."""
    result = _run(
        [{"a": 1, "b": 2, "c": 3}],
        [{"op": "union", "sources": ["right"]}],
        {"right": [{"b": 4, "a": 5, "d": 6}]},
    )
    assert result == [{"a": 1, "b": 2}, {"a": 5, "b": 4}]


def test_join_missing_sibling_raises_transform_error() -> None:
    """An absent sibling source reports the failing join operation index."""
    spec = TransformSpec.model_validate(
        {"ops": [{"op": "limit", "n": 1}, {"op": "join", "with": "missing", "on": [{"left": "key", "right": "key"}]}]}
    )
    with pytest.raises(TransformError, match="sibling source 'missing' was not executed") as caught:
        apply_transform(frame_from_records([{"key": "a"}]), spec, frames={})
    assert caught.value.op_index == 1


def test_group_by_first_appearance_order() -> None:
    """Groups remain in input first-appearance order rather than sorted key order."""
    result = _run(
        [{"program": "z", "value": 1}, {"program": "a", "value": 2}, {"program": "z", "value": 3}],
        [{"op": "group_by", "by": ["program"], "aggregate": {"value": "sum"}}],
    )
    assert result == [{"program": "z", "value": 4}, {"program": "a", "value": 2}]


def test_relational_ops_do_not_mutate_siblings() -> None:
    """Join and union read sibling frames without changing their columns or rows."""
    sibling = frame_from_records([{"key": "a", "value": 2}, {"key": None, "value": 3}])
    before = sibling.copy(deep=True)
    join_spec = TransformSpec.model_validate(
        {"ops": [{"op": "join", "with": "right", "how": "left", "on": [{"left": "key", "right": "key"}]}]}
    )
    union_spec = TransformSpec.model_validate({"ops": [{"op": "union", "sources": ["right"]}]})
    apply_transform(frame_from_records([{"key": "a", "value": 1}]), join_spec, frames={"right": sibling})
    apply_transform(frame_from_records([{"key": "a", "value": 1}]), union_spec, frames={"right": sibling})
    assert_frame_equal(sibling, before)
