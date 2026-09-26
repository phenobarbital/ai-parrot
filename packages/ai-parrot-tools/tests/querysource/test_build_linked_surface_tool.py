"""FEAT-598 TASK-3785 — qs_build_linked_surface (AC3, AC4, AC5, S5)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from parrot_tools.querysource.dialect import build_conditions
from parrot_tools.querysource.errors import InvalidConditionsError
from parrot_tools.querysource.toolkit import QuerysourceToolkit


@pytest.fixture
def fake_core_qs(patched_qs, monkeypatch):
    """Patch the executor's QuerySource seam with deterministic frames."""
    state: dict[str, list[dict[str, object]]] = {"qs": [], "mq": []}
    frame = pd.DataFrame(
        {
            "day": pd.date_range("2026-01-01", periods=12, freq="D"),
            "visits": list(range(12)),
            "program": ["epson"] * 12,
        }
    )

    class FakeQS:
        def __init__(self, **kwargs):
            state["qs"].append(kwargs)

        async def query(self, output_format=None):
            return frame, None

        async def close(self):
            return None

    class FakeMultiQS:
        def __init__(self, **kwargs):
            state["mq"].append(kwargs)

        async def query(self):
            return {"result": frame}, {}

        async def close(self):
            return None

    monkeypatch.setattr("parrot.tools.dataset_manager.sources.query_slug._get_qs", lambda: FakeQS)
    monkeypatch.setattr("parrot.tools.dataset_manager.sources.query_slug._get_multiqs", lambda: FakeMultiQS)
    return state


async def test_build_linked_surface_tool_order(fake_core_qs):
    """The tool builds a TOOL-origin envelope after exactly one execution."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    result = await toolkit.build_linked_surface(
        "epson_field_activity", {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]}
    )

    source = result["a2ui_envelope"]["metadata"]["extensions"]["parrot_data_sources"]["epson_field_activity"]
    assert len(fake_core_qs["qs"]) == 1
    assert source["target"] == "/epson_field_activity/rows"
    assert result["a2ui_envelope"]["components"][0]["data"] == {"path": "/epson_field_activity/rows"}


async def test_forced_conditions_become_locked(fake_core_qs):
    """Forced QuerySource conditions remain locked in the descriptor."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake", forced_conditions={"program": "epson"})
    result = await toolkit.build_linked_surface(
        "epson_field_activity", {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]}
    )

    source = result["a2ui_envelope"]["metadata"]["extensions"]["parrot_data_sources"]["epson_field_activity"]
    assert source["locked"] == ["program"]
    assert source["params"]["program"]["editable"] is False
    assert source["conditions"]["program"] == "epson"


async def test_variable_values_rejected(fake_core_qs):
    """Portable linked descriptors reject deployment-local @ variables."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    with pytest.raises(InvalidConditionsError):
        await toolkit.build_linked_surface(
            "epson_field_activity",
            {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]},
            request={"placeholders": {"firstdate": "@today"}},
        )


async def test_snapshot_false_still_executes(fake_core_qs):
    """Axis validation executes the slug even without an embedded snapshot."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    result = await toolkit.build_linked_surface(
        "epson_field_activity",
        {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]},
        snapshot=False,
    )

    source = result["a2ui_envelope"]["metadata"]["extensions"]["parrot_data_sources"]["epson_field_activity"]
    assert len(fake_core_qs["qs"]) == 1
    assert result["a2ui_envelope"]["dataModel"]["epson_field_activity"] == {"rows": []}
    assert source["snapshot_at"] is None


async def test_axis_validation_unknown_column(fake_core_qs):
    """Builder validation reports requested axes absent from the fetched frame."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    with pytest.raises(ValueError, match="nope"):
        await toolkit.build_linked_surface(
            "epson_field_activity", {"component": "Chart", "type": "bar", "x": "nope", "y": ["visits"]}
        )


async def test_tenant_multiquery_builds(fake_core_qs, monkeypatch):
    """Tenant-scoped MultiQuery descriptors dispatch through MultiQS."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    detail = await toolkit.describe_slug("pokemon_all_fso_odoo_new")
    monkeypatch.setattr(toolkit, "describe_slug", lambda *args, **kwargs: _return(detail.model_copy(update={"is_multiquery": True})))
    result = await toolkit.build_linked_surface(
        "pokemon_all_fso_odoo_new",
        {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]},
        tenant="acme",
    )

    source = result["a2ui_envelope"]["metadata"]["extensions"]["parrot_data_sources"]["pokemon_all_fso_odoo_new"]
    assert fake_core_qs["mq"][0]["tenant"] == "acme"
    assert source["tenant"] == "acme" and source["is_multiquery"] is True


async def _return(value):
    """Return a value from a coroutine-compatible test stub."""
    return value


def test_toolkit_build_conditions_matches_derive():
    """S5: build_conditions without lane keys matches derive_conditions fixtures."""
    from parrot.outputs.a2ui.linked import __file__ as linked_file
    from parrot.outputs.a2ui.linked.conditions import derive_conditions
    from parrot.outputs.a2ui.linked.models import SourceRequest

    fixtures = Path(linked_file).parent / "contract" / "fixtures" / "conditions"
    for fixture_path in fixtures.glob("*.json"):
        fixture = json.loads(fixture_path.read_text())
        request = fixture["request"]
        locked = fixture["locked"]
        payload = build_conditions(
            placeholders=request.get("placeholders"),
            filter=request.get("filter"),
            fields=request.get("fields"),
            ordering=request.get("ordering"),
            grouping=request.get("grouping"),
            limit=request.get("limit"),
            offset=request.get("offset"),
            refresh=False,
            max_rows=5000,
            forced=locked,
        )
        payload.pop("querylimit")
        payload.pop("refresh", None)
        assert payload == derive_conditions(SourceRequest.model_validate(request), locked=locked)
