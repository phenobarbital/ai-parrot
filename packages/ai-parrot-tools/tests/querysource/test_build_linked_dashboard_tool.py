"""FEAT-610 TASK-3847 — qs_build_linked_dashboard (AC1, AC2, S1, S3, S8)."""

from __future__ import annotations

import pandas as pd
import pytest

from parrot.outputs.a2ui.catalog import ProducerOrigin, validate_envelope
from parrot.outputs.a2ui.models import CreateSurface
from parrot_tools.querysource.errors import InvalidConditionsError, QuerysourceToolkitError
from parrot_tools.querysource.toolkit import QuerysourceToolkit

SLUG = "epson_field_activity"


@pytest.fixture
def fake_core_qs(patched_qs, monkeypatch):
    """Patch the executor's QuerySource seam with deterministic frames."""
    state: dict[str, list[dict[str, object]]] = {"qs": [], "fail": []}
    frame = pd.DataFrame(
        {
            "day": pd.date_range("2026-01-01", periods=6, freq="D"),
            "visits": list(range(6)),
            "total": [10, 20, 30, 40, 50, 60],
            "program": ["epson"] * 6,
        }
    )

    class FakeQS:
        def __init__(self, **kwargs):
            state["qs"].append(kwargs)

        async def query(self, output_format=None):
            if state["fail"]:
                raise RuntimeError("boom")
            return frame, None

        async def close(self):
            return None

    monkeypatch.setattr("parrot.tools.dataset_manager.sources.query_slug._get_qs", lambda: FakeQS)
    return state


def _widgets() -> list[dict]:
    kpis = [
        {"key": f"kpi_{i}", "slug": SLUG, "component": {"component": "KPICard", "value": "total"}} for i in range(4)
    ]
    charts = [
        {
            "key": f"bar_{i}",
            "slug": SLUG,
            "component": {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]},
        }
        for i in range(2)
    ]
    charts.append(
        {"key": "pie_0", "slug": SLUG, "component": {"component": "Chart", "type": "pie", "x": "day", "y": ["visits"]}}
    )
    table = [{"key": "table_0", "slug": SLUG, "component": {"component": "DataTable"}}]
    return [*kpis, *charts, *table]


def _reachable(components: list[dict]) -> set[str]:
    by_id = {c["id"]: c for c in components}
    seen: set[str] = set()
    stack = ["root"]
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        stack.extend(by_id[cid].get("children") or [])
    return seen


