"""FEAT-610 — Polestar graduates linked dashboard widget specs and agent."""

from __future__ import annotations

import json
from typing import Any

from parrot.bots import Agent
from parrot.models.responses import AIMessage
from parrot_tools.querysource.toolkit import QuerysourceToolkit

SLUG = "polestar_graduates_directory"
BY_COURSE_SLUG = "polestar_graduates_by_course"
DEFAULT_LLM = "anthropic:claude-sonnet-5"

WIDGETS: list[dict[str, Any]] = [
    {
        "key": "kpi_total",
        "slug": SLUG,
        "request": {"fields": ["count(*) as total"]},
        "component": {"component": "KPICard", "title": "Graduates (people)", "value": "total"},
    },
    {
        "key": "kpi_studio",
        "slug": SLUG,
        "request": {
            "fields": ["count(*) as total"],
            "filter": {"graduation_details": {"@>": [{"course": "Pilates Studio"}]}},
        },
        "component": {"component": "KPICard", "title": "Pilates Studio graduates (people)", "value": "total"},
    },
    {
        "key": "kpi_mat",
        "slug": SLUG,
        "request": {
            "fields": ["count(*) as total"],
            "filter": {"graduation_details": {"@>": [{"course": "Pilates Mat"}]}},
        },
        "component": {"component": "KPICard", "title": "Pilates Mat graduates (people)", "value": "total"},
    },
    {
        "key": "kpi_multi",
        "slug": SLUG,
        "request": {
            "fields": ["count(*) FILTER (WHERE jsonb_array_length(graduation_details) > 1) AS multi_graduates"]
        },
        "component": {"component": "KPICard", "title": "Multi-graduates (people)", "value": "multi_graduates"},
    },
    {
        "key": "by_country",
        "slug": SLUG,
        "request": {"fields": ["country", "count(*) as graduates"], "grouping": ["country"]},
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
        "slug": SLUG,
        "request": {"fields": ["licensee", "count(*) as graduates"], "grouping": ["licensee"]},
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
        "You build dashboards. Call qs_build_linked_dashboard exactly once with the following widgets, unchanged, "
        "and title 'Polestar graduates dashboard'. Then reply with one short sentence.\n" + json.dumps(WIDGETS)
    )
    return Agent(
        name="polestar-dashboard",
        llm=llm or DEFAULT_LLM,
        tools=toolkit.get_tools(),
        system_prompt=prompt,
    )


def dashboard_question() -> str:
    """Return the user turn that hands ``WIDGETS`` to the agent verbatim."""
    return "Build the Polestar graduates dashboard with these widgets:\n" + json.dumps(WIDGETS)


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
