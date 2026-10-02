"""FEAT-610 — Polestar graduates linked dashboard: dashboard-owned data sources shared by its widgets.

The dashboard (not each widget) owns the data sources. ``SOURCES`` are fetched once when the dashboard loads;
``WIDGETS`` declare where their data comes from:

* ``source: "kpis"`` — four KPICards read four aggregates computed by ONE query (one call instead of four);
* ``source: "geo"`` + ``transform`` — two charts are *derived views* of one grouped query: the country and licensee
  aggregations are computed client-side (and server-side for snapshots/refresh) with the transform DSL, no extra call;
* ``slug`` — the pie chart and the server-paged grid keep their own sources (the grid pages on the server, so its
  rows can never feed a derived view).

Load cost: 4 QuerySource calls (+ the grid's page/count) instead of the 8 per-widget calls of the first version.
"""

from __future__ import annotations

import json
from typing import Any

from parrot.bots import Agent
from parrot.models.responses import AIMessage
from parrot_tools.querysource.toolkit import QuerysourceToolkit

SLUG = "polestar_graduates_directory"
BY_COURSE_SLUG = "polestar_graduates_by_course"
DEFAULT_LLM = "google:gemini-3.5-flash"

SOURCES: dict[str, dict[str, Any]] = {
    # One query computes every KPI (people): total, per-course counts over the JSONB diplomas, multi-graduates.
    "kpis": {
        "slug": SLUG,
        "request": {
            "fields": [
                "count(*) as total",
                'count(*) FILTER (WHERE graduation_details @> \'[{"course": "Pilates Studio"}]\') as studio',
                'count(*) FILTER (WHERE graduation_details @> \'[{"course": "Pilates Mat"}]\') as mat',
                "count(*) FILTER (WHERE jsonb_array_length(graduation_details) > 1) AS multi_graduates",
            ]
        },
    },
    # One country × licensee matrix (a few thousand rows at most) feeds two derived charts.
    "geo": {
        "slug": SLUG,
        "request": {"fields": ["country", "licensee", "count(*) as graduates"], "grouping": ["country", "licensee"]},
    },
}

WIDGETS: list[dict[str, Any]] = [
    {
        "key": "kpi_total",
        "source": "kpis",
        "component": {"component": "KPICard", "title": "Graduates (people)", "value": "total"},
    },
    {
        "key": "kpi_studio",
        "source": "kpis",
        "component": {"component": "KPICard", "title": "Pilates Studio graduates (people)", "value": "studio"},
    },
    {
        "key": "kpi_mat",
        "source": "kpis",
        "component": {"component": "KPICard", "title": "Pilates Mat graduates (people)", "value": "mat"},
    },
    {
        "key": "kpi_multi",
        "source": "kpis",
        "component": {"component": "KPICard", "title": "Multi-graduates (people)", "value": "multi_graduates"},
    },
    {
        "key": "by_country",
        "source": "geo",
        "transform": {
            "ops": [
                {"op": "group_by", "by": ["country"], "aggregate": {"graduates": "sum"}},
                {"op": "sort", "by": [{"column": "graduates", "direction": "desc"}]},
            ]
        },
        "component": {
            "component": "Chart",
            "type": "bar",
            "x": "country",
            "y": ["graduates"],
            "title": "Graduates by country (people)",
        },
    },
    {
        "key": "by_licensee",
        "source": "geo",
        "transform": {
            "ops": [
                {"op": "group_by", "by": ["licensee"], "aggregate": {"graduates": "sum"}},
                {"op": "sort", "by": [{"column": "graduates", "direction": "desc"}]},
            ]
        },
        "component": {
            "component": "Chart",
            "type": "bar",
            "x": "licensee",
            "y": ["graduates"],
            "title": "Graduates by licensee (people)",
        },
    },
    {
        "key": "by_course",
        "slug": BY_COURSE_SLUG,
        "request": {"fields": ["course", "count(*) as graduates"], "grouping": ["course"]},
        "component": {
            "component": "Chart",
            "type": "pie",
            "x": "course",
            "y": ["graduates"],
            "title": "Graduates by course (diplomas)",
        },
    },
    {
        "key": "graduates",
        "slug": SLUG,
        "request": {
            "fields": ["student_uid", "full_name", "country", "licensee", "is_requalified", "last_diploma_date"],
            "ordering": ["student_uid"],
            "limit": 500,
        },
        "component": {
            "component": "DataTable",
            "title": "Graduates (people)",
            "columns": [
                {"name": "student_uid"},
                {"name": "full_name"},
                {"name": "country"},
                {"name": "licensee"},
                {"name": "is_requalified"},
                {"name": "last_diploma_date"},
            ],
        },
    },
]


def build_dashboard_agent(llm: str | None = None) -> Agent:
    """Build the deterministic Polestar dashboard agent."""
    toolkit = QuerysourceToolkit(programs=["polestar"])
    prompt = (
        "You build dashboards. Call qs_build_linked_dashboard exactly once with the following `sources` and "
        "`widgets`, unchanged, and title 'Polestar graduates dashboard'. Then reply with one short sentence.\n"
        f"sources: {json.dumps(SOURCES)}\nwidgets: {json.dumps(WIDGETS)}"
    )
    return Agent(
        name="polestar-dashboard",
        llm=llm or DEFAULT_LLM,
        tools=toolkit.get_tools(),
        system_prompt=prompt,
    )


def dashboard_question() -> str:
    """Return the user turn that hands ``SOURCES`` and ``WIDGETS`` to the agent verbatim."""
    return (
        "Build the Polestar graduates dashboard with these dashboard sources and widgets:\n"
        f"sources: {json.dumps(SOURCES)}\nwidgets: {json.dumps(WIDGETS)}"
    )


def extract_envelope(response: AIMessage) -> dict[str, Any]:
    """Return the linked-dashboard envelope from an agent tool result.

    Raises:
        RuntimeError: If the dashboard tool was not called or returned no linked data sources.
    """
    for call in response.tool_calls:
        if call.name != "qs_build_linked_dashboard" or not isinstance(call.result, dict):
            continue
        envelope = call.result.get("a2ui_envelope")
        if not isinstance(envelope, dict):
            continue
        metadata = envelope.get("metadata")
        extensions = metadata.get("extensions") if isinstance(metadata, dict) else None
        sources = extensions.get("parrot_data_sources") if isinstance(extensions, dict) else None
        if isinstance(sources, dict) and sources:
            return envelope
    raise RuntimeError("the agent did not call qs_build_linked_dashboard; no linked envelope to serve")