async def test_build_linked_dashboard_one_envelope(fake_core_qs):
    """Eight widgets yield one TOOL-origin surface with eight sources."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    result = await toolkit.build_linked_dashboard(_widgets(), title="Dash")

    env = result["a2ui_envelope"]
    sources = env["metadata"]["extensions"]["parrot_data_sources"]
    assert len(sources) == 8
    assert len(fake_core_qs["qs"]) == 8
    # Definition-only by default: every source is probed with one row and the envelope carries no rows.
    assert all(call["conditions"]["querylimit"] == 1 for call in fake_core_qs["qs"])
    assert all(env["dataModel"][key] == {"rows": []} for key in sources)
    assert all(source["snapshot_at"] is None for source in sources.values())
    ids = [c["id"] for c in env["components"]]
    assert len(ids) == len(set(ids))
    assert {"root", "row_kpis", "row_charts", "table_0", "title"} <= set(ids)
    validate_envelope(CreateSurface.model_validate(env), origin=ProducerOrigin.TOOL)
    assert result["artifacts"][0]["sources"] == list(sources)


async def test_build_linked_dashboard_reachability(fake_core_qs):
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    result = await toolkit.build_linked_dashboard(_widgets())
    env = result["a2ui_envelope"]
    comps = env["components"]
    assert _reachable(comps) == {c["id"] for c in comps}
    sources = env["metadata"]["extensions"]["parrot_data_sources"]
    for comp in comps:
        data = comp.get("data") or comp.get("value")
        if isinstance(data, dict) and "path" in data:
            assert data["path"].split("/")[1] in sources


async def test_build_linked_dashboard_kpi_bindings(fake_core_qs):
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    result = await toolkit.build_linked_dashboard(_widgets())
    by_id = {c["id"]: c for c in result["a2ui_envelope"]["components"]}
    assert by_id["kpi_2"]["value"] == {"path": "/kpi_2/rows/0/total"}


@pytest.mark.parametrize("bad", ["kpi_0", "bad-key", "1abc", "root"])
async def test_build_linked_dashboard_duplicate_key(fake_core_qs, bad):
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    widgets = _widgets()
    widgets[-1]["key"] = bad
    with pytest.raises(InvalidConditionsError):
        await toolkit.build_linked_dashboard(widgets)
    assert fake_core_qs["qs"] == []


async def test_build_linked_dashboard_kpi_needs_column(fake_core_qs):
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    widgets = [{"key": "k", "slug": SLUG, "component": {"component": "KPICard"}}]
    with pytest.raises(InvalidConditionsError):
        await toolkit.build_linked_dashboard(widgets)


async def test_build_linked_dashboard_source_failure(fake_core_qs):
    fake_core_qs["fail"].append(True)
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    with pytest.raises(
        QuerysourceToolkitError, match=r"source\(s\) failed while building the linked dashboard: 'kpi_0'"
    ):
        await toolkit.build_linked_dashboard(_widgets())


def _shared_dashboard() -> tuple[dict, list[dict]]:
    """Dashboard-owned sources: one `kpis` query feeding four KPICards, one `rows` query feeding a grid and two
    derived charts, plus one inline widget and one widget with its own slug."""
    sources = {
        "kpis": {"slug": SLUG, "request": {"fields": ["sum(visits) as total"]}},
        "rows": {"slug": SLUG, "request": {"limit": 500}},
    }
    widgets = [
        *[
            {"key": f"kpi_{i}", "source": "kpis", "component": {"component": "KPICard", "value": "total"}}
            for i in range(4)
        ],
        {
            "key": "by_program",
            "source": "rows",
            "transform": {"ops": [{"op": "group_by", "by": ["program"], "aggregate": {"visits": "sum"}}]},
            "component": {"component": "Chart", "type": "pie", "x": "program", "y": ["visits"]},
        },
        {
            "key": "by_day",
            "source": "rows",
            "transform": {"ops": [{"op": "select", "columns": ["day", "visits"]}]},
            "component": {"component": "Chart", "type": "bar", "x": "day", "y": ["visits"]},
        },
        {"key": "grid", "source": "rows", "component": {"component": "DataTable"}},
        {
            "key": "static",
            "data": [{"k": "a", "v": 1}, {"k": "b", "v": 2}],
            "component": {"component": "Chart", "type": "bar", "x": "k", "y": ["v"]},
        },
        {"key": "own", "slug": SLUG, "component": {"component": "KPICard", "value": "total"}},
    ]
    return sources, widgets


async def test_build_linked_dashboard_shared_sources(fake_core_qs):
    """Two dashboard sources + one own-slug widget → three QuerySource calls for nine widgets."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    sources, widgets = _shared_dashboard()
    result = await toolkit.build_linked_dashboard(widgets, sources=sources, title="Shared", snapshot=True)

    env = result["a2ui_envelope"]
    descriptors = env["metadata"]["extensions"]["parrot_data_sources"]
    assert len(fake_core_qs["qs"]) == 3
    assert set(descriptors) == {"kpis", "rows", "by_program", "by_day", "own"}
    assert descriptors["by_program"]["kind"] == "derived" and descriptors["by_program"]["from"] == "rows"
    assert descriptors["kpis"]["kind"] == "query_slug"
    by_id = {c["id"]: c for c in env["components"]}
    assert by_id["kpi_2"]["value"] == {"path": "/kpis/rows/0/total"}
    assert by_id["grid"]["data"] == {"path": "/rows/rows"}
    assert by_id["by_program"]["data"] == {"path": "/by_program/rows"}
    assert by_id["static"]["data"] == {"path": "/static/rows"}
    assert by_id["own"]["value"] == {"path": "/own/rows/0/total"}
    assert env["dataModel"]["static"] == {"rows": [{"k": "a", "v": 1}, {"k": "b", "v": 2}]}
    assert env["dataModel"]["by_program"]["rows"] == [{"program": "epson", "visits": 15}]
    assert "static" not in descriptors
    assert _reachable(env["components"]) == {c["id"] for c in env["components"]}
    validate_envelope(CreateSurface.model_validate(env), origin=ProducerOrigin.TOOL)
    artifact = result["artifacts"][0]
    assert artifact["shared"] == ["kpis", "rows"]
    assert artifact["derived"] == ["by_program", "by_day"]
    assert artifact["inline"] == ["static"]


