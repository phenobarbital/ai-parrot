"""A2UI finance example — opt-in production verification (PARROT_TEST_QS_LIVE=1 ENV=prod, seeded slugs)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples" / "a2ui_finance"))
import finance_client  # noqa: E402
import finance_dashboard  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.getenv("PARROT_TEST_QS_LIVE") != "1" or os.getenv("ENV") != "prod",
    reason="requires PARROT_TEST_QS_LIVE=1 and ENV=prod",
)


@pytest.mark.asyncio
async def test_finance_dashboard_live_is_definition_only() -> None:
    """The default toolkit build probes both slugs and ships no rows; every widget's axes validate."""
    from parrot_tools.querysource.toolkit import QuerysourceToolkit

    toolkit = QuerysourceToolkit(programs=[finance_dashboard.PROGRAM])
    result = await toolkit.build_linked_dashboard(finance_dashboard.WIDGETS, title=finance_dashboard.TITLE)
    envelope = result["a2ui_envelope"]
    sources = envelope["metadata"]["extensions"]["parrot_data_sources"]
    assert set(sources) == {widget["key"] for widget in finance_dashboard.WIDGETS}
    assert all(envelope["dataModel"][key] == {"rows": []} for key in sources)
    assert all(source["snapshot_at"] is None for source in sources.values())


@pytest.mark.asyncio
async def test_finance_expectations_live_through_dataset_manager() -> None:
    """DatasetManager.add_query + materialize run the seeded slugs and yield the widgets' expected values."""
    expected = await finance_client.expected_values()
    assert expected["grid_total"] > 0
    assert set(expected["kpis"]) == set(finance_client.KPI_KEYS)
    assert expected["groups"]["by_division"] and expected["groups"]["trend"]
