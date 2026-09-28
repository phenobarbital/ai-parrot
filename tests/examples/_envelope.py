"""Shared test helper: the linked-dashboard envelope built with the production builders (no DB round-trip)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "examples" / "a2ui"))
import dashboard  # noqa: E402

from parrot.outputs.a2ui.builders import build_linked_surface  # noqa: E402
from parrot.outputs.a2ui.linked.conditions import derive_conditions  # noqa: E402
from parrot.outputs.a2ui.linked.models import LinkedDataSource, SourceRequest  # noqa: E402
from parrot_tools.querysource.models import DashboardWidget  # noqa: E402
from parrot_tools.querysource.toolkit import QuerysourceToolkit  # noqa: E402


def real_envelope(title_override: str | None = None) -> dict:
    """Build the dashboard envelope exactly as ``qs_build_linked_dashboard`` does, minus the DB round-trip."""
    widgets = [DashboardWidget.model_validate(w) for w in dashboard.WIDGETS]
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
        frames[widget.key] = pd.DataFrame(
            [
                {
                    "total": 0,
                    "multi_graduates": 0,
                    "country": "x",
                    "graduates": 1,
                    "licensee": "l",
                    "course": "c",
                    "student_uid": 1,
                    "full_name": "n",
                    "is_requalified": False,
                    "last_diploma_date": "2026-01-01",
                }
            ]
        )
    components = [{**QuerysourceToolkit._bind_component(w.component, w.key), "id": w.key} for w in widgets]
    if title_override:
        components[0]["title"] = title_override
    layout = QuerysourceToolkit._dashboard_layout(components, widgets, "Polestar graduates dashboard")
    envelope = build_linked_surface(layout, sources, frames, surface_id="linked-dashboard", snapshot=True)
    return envelope.model_dump(mode="json", by_alias=True, exclude_none=True)


