"""S2 example TOOL: Epson activity dashboard over linked sources (FEAT-611 spec §3 M8).

Example-scoped (spec §9 S10): composes descriptors, pre-authorizes them, executes, builds. No core API.
Browser lane: the date FilterBar re-queries only `activity` (a FilterBar param names one source).
Server lane: POST /refresh {params:{firstdate,lastdate}} broadcasts to every activity-backed source.
KPI "stores visited" = distinct stores per program, summed (the DSL has no distinct count), so a store
active in two programs counts twice.
"""

from __future__ import annotations

import logging
from typing import Any

from parrot.auth.exceptions import AuthorizationRequired
from parrot.outputs.a2ui.builders import build_linked_surface
from parrot.outputs.a2ui.linked.conditions import derive_conditions
from parrot.outputs.a2ui.linked.executor import execute_sources
from parrot.outputs.a2ui.linked.models import LinkedDataSource, ParamSpec, SourceRequest, TransformSpec
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

logger = logging.getLogger("examples.a2ui.linked_e2e.dashboard_tool")

SURFACE_ID = "linked-epson-dashboard"
ACTIVITY_SLUG = "epson_field_activity"
TARGETS_SLUG = "epson_program_targets"
#: ISO start of the parity fixture's date range — offered as an explicit "From" option.
RANGE_START = "2026-09-01"
_JOIN_TARGETS = {"op": "join", "with": "targets", "how": "left", "on": [{"left": "program", "right": "program"}]}
_PCT = {"operator": "/", "left": {"operator": "*", "left": "visits", "right": 100}, "right": "target"}

ATTAINMENT_OPS: list[dict[str, Any]] = [
    _JOIN_TARGETS,
    {"op": "group_by", "by": ["program"], "aggregate": {"visits": "sum", "target": "max"}},
    {"op": "derive", "name": "attainment", "expr": _PCT},
    {"op": "sort", "by": [{"column": "attainment", "direction": "desc"}]},
]
KPI_OPS: list[dict[str, Any]] = [
    {"op": "group_by", "by": ["program", "store_id"], "aggregate": {"visits": "sum"}},
    _JOIN_TARGETS,
    {"op": "group_by", "by": ["program"], "aggregate": {"visits": "sum", "store_id": "count", "target": "max"}},
    {"op": "derive", "name": "k", "expr": 1},
    {"op": "group_by", "by": ["k"], "aggregate": {"visits": "sum", "store_id": "sum", "target": "sum"}},
    {"op": "derive", "name": "attainment_pct", "expr": _PCT},
]


def _date_params() -> dict[str, ParamSpec]:
    """Return the editable firstdate/lastdate params shared by every activity-backed source."""
    return {
        "firstdate": ParamSpec(type="date", accepts_keywords=True),
        "lastdate": ParamSpec(type="date", accepts_keywords=True),
    }


def build_sources(firstdate: str, lastdate: str) -> dict[str, LinkedDataSource]:
    """Return the four descriptors in dependency-friendly insertion order (targets first).

    Args:
        firstdate: Initial ``firstdate`` placeholder (ISO date or QuerySource keyword such as ``FDOM``).
        lastdate: Initial ``lastdate`` placeholder (ISO date or keyword such as ``TODAY``).

    Returns:
        ``{targets, activity, attainment, kpis}`` linked-source descriptors.
    """
    dated = SourceRequest(placeholders={"firstdate": firstdate, "lastdate": lastdate})
    plain = SourceRequest()

    def _src(
        key: str, slug: str, request: SourceRequest, ops: list[dict[str, Any]] | None, params: dict[str, ParamSpec]
    ) -> LinkedDataSource:
        return LinkedDataSource(
            slug=slug,
            conditions=derive_conditions(request, locked={}),  # must equal catalog re-derivation (:599-607)
            request=request,
            params=params,
            transform=TransformSpec.model_validate({"ops": ops}) if ops else None,
            target=f"/{key}/rows",
        )

    return {
        "targets": _src("targets", TARGETS_SLUG, plain, None, {}),
        "activity": _src("activity", ACTIVITY_SLUG, dated, None, _date_params()),
        "attainment": _src("attainment", ACTIVITY_SLUG, dated, ATTAINMENT_OPS, _date_params()),
        "kpis": _src("kpis", ACTIVITY_SLUG, dated, KPI_OPS, _date_params()),
    }


def _options(*values: str) -> list[dict[str, str]]:
    """Return FilterBar ``options[]`` with label == value."""
    return [{"label": value, "value": value} for value in values]


