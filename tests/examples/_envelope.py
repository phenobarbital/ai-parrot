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
from parrot.outputs.a2ui.linked.dsl import apply_transform  # noqa: E402
from parrot.outputs.a2ui.linked.models import (  # noqa: E402
    DerivedDataSource,
    LinkedDataSource,
    LinkedSource,
    SourceRequest,
    TransformSpec,
)
from parrot_tools.querysource.models import DashboardSource, DashboardWidget  # noqa: E402
from parrot_tools.querysource.toolkit import QuerysourceToolkit  # noqa: E402

#: One representative row per query-slug source, shaped like the columns each request returns.
SAMPLE_ROWS: dict[str, list[dict]] = {
    "kpis": [{"total": 0, "studio": 0, "mat": 0, "multi_graduates": 0}],
    "geo": [{"country": "x", "licensee": "l", "graduates": 1}, {"country": "y", "licensee": "l", "graduates": 2}],
    "by_course": [{"course": "c", "graduates": 1}],
    "graduates": [
        {
            "student_uid": 1,
            "full_name": "n",
            "country": "x",
            "licensee": "l",
            "is_requalified": False,
            "last_diploma_date": "2026-01-01",
        }
    ],
}


def _query_source(key: str, spec: DashboardSource | DashboardWidget) -> LinkedDataSource:
    request = SourceRequest.model_validate(spec.request or {})
    return LinkedDataSource(
        slug=spec.slug,
        tenant=spec.tenant,
        is_multiquery=False,
        conditions=derive_conditions(request, locked={}),
        request=request,
        params={},
        locked=[],
        target=f"/{key}/rows",
    )


def real_envelope(title_override: str | None = None) -> dict:
    """Build the dashboard envelope exactly as ``qs_build_linked_dashboard`` does, minus the DB round-trip."""
    shared = {key: DashboardSource.model_validate(spec) for key, spec in dashboard.SOURCES.items()}
    widgets = [DashboardWidget.model_validate(w) for w in dashboard.WIDGETS]
    sources: dict[str, LinkedSource] = {key: _query_source(key, spec) for key, spec in shared.items()}
    frames: dict[str, pd.DataFrame] = {key: pd.DataFrame(SAMPLE_ROWS[key]) for key in shared}
    inline: dict[str, list[dict]] = {}
    for widget in widgets:
        if widget.origin == "slug":
            sources[widget.key] = _query_source(widget.key, widget)
            frames[widget.key] = pd.DataFrame(SAMPLE_ROWS[widget.key])
        elif widget.origin == "data":
            inline[widget.key] = list(widget.data or [])
        elif widget.transform is not None:
            spec = TransformSpec.model_validate(widget.transform)
            sources[widget.key] = DerivedDataSource.model_validate(
                {"kind": "derived", "from": widget.source, "transform": spec, "target": f"/{widget.key}/rows"}
            )
            frames[widget.key] = apply_transform(frames[widget.source], spec, frames=frames)
    components = []
    for widget in widgets:
        bind_key = widget.source if widget.origin == "source" and widget.transform is None else widget.key
        components.append({**QuerysourceToolkit._bind_component(widget.component, bind_key), "id": widget.key})
    if title_override:
        components[0]["title"] = title_override
    layout = QuerysourceToolkit._dashboard_layout(components, widgets, "Polestar graduates dashboard")
    envelope = build_linked_surface(
        layout, sources, frames, surface_id="linked-dashboard", snapshot=True, inline=inline
    )
    return envelope.model_dump(mode="json", by_alias=True, exclude_none=True)
