"""Shared test helper: the finance linked-dashboard envelope built with the production builders (no DB round-trip)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "examples" / "a2ui_finance"))
import finance_dashboard  # noqa: E402

from parrot.outputs.a2ui.builders import build_linked_surface  # noqa: E402
from parrot.outputs.a2ui.linked.conditions import derive_conditions  # noqa: E402
from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest  # noqa: E402
from parrot_tools.querysource.models import DashboardWidget  # noqa: E402
from parrot_tools.querysource.toolkit import QuerysourceToolkit  # noqa: E402

#: One row carrying every column any finance widget binds (money columns float64, as the seeded slugs return them).
PROBE_ROW = {
    "snapshot_date": "2026-09-01",
    "division": "North",
    "project": "Alpha",
    "rev_actual": 100.0,
    "rev_budget": 90.0,
    "ebitda_actual": 20.0,
    "ebitda_budget": 25.0,
    "rev_variance": 10.0,
    "ebitda_variance": -5.0,
}


def real_finance_envelope(*, snapshot: bool = False) -> dict:
    """Build the finance envelope exactly as ``qs_build_linked_dashboard`` does, minus the DB round-trip.

    Definition-only by default (``snapshot=False``), matching the toolkit default the example relies on.
    """
    widgets = [DashboardWidget.model_validate(w) for w in finance_dashboard.WIDGETS]
    sources: dict[str, LinkedDataSource] = {}
    frames: dict[str, pd.DataFrame] = {}
    for widget in widgets:
        request = SourceRequest.model_validate(widget.request or {})
        sources[widget.key] = LinkedDataSource(
            slug=widget.slug,
            tenant=widget.tenant,
            is_multiquery=False,
            conditions=derive_conditions(request, locked={}),
            request=request,
            params={},
            locked=[],
            target=f"/{widget.key}/rows",
        )
        frames[widget.key] = pd.DataFrame([PROBE_ROW])
    components = [{**QuerysourceToolkit._bind_component(w.component, w.key), "id": w.key} for w in widgets]
    layout = QuerysourceToolkit._dashboard_layout(components, widgets, finance_dashboard.TITLE)
    envelope = build_linked_surface(layout, sources, frames, surface_id="linked-finance-dashboard", snapshot=snapshot)
    return envelope.model_dump(mode="json", by_alias=True, exclude_none=True)
