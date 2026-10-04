"""FEAT-610 TASK-3848 — opt-in production verification for the dashboard widgets."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from parrot_tools.querysource.errors import SlugNotFoundError
from parrot_tools.querysource.toolkit import QuerysourceToolkit

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "a2ui"))
import client  # noqa: E402
import dashboard  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.getenv("PARROT_TEST_QS_LIVE") != "1" or os.getenv("ENV") != "prod",
    reason="requires PARROT_TEST_QS_LIVE=1 and ENV=prod",
)


def _sources_and_widgets(*, with_by_course: bool) -> tuple[dict, list[dict]]:
    """The example's dashboard-owned sources and its widgets, minus the by-course pie when its slug is not seeded."""
    widgets = [widget for widget in dashboard.WIDGETS if with_by_course or widget["key"] != "by_course"]
    return dashboard.SOURCES, widgets


def _expected_source_keys(widgets: list[dict]) -> set[str]:
    """Descriptor keys: every dashboard source, plus each widget that owns a slug or derives a view."""
    owned = {widget["key"] for widget in widgets if "slug" in widget or "transform" in widget}
    return set(dashboard.SOURCES) | owned


@pytest.mark.asyncio
async def test_linked_dashboard_live() -> None:
    """The production query map reproduces the verified values and sources."""
    toolkit = QuerysourceToolkit(programs=["polestar"])
    try:
        await toolkit.describe_slug(dashboard.BY_COURSE_SLUG)
    except SlugNotFoundError:
        sources, widgets = _sources_and_widgets(with_by_course=False)
    else:
        sources, widgets = _sources_and_widgets(with_by_course=True)

    result = await toolkit.build_linked_dashboard(
        widgets,
        sources=sources,
        title="Polestar graduates dashboard",
        snapshot=True,  # this test asserts the embedded rows; the default build is definition-only
    )
    envelope = result["a2ui_envelope"]
    data_model = envelope["dataModel"]
    descriptors = envelope["metadata"]["extensions"]["parrot_data_sources"]

    # The four KPICards share ONE `kpis` row; the two bar charts are derived views of `geo`.
    kpis = data_model[client.KPI_SOURCE]["rows"][0]
    for key, (column, expected) in client.EXPECTED_KPIS.items():
        assert kpis[column] == expected, key
    for key, expected_groups in client.EXPECTED_GROUPS.items():
        assert len(data_model[key]["rows"]) == expected_groups, key
        assert descriptors[key]["kind"] == "derived" and descriptors[key]["from"] == "geo"
    assert len(data_model[client.GRID_KEY]["rows"]) == 500
    assert set(descriptors) == _expected_source_keys(widgets)

    if "by_course" in data_model:
        by_course = data_model["by_course"]["rows"]
        counts = {row["course"]: row["graduates"] for row in by_course}
        assert counts == client.EXPECTED_SLICES


@pytest.mark.asyncio
async def test_linked_dashboard_live_default_is_definition_only() -> None:
    """The default build probes every slug with one row and ships no rows in the envelope."""
    toolkit = QuerysourceToolkit(programs=["polestar"])
    sources, widgets = _sources_and_widgets(with_by_course=False)
    result = await toolkit.build_linked_dashboard(widgets, sources=sources, title="Polestar graduates dashboard")
    envelope = result["a2ui_envelope"]
    descriptors = envelope["metadata"]["extensions"]["parrot_data_sources"]
    assert set(descriptors) == _expected_source_keys(widgets)
    assert all(envelope["dataModel"][key] == {"rows": []} for key in descriptors)
    assert all(descriptor.get("snapshot_at") is None for descriptor in descriptors.values())
