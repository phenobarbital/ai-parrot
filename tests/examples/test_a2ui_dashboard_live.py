"""FEAT-610 TASK-3848 — opt-in production verification for the dashboard widgets."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from parrot_tools.querysource.errors import SlugNotFoundError
from parrot_tools.querysource.toolkit import QuerysourceToolkit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "a2ui"))
import dashboard  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.getenv("PARROT_TEST_QS_LIVE") != "1" or os.getenv("ENV") != "prod",
    reason="requires PARROT_TEST_QS_LIVE=1 and ENV=prod",
)


@pytest.mark.asyncio
async def test_linked_dashboard_live() -> None:
    """The production query map reproduces the verified values and sources."""
    toolkit = QuerysourceToolkit(programs=["polestar"])
    try:
        await toolkit.describe_slug(dashboard.BY_COURSE_SLUG)
    except SlugNotFoundError:
        widgets = [widget for widget in dashboard.WIDGETS if widget["key"] != "by_course"]
    else:
        widgets = dashboard.WIDGETS

    result = await toolkit.build_linked_dashboard(
        widgets,
        title="Polestar graduates dashboard",
        snapshot=True,  # this test asserts the embedded rows; the default build is definition-only
    )
    envelope = result["a2ui_envelope"]
    data_model = envelope["dataModel"]
    sources = envelope["metadata"]["extensions"]["parrot_data_sources"]

    assert data_model["kpi_total"]["rows"][0]["total"] == 17572
    assert data_model["kpi_studio"]["rows"][0]["total"] == 9191
    assert data_model["kpi_mat"]["rows"][0]["total"] == 6245
    assert data_model["kpi_multi"]["rows"][0]["multi_graduates"] == 2884
    assert len(data_model["by_country"]["rows"]) == 95
    assert len(data_model["by_licensee"]["rows"]) == 23
    assert len(data_model["graduates"]["rows"]) == 500
    assert set(sources) == {widget["key"] for widget in dashboard.WIDGETS}

    if "by_course" in data_model:
        by_course = data_model["by_course"]["rows"]
        counts = {row["course"]: row["graduates"] for row in by_course}
        assert counts == {"Pilates Studio": 9204, "Pilates Mat": 6247, "Pilates Rehab": 3300, "Pilates Reformer": 2048}


@pytest.mark.asyncio
async def test_linked_dashboard_live_default_is_definition_only() -> None:
    """The default build probes every slug with one row and ships no rows in the envelope."""
    toolkit = QuerysourceToolkit(programs=["polestar"])
    widgets = [widget for widget in dashboard.WIDGETS if widget["key"] != "by_course"]
    result = await toolkit.build_linked_dashboard(widgets, title="Polestar graduates dashboard")
    envelope = result["a2ui_envelope"]
    sources = envelope["metadata"]["extensions"]["parrot_data_sources"]
    assert set(sources) == {widget["key"] for widget in widgets}
    assert all(envelope["dataModel"][key] == {"rows": []} for key in sources)
    assert all(source["snapshot_at"] is None for source in sources.values())
