"""FEAT-636 TASK-4104 — PythonTransform wire model, 3-way XOR, terminal rule."""

import pytest
from pydantic import ValidationError

from parrot.outputs.a2ui.linked.models import LinkedSources, TransformSpec

PY = {"python": {"transformer": "division_breakdown", "params": {"period": "Q3"}}}


def _src(target: str, transform: dict | None = None) -> dict:
    return {"slug": "sales", "conditions": {}, "request": {}, "target": target, "transform": transform}


def test_python_member_parses_with_defaults() -> None:
    spec = TransformSpec.model_validate(PY)
    assert spec.python.input_alias == "source" and spec.python.output is None


@pytest.mark.parametrize("payload", [{}, {**PY, "ops": [{"op": "limit", "n": 1}]}])
def test_transform_spec_xor_three(payload: dict) -> None:
    with pytest.raises(ValidationError, match="exactly one of 'ops', 'ref' or 'python'"):
        TransformSpec.model_validate(payload)


def test_derived_rejects_python() -> None:
    with pytest.raises(ValidationError, match="derived source requires inline transform.ops"):
        LinkedSources.model_validate(
            {
                "sales": _src("/sales"),
                "view": {"from": "sales", "transform": PY, "target": "/view"},
            }
        )


@pytest.mark.parametrize("consumer", ["derived", "join", "union"])
def test_python_source_is_terminal(consumer: str) -> None:
    sources = {"sales": _src("/sales", PY)}
    if consumer == "derived":
        sources["view"] = {"from": "sales", "transform": {"ops": [{"op": "limit", "n": 1}]}, "target": "/view"}
    elif consumer == "join":
        sources["view"] = _src(
            "/view", {"ops": [{"op": "join", "with": "sales", "on": [{"left": "id", "right": "id"}]}]}
        )
    else:
        sources["view"] = _src("/view", {"ops": [{"op": "union", "sources": ["sales"]}]})

    with pytest.raises(ValidationError, match="terminal"):
        LinkedSources.model_validate(sources)


def test_existing_descriptor_unchanged() -> None:
    sources = LinkedSources.model_validate({"sales": _src("/sales", {"ops": [{"op": "limit", "n": 5}]})})
    assert sources.root["sales"].transform.python is None