async def test_build_linked_dashboard_shared_sources_definition_only(fake_core_qs):
    """Default (snapshot=False): shared and own sources are probed once each; derived views and query sources carry
    no rows, inline data is still baked in."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    sources, widgets = _shared_dashboard()
    result = await toolkit.build_linked_dashboard(widgets, sources=sources)

    env = result["a2ui_envelope"]
    descriptors = env["metadata"]["extensions"]["parrot_data_sources"]
    assert len(fake_core_qs["qs"]) == 3
    assert set(descriptors) == {"kpis", "rows", "by_program", "by_day", "own"}
    assert all(descriptor.get("snapshot_at") is None for descriptor in descriptors.values())
    for key in descriptors:
        assert not env["dataModel"].get(key, {}).get("rows")
    assert env["dataModel"]["static"] == {"rows": [{"k": "a", "v": 1}, {"k": "b", "v": 2}]}
    validate_envelope(CreateSurface.model_validate(env), origin=ProducerOrigin.TOOL)


@pytest.mark.parametrize(
    "widget",
    [
        {"key": "w", "source": "missing", "component": {"component": "KPICard", "value": "total"}},
        {"key": "kpis", "source": "kpis", "component": {"component": "KPICard", "value": "total"}},
        {"key": "w", "transform": {"ops": []}, "slug": SLUG, "component": {"component": "DataTable"}},
        {"key": "w", "source": "kpis", "slug": SLUG, "component": {"component": "DataTable"}},
        {"key": "w", "component": {"component": "DataTable"}},
        {"key": "w", "source": "kpis", "request": {"limit": 1}, "component": {"component": "DataTable"}},
        {"key": "w", "data": [], "component": {"component": "DataTable"}},
        {"key": "w", "source": "kpis", "transform": {"ops": [{"op": "nope"}]}, "component": {"component": "DataTable"}},
    ],
    ids=[
        "unknown-source",
        "key-collides-with-source",
        "transform-without-source",
        "two-origins",
        "no-origin",
        "request-without-slug",
        "empty-inline",
        "bad-transform",
    ],
)
async def test_build_linked_dashboard_rejects_bad_origins(fake_core_qs, widget):
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    with pytest.raises(InvalidConditionsError):
        await toolkit.build_linked_dashboard([widget], sources={"kpis": {"slug": SLUG}})
    assert fake_core_qs["qs"] == []


async def test_build_linked_dashboard_derived_failure_reported(fake_core_qs):
    """A derived view over a missing column fails the build with a 'derived from' label."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    widgets = [
        {
            "key": "view",
            "source": "rows",
            "transform": {"ops": [{"op": "select", "columns": ["missing"]}]},
            "component": {"component": "DataTable"},
        }
    ]
    with pytest.raises(QuerysourceToolkitError, match=r"'view' \(derived from rows\): data_stage"):
        await toolkit.build_linked_dashboard(widgets, sources={"rows": {"slug": SLUG}})


async def test_build_linked_dashboard_tool_schema():
    """The generated tool schema exposes `sources` as an object of objects."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    tool = next(t for t in toolkit.get_tools() if t.name == "qs_build_linked_dashboard")
    schema = tool.args_schema.model_json_schema()
    assert "sources" in schema["properties"]
    assert "widgets" in schema["properties"]


async def test_build_linked_dashboard_jsonb_kpi(fake_core_qs):
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    widgets = [
        {
            "key": "pilates",
            "slug": SLUG,
            "component": {"component": "KPICard", "value": "total"},
            "request": {"filter": {"graduation_details": {"@>": [{"course": "Pilates Studio"}]}}},
        }
    ]
    result = await toolkit.build_linked_dashboard(widgets)
    source = result["a2ui_envelope"]["metadata"]["extensions"]["parrot_data_sources"]["pilates"]
    assert source["conditions"]["filter"]["graduation_details"] == {"@>": [{"course": "Pilates Studio"}]}


async def test_build_linked_dashboard_snapshot_true_embeds_rows(fake_core_qs):
    """snapshot=True runs every query in full and embeds the rows."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    result = await toolkit.build_linked_dashboard(_widgets(), snapshot=True)
    env = result["a2ui_envelope"]
    assert all(call["conditions"]["querylimit"] == 5000 for call in fake_core_qs["qs"])
    assert all(len(env["dataModel"][key]["rows"]) == 6 for key in env["dataModel"])


async def test_build_linked_dashboard_manual_policy_warns_without_snapshot(fake_core_qs, caplog):
    """A manual-refresh widget without a snapshot renders empty in the admin lane, so the toolkit warns."""
    toolkit = QuerysourceToolkit(dsn="postgres://fake")
    widgets = _widgets()
    widgets[0]["refresh"] = {"policy": "manual"}
    with caplog.at_level("WARNING"):
        await toolkit.build_linked_dashboard(widgets)
    assert any("kpi_0" in record.message and "manual" in record.message for record in caplog.records)
