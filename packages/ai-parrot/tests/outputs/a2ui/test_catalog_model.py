"""Catalog schema -> Pydantic generation (FEAT-755 TASK-4762)."""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from pydantic import BaseModel, ValidationError

from parrot.outputs.a2ui.builders import build_card, build_graph, build_kpicard
from parrot.outputs.a2ui.catalog import get_component
from parrot.outputs.a2ui.catalog._model import clear_model_cache, component_model, model_from_schema
from parrot.outputs.a2ui.graph import GraphSpec

_ENVELOPE_KEYS = {"id", "component", "catalogId"}
_BASE = {"label": "x", "value": 1}


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_model_cache()
    yield
    clear_model_cache()


def _kpi() -> type[BaseModel]:
    return component_model("KPICard")


def _props(envelope: Any) -> dict[str, Any]:
    """The component config a builder produced, minus the envelope wrapper keys."""
    dumped = envelope.components[0].model_dump(by_alias=True, exclude_none=True)
    return {k: v for k, v in dumped.items() if k not in _ENVELOPE_KEYS}


class TestLooseVocabulary:
    @pytest.mark.parametrize("field", ["value", "delta"])
    @pytest.mark.parametrize("payload", [42, 3.5, "1.2k", {"path": "/p"}])
    def test_untyped_accepts_anything(self, field: str, payload: Any) -> None:
        inst = _kpi().model_validate({**_BASE, field: payload})
        assert getattr(inst, field) == payload

    @pytest.mark.parametrize("payload", [[{"date": "2026-01-01", "value": 1}], {"path": "/series"}])
    def test_series_list_or_dict(self, payload: Any) -> None:
        assert _kpi().model_validate({**_BASE, "series": payload}).series == payload

    def test_higher_is_better_four_outcomes(self) -> None:
        model = _kpi()
        outcomes = [
            model.model_validate({**_BASE, **p}).model_dump(exclude_unset=True).get("higherIsBetter", "<omitted>")
            for p in ({"higherIsBetter": True}, {"higherIsBetter": False}, {"higherIsBetter": None}, {})
        ]
        assert outcomes == [True, False, None, "<omitted>"]

    def test_enum_literal(self) -> None:
        assert _kpi().model_validate({**_BASE, "trend": "up"}).trend == "up"
        with pytest.raises(ValidationError):
            _kpi().model_validate({**_BASE, "trend": "sideways"})

    def test_optional_and_required(self) -> None:
        inst = _kpi().model_validate(_BASE)
        assert inst.unit is None and inst.trend is None
        info = component_model("InfoCard")
        info.model_validate({"title": "t"})
        with pytest.raises(ValidationError):
            info.model_validate({"body": "no title"})

    def test_extra_allowed_and_description_verbatim(self) -> None:
        model = _kpi()
        assert model.model_config.get("extra") == "allow"
        assert model.model_validate({**_BASE, "unknown": {"path": "/x"}}).model_extra == {"unknown": {"path": "/x"}}
        schema = get_component("KPICard").definition.schema_
        assert model.model_fields["value"].description == schema["properties"]["value"]["description"]

    def test_nested_and_awkward_names(self) -> None:
        model = model_from_schema(
            {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
                    },
                },
            },
            name="Probe",
        )
        inst = model.model_validate({"from": "a", "items": [{"n": 1, "extra": 2}]})
        assert inst.model_dump(by_alias=True, exclude_unset=True)["from"] == "a"
        with pytest.raises(ValidationError):
            model.model_validate({"items": [{}]})


class TestSourceModel:
    def test_graph_identity(self) -> None:
        assert component_model("Graph") is GraphSpec

    def test_cyclic_dag_still_raises(self) -> None:
        with pytest.raises(ValidationError):
            component_model("Graph").model_validate(
                {
                    "kind": "dag",
                    "nodes": [{"id": "a"}, {"id": "b"}],
                    "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
                    "accessibleDescription": "cycle",
                }
            )

    @pytest.mark.parametrize("name", ["KPICard", "InfoCard", "Timeline"])
    def test_generated_and_cached(self, name: str) -> None:
        first = component_model(name)
        assert issubclass(first, BaseModel) and first is not GraphSpec
        assert component_model(name) is first
        clear_model_cache()
        assert component_model(name) is not first

    def test_unregistered_raises_keyerror(self) -> None:
        with pytest.raises(KeyError):
            component_model("NoSuchComponent")


def _fidelity_cases() -> list[tuple[str, dict[str, Any]]]:
    return [
        ("KPICard", _props(build_kpicard(label="Revenue", value=42, unit="$", trend="up"))),
        ("KPICard", {"label": "Hours", "value": {"path": "/h"}, "delta": "+3%", "higherIsBetter": None}),
        ("KPICard", {"label": "Defects", "value": 7, "higherIsBetter": False, "series": {"path": "/s"}}),
        ("InfoCard", _props(build_card(title="Hello", subtitle="World", body="Body text"))),
        ("Timeline", {"title": "T", "events": [{"title": "a", "timestamp": "2026-01-01"}, {"title": "b"}]}),
        (
            "Graph",
            _props(
                build_graph(
                    nodes=[{"id": "a", "label": "Start"}, {"id": "b", "label": "End"}],
                    edges=[{"from": "a", "to": "b", "label": "go"}],
                    accessible_description="Tiny graph",
                )
            ),
        ),
    ]


class TestFidelity:
    """G6: the generated model is never stricter than its catalog schema."""

    @pytest.mark.parametrize(("name", "config"), _fidelity_cases())
    def test_schema_valid_implies_model_valid(self, name: str, config: dict[str, Any]) -> None:
        schema = get_component(name).definition.schema_
        jsonschema.validate(config, schema)
        component_model(name).model_validate(config)
