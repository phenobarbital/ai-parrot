"""FEAT-754 M5 — build_c4_diagram / build_graph(level=)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parrot.outputs.a2ui import builders
from parrot.outputs.a2ui.builders import build_c4_diagram, build_graph
from parrot.outputs.a2ui.catalog import ProducerOrigin
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.models import Action, EventAction

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "c4_container_diagram.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def _c4(**kwargs):
    d = _fixture()
    return build_c4_diagram(
        level=d["level"],
        nodes=d["nodes"],
        edges=d["edges"],
        boundaries=d["groups"],
        title=d["title"],
        **kwargs,
    )


def test_build_c4_diagram_fills_positions_and_catalog_id() -> None:
    envelope = _c4()
    comp = envelope.components[0]
    assert comp.catalog_id == VIZ_CORE_CATALOG_ID
    assert comp.model_extra["kind"] == "c4"
    assert comp.model_extra["level"] == "container"
    positions = comp.model_extra["layout"]["positions"]
    for node in _fixture()["nodes"]:
        assert positions[node["id"]] is not None
    assert envelope.surface_id == "c4-diagram"


def test_build_graph_level_passthrough() -> None:
    d = _fixture()
    envelope = build_graph(
        nodes=d["nodes"], edges=d["edges"], groups=d["groups"], kind="c4", level="container", title=d["title"]
    )
    comp = envelope.components[0]
    assert comp.model_extra["level"] == "container"
    assert comp.model_extra == _c4().components[0].model_extra


def test_build_c4_diagram_in_all() -> None:
    assert "build_c4_diagram" in builders.__all__


def test_build_c4_diagram_action_tool_origin_only() -> None:
    action = Action(event=EventAction(name="select"))
    assert _c4(action=action).components[0].action is not None
    with pytest.raises(CatalogValidationError):
        _c4(action=action, origin=ProducerOrigin.LLM)


def test_c4_node_state_and_action_still_work() -> None:
    action = Action(event=EventAction(name="select"))
    comp = _c4(action=action).components[0]
    api = next(n for n in comp.model_extra["nodes"] if n["id"] == "api")
    assert api["state"] == "running"
    assert comp.action is not None
