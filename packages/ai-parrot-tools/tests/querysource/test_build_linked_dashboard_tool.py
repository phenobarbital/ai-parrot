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
    with pytest.raises(QuerysourceToolkitError, match="source '"):
        await toolkit.build_linked_dashboard(_widgets())


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