def build_components(programs: list[str]) -> list[dict[str, Any]]:
    """Return the S2 component list (ids are stable: the golden compares them).

    Args:
        programs: Option values of the local (row-filtering) program FilterBar.

    Returns:
        A2UI component dicts rooted at ``root``.
    """

    def kpi(cid: str, label: str, col: str) -> dict[str, Any]:
        return {"id": cid, "component": "KPICard", "label": label, "value": {"path": f"/kpis/rows/0/{col}"}}

    return [
        {
            "id": "root",
            "component": "Column",
            "children": ["kpi_row", "date_filters", "program_filter", "chart", "table"],
        },
        {"id": "kpi_row", "component": "Row", "children": ["kpi_visits", "kpi_stores", "kpi_attainment"]},
        kpi("kpi_visits", "Total visits", "visits"),
        kpi("kpi_stores", "Stores visited", "store_id"),
        kpi("kpi_attainment", "% attainment", "attainment_pct"),
        {
            "id": "date_filters",
            "component": "FilterBar",
            "title": "Date range",
            "filters": [
                {
                    "column": "day",
                    "label": "From",
                    "options": _options("FDOM", "YESTERDAY", RANGE_START),
                    "param": {"source": "activity", "name": "firstdate"},
                },
                {
                    "column": "day",
                    "label": "To",
                    "options": _options("TODAY", "YESTERDAY"),
                    "param": {"source": "activity", "name": "lastdate"},
                },
            ],
        },
        {
            "id": "program_filter",
            "component": "FilterBar",
            "title": "Program",
            "filters": [
                {"column": "program", "label": "Program", "multiple": True, "options": _options(*programs)},
            ],
        },
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
            "data": {"path": "/attainment/rows"},
            "columns": [{"name": c} for c in ("program", "visits", "target", "attainment")],
        },
    ]


async def build_epson_activity_dashboard(
    firstdate: str = "FDOM",
    lastdate: str = "TODAY",
    programs: list[str] | None = None,
    snapshot: bool = True,
    *,
    pctx: Any = None,
    guard: Any = None,
) -> dict[str, Any]:
    """Compose the S2 linked dashboard; returns {"a2ui_envelope": <inner CreateSurface>, "artifacts": [...]}.

    Args:
        firstdate: Initial ``firstdate`` (ISO date or keyword, default ``FDOM``).
        lastdate: Initial ``lastdate`` (ISO date or keyword, default ``TODAY``).
        programs: Program FilterBar options; ``None`` derives them from the targets frame.
        snapshot: Embed the fetched rows in the envelope's data model.
        pctx: Caller PermissionContext (injected, never LLM-visible).
        guard: Data-plane guard; ``None`` runs unguarded (offline/golden use only).

    Returns:
        The toolkit-shaped dict (toolkit.py:400-413).

    Raises:
        AuthorizationRequired: guard given without pctx, or the guard denies any (tenant, slug) — before any fetch.
        RuntimeError: any source failed during execution (its stable error code is in the message).
    """
    sources = build_sources(firstdate, lastdate)
    if guard is not None:
        if pctx is None:
            raise AuthorizationRequired(
                tool_name="build_epson_activity_dashboard",
                message="a caller PermissionContext is required when a guard is configured",
            )
        seen: set[tuple[str | None, str]] = set()
        for key, src in sources.items():
            pair = (src.tenant, src.slug)
            if pair in seen:
                continue
            seen.add(pair)
            source_id = f"{src.tenant or 'public'}:{src.slug}"
            try:
                await guard.authorize_source(pctx, PhysicalResources(source_type="query_slug", source_id=source_id))
            except AuthorizationRequired:
                logger.warning("epson dashboard source %r (slug=%s, tenant=%s) denied", key, src.slug, src.tenant)
                raise
    else:
        logger.warning("build_epson_activity_dashboard: no data-plane guard — unguarded (offline/golden use only)")
    outcome = await execute_sources(sources, pctx=pctx, guard=guard)
    failed = {k: o.error for k, o in outcome.outcomes.items() if o.error is not None}
    if failed:
        raise RuntimeError(f"epson dashboard sources failed: {failed}")
    if programs is None:
        programs = sorted(str(p) for p in outcome.frames["targets"]["program"].dropna().unique())
    envelope = build_linked_surface(
        build_components(programs), sources, outcome.frames, surface_id=SURFACE_ID, snapshot=snapshot
    )
    logger.info("built %s with sources=%s snapshot=%s", SURFACE_ID, list(sources), snapshot)
    return {
        "a2ui_envelope": envelope.model_dump(mode="json", by_alias=True, exclude_none=True),
        "artifacts": [
            {
                "type": "a2ui_linked_surface",
                "surface_id": envelope.surface_id,
                "sources": list(sources),
                "slug": ACTIVITY_SLUG,
                "tenant": None,
            }
        ],
    }
