"""FEAT-598 TASK-3790 — every published envelope fixture is TOOL-valid, LLM-rejected, bakeable and schema-valid."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pandas as pd
import pytest

import parrot.outputs.a2ui.linked as linked_pkg
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.builders import build_linked_surface
from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.linked.conditions import derive_conditions
from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest, TransformSpec
from parrot.outputs.a2ui.models import CreateSurface

CONTRACT = Path(linked_pkg.__file__).parent / "contract"
ENVELOPES = sorted((CONTRACT / "fixtures" / "envelopes").glob("*.json"))
FIXED_SNAPSHOT_AT = "2026-09-25T00:00:00+00:00"


def _dump(envelope: CreateSurface) -> str:
    return (
        json.dumps(envelope.model_dump(mode="json", by_alias=True, exclude_none=True), sort_keys=True, indent=2) + "\n"
    )


def _request() -> SourceRequest:
    return SourceRequest(placeholders={"firstdate": "YESTERDAY", "lastdate": "TODAY"})


def _activity_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "day": pd.date_range("2026-09-01", periods=3),
            "visits": [10, 20, 30],
            "program": ["epson", "pokemon", "epson"],
        }
    )


def _targets_frame() -> pd.DataFrame:
    return pd.DataFrame({"program": ["epson", "pokemon"], "target": [100, 50]})


def _mq_frame() -> pd.DataFrame:
    return pd.DataFrame({"result": ["ok", "ok"], "count": [1, 2]})


def _build_linked_dashboard_join() -> CreateSurface:
    """Two sources ("activity", "targets"); "activity" joins into "targets" (S4/S5/AC16)."""
    request = _request()
    activity = LinkedDataSource(
        slug="epson_field_activity",
        conditions=derive_conditions(request, locked={}),
        request=request,
        target="/activity/rows",
        snapshot_at=FIXED_SNAPSHOT_AT,
        transform=TransformSpec(
            ops=[{"op": "join", "with": "targets", "how": "left", "on": [{"left": "program", "right": "program"}]}]
        ),
    )
    targets = LinkedDataSource(
        slug="epson_program_targets",
        conditions=derive_conditions(request, locked={}),
        request=request,
        target="/targets/rows",
        snapshot_at=FIXED_SNAPSHOT_AT,
    )
    components = [
        {"id": "root", "component": "Column", "children": ["chart", "table"]},
        {
            "id": "chart",
            "component": "Chart",
            "type": "bar",
            "x": "day",
            "y": ["visits"],
            "data": {"path": "/activity/rows"},
        },
        {
            "id": "table",
            "component": "DataTable",
            "columns": [{"name": "program"}, {"name": "target"}],
            "data": {"path": "/targets/rows"},
        },
    ]
    return build_linked_surface(
        components,
        {"activity": activity, "targets": targets},
        {"activity": _activity_frame(), "targets": _targets_frame()},
        surface_id="linked-dashboard-join",
    )


def _build_linked_multiquery_public() -> CreateSurface:
    """One MultiQuery source, public (``tenant=None``), selecting a ``multi_output`` (spec §3 M12)."""
    request = _request()
    source = LinkedDataSource(
        slug="epson_multiquery",
        tenant=None,
        is_multiquery=True,
        multi_output="result",
        conditions=derive_conditions(request, locked={}),
        request=request,
        target="/mq/rows",
        snapshot_at=FIXED_SNAPSHOT_AT,
    )
    components = [
        {
            "id": "root",
            "component": "DataTable",
            "columns": [{"name": "result"}, {"name": "count"}],
            "data": {"path": "/mq/rows"},
        },
    ]
    return build_linked_surface(components, {"mq": source}, {"mq": _mq_frame()}, surface_id="linked-multiquery-public")


@pytest.mark.parametrize(
    "name,builder",
    [
        ("linked_dashboard_join.json", _build_linked_dashboard_join),
        ("linked_multiquery_public.json", _build_linked_multiquery_public),
    ],
)
def test_envelope_fixture_is_regenerable(name, builder):
    assert (CONTRACT / "fixtures" / "envelopes" / name).read_text() == _dump(builder())


def test_all_four_envelope_fixtures_present():
    assert {p.name for p in ENVELOPES} >= {
        "linked_chart.json",
        "linked_no_snapshot.json",
        "linked_dashboard_join.json",
        "linked_multiquery_public.json",
    }


@pytest.mark.parametrize("path", ENVELOPES, ids=lambda p: p.name)
def test_envelope_fixture_contract(path):
    envelope = CreateSurface.model_validate(json.loads(path.read_text()))
    validate_envelope(envelope, origin=ProducerOrigin.TOOL)
    with pytest.raises(CatalogValidationError) as exc_info:
        validate_envelope(envelope, origin=ProducerOrigin.LLM)  # DATA_SOURCES_NOT_ALLOWED_FOR_LLM (AC2)
    codes = [issue["code"] for issue in exc_info.value.issues]
    assert "DATA_SOURCES_NOT_ALLOWED_FOR_LLM" in codes
    bake_envelope(envelope)  # every binding resolves, snapshot or not (AC16)
    schema = json.loads((CONTRACT / "schema.json").read_text())
    jsonschema.validate(envelope.metadata.extensions.root["parrot_data_sources"], schema)
