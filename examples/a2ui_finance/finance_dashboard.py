"""A2UI finance example — budget-variance linked dashboard over ``troc.finance_projection`` query slugs.

The widgets bind to two QuerySource slugs seeded by ``seed_finance.py`` (``finance_projection_latest`` for the
latest snapshot day, ``finance_projection_snapshots`` for the whole history). The envelope is DEFINITION-ONLY: the
agent asks ``qs_build_linked_dashboard`` for ``snapshot=false`` (the toolkit default), ``ensure_definition_only``
enforces it on whatever the LLM returned, and the browser lane fetches every source itself.
"""

from __future__ import annotations

import json
from typing import Any

from parrot.bots import Agent
from parrot.models.responses import AIMessage
from parrot_tools.querysource.toolkit import QuerysourceToolkit

SNAPSHOTS_SLUG = "finance_projection_snapshots"
LATEST_SLUG = "finance_projection_latest"
PROGRAM = "troc"
DEFAULT_LLM = "google:gemini-3.5-flash"
TITLE = "Finance projection dashboard"
GRID_KEY = "latest_rows"

#: The seeded slugs expose exactly these columns (money columns are cast to float8 inside the slug SQL).
COLUMNS = ["snapshot_date", "division", "project", "rev_actual", "rev_budget", "ebitda_actual", "ebitda_budget"]

WIDGETS: list[dict[str, Any]] = [
    {
        "key": "kpi_rev_actual",
        "slug": LATEST_SLUG,
        "request": {"fields": ["sum(rev_actual) AS rev_actual"]},
        "component": {"component": "KPICard", "title": "Revenue actual (latest snapshot)", "value": "rev_actual"},
    },
    {
        "key": "kpi_rev_budget",
        "slug": LATEST_SLUG,
        "request": {"fields": ["sum(rev_budget) AS rev_budget"]},
        "component": {"component": "KPICard", "title": "Revenue budget (latest snapshot)", "value": "rev_budget"},
    },
    {
        "key": "kpi_rev_variance",
        "slug": LATEST_SLUG,
        "request": {"fields": ["sum(rev_actual) - sum(rev_budget) AS rev_variance"]},
        "component": {"component": "KPICard", "title": "Revenue variance vs budget", "value": "rev_variance"},
    },
    {
        "key": "kpi_ebitda_variance",
        "slug": LATEST_SLUG,
        "request": {"fields": ["sum(ebitda_actual) - sum(ebitda_budget) AS ebitda_variance"]},
        "component": {"component": "KPICard", "title": "EBITDA variance vs budget", "value": "ebitda_variance"},
    },
    {
        "key": "by_division",
        "slug": LATEST_SLUG,
        "request": {
            "fields": ["division", "sum(rev_actual) AS rev_actual", "sum(rev_budget) AS rev_budget"],
            "grouping": ["division"],
            "ordering": ["division"],
        },
        "component": {
            "component": "Chart",
            "type": "bar",
            "x": "division",
            "y": ["rev_actual", "rev_budget"],
            "title": "Revenue by division: actual vs budget (latest snapshot)",
        },
    },
    {
        "key": "by_project",
        "slug": LATEST_SLUG,
        "request": {
            "fields": ["project", "sum(rev_actual) AS rev_actual"],
            "grouping": ["project"],
            "ordering": ["project"],
        },
        "component": {
            "component": "Chart",
            "type": "pie",
            "x": "project",
            "y": ["rev_actual"],
            "title": "Revenue share by project (latest snapshot)",
        },
    },
    {
        "key": "trend",
        "slug": SNAPSHOTS_SLUG,
        "request": {
            "fields": ["snapshot_date", "sum(rev_actual) AS rev_actual", "sum(rev_budget) AS rev_budget"],
            "grouping": ["snapshot_date"],
            "ordering": ["snapshot_date"],
        },
        "component": {
            "component": "Chart",
            "type": "line",
            "x": "snapshot_date",
            "y": ["rev_actual", "rev_budget"],
            "title": "Revenue trend across snapshots: actual vs budget",
        },
    },
    {
        "key": GRID_KEY,
        "slug": LATEST_SLUG,
        "request": {"fields": list(COLUMNS), "ordering": ["division", "project"], "limit": 500},
        "component": {
            "component": "DataTable",
            "title": "Latest snapshot rows",
            "columns": [{"name": column} for column in COLUMNS],
        },
    },
]


def agent_prompt() -> str:
    """The system prompt: one tool call, the widgets verbatim, and a definition-only (``snapshot=false``) build."""
    return (
        "You build dashboards. Call qs_build_linked_dashboard exactly once with the following widgets, unchanged, "
        f"title '{TITLE}' and snapshot=false (the surface must carry no rows; the browser fetches them). "
        "Then reply with one short sentence.\n" + json.dumps(WIDGETS)
    )


def build_dashboard_agent(llm: str | None = None) -> Agent:
    """Build the deterministic finance dashboard agent (tenant-restricted to the ``troc`` program)."""
    toolkit = QuerysourceToolkit(programs=[PROGRAM])
    return Agent(
        name="finance-dashboard",
        llm=llm or DEFAULT_LLM,
        tools=toolkit.get_tools(),
        system_prompt=agent_prompt(),
    )


def dashboard_question() -> str:
    """Return the user turn that hands ``WIDGETS`` to the agent verbatim."""
    return f"Build the {TITLE} with these widgets (snapshot=false):\n" + json.dumps(WIDGETS)


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


def ensure_definition_only(envelope: dict[str, Any]) -> dict[str, Any]:
    """Strip any baked snapshot so the served envelope is definition-only, whatever the LLM passed as ``snapshot``.

    Every source's ``dataModel`` entry becomes ``{"rows": []}`` and its descriptor loses ``snapshot_at`` /
    ``snapshot_truncated``; the browser lane then fetches each source exactly once on mount.
    """
    sources = envelope.get("metadata", {}).get("extensions", {}).get("parrot_data_sources", {})
    data_model = envelope.setdefault("dataModel", {})
    for key, source in sources.items():
        data_model[key] = {"rows": []}
        if isinstance(source, dict):
            source["snapshot_at"] = None
            source["snapshot_truncated"] = False
    return envelope
