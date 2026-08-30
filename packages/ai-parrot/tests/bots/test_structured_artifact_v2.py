"""Tests for FEAT-473 TASK-2565 — agents' artifact v2 call-site wiring.

PandasAgent/DatabaseAgent cannot be exercised end-to-end without a live LLM
client (see ``test_pandasagent_artifact_envelope.py``'s own docstring). These
tests instead verify (a) each agent module is wired to the REAL
``attach_structured_artifact`` helper (import-level check) and (b) the
helper mints the expected v2 entry for the exact response shape each agent
produces once its renderer has run (TASK-2563 dual-emit).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from parrot.models.outputs import (
    OutputMode,
    StructuredChartConfig,
    StructuredTableConfig,
)
from parrot.outputs.a2ui.adapters.structured import chart_to_surface, table_to_surface
from parrot.outputs.a2ui.artifacts import attach_structured_artifact
from parrot.outputs.a2ui.serialization import serialize


def test_bots_data_wired_to_attach_structured_artifact():
    import parrot.bots.data as data_mod

    assert data_mod.attach_structured_artifact is attach_structured_artifact


def test_database_agent_wired_to_attach_structured_artifact():
    import parrot.bots.database.agent as db_agent_mod

    assert db_agent_mod.attach_structured_artifact is attach_structured_artifact


async def test_pandasagent_artifact_v2():
    """PandasAgent STRUCTURED_CHART: artifacts[0] carries schemaVersion=2/surfaceId."""
    cfg = StructuredChartConfig(type="bar", x="month", y=["sales"], data=[])
    rows = [{"month": "Jan", "sales": 100}, {"month": "Feb", "sales": 120}]
    surface = chart_to_surface(cfg, rows, surface_id="structured_chart-abc12345")

    response = SimpleNamespace(
        output={"type": "bar", "x": "month", "y": ["sales"]},
        artifacts=[],
        artifact_id=None,
        a2ui_envelope=serialize(surface),
    )

    art_id = attach_structured_artifact(response, OutputMode.STRUCTURED_CHART)

    assert art_id == response.artifact_id
    entry = response.artifacts[0]
    assert entry["schemaVersion"] == 2
    assert entry["surfaceId"] == art_id
    assert entry["artifactId"] == art_id
    assert entry["type"] == "chart"


async def test_dbagent_structured_table_mints_artifact():
    """DatabaseAgent STRUCTURED_TABLE mints exactly one artifact entry.

    Mirrors the existing ``test_db_agent_structured_table_via_renderer``
    pattern (renderer run as an explicit step) — DatabaseAgent.ask() sets
    output_mode but does not itself render; the formatter/renderer pass
    (elsewhere) populates response.output/response.a2ui_envelope before
    attach_structured_artifact can mint anything (see TASK-2565 Completion
    Note for the exact-timing caveat at the agent.py call site).
    """
    cfg = StructuredTableConfig(columns=[{"name": "order_id", "type": "integer", "title": "Order ID"}])
    rows = [{"order_id": 1}, {"order_id": 2}]
    surface = table_to_surface(cfg, rows, surface_id="structured_table-deadbeef")

    response = SimpleNamespace(
        output={"columns": [{"name": "order_id", "type": "integer", "title": "Order ID"}]},
        artifacts=[],
        artifact_id=None,
        a2ui_envelope=serialize(surface),
    )

    art_id = attach_structured_artifact(response, OutputMode.STRUCTURED_TABLE)

    assert len(response.artifacts) == 1
    assert response.artifacts[0]["type"] == "table"
    assert art_id == response.artifact_id


async def test_attach_structured_artifact_noop_before_render():
    """The exact agent.py call-site timing: response.output isn't a dict yet.

    DatabaseAgent's STRUCTURED_TABLE branch calls the helper immediately
    after setting output_mode — BEFORE the formatter's renderer pass has
    turned response.output into a config dict. The helper's own guard makes
    this a safe no-op (never raises, never mutates response) rather than a
    premature/incorrect mint.
    """
    from parrot.bots.database.models import QueryResponse

    response = SimpleNamespace(
        output=QueryResponse(query="SELECT 1", explanation="x"),
        artifacts=[],
        artifact_id=None,
        a2ui_envelope=None,
    )

    art_id = attach_structured_artifact(response, OutputMode.STRUCTURED_TABLE)

    assert art_id is None
    assert response.artifacts == []
    assert response.artifact_id is None


@pytest.mark.parametrize("mode", [OutputMode.DEFAULT, OutputMode.MARKDOWN, OutputMode.HTML])
async def test_non_structured_modes_never_mint(mode):
    response = SimpleNamespace(output={"anything": True}, artifacts=[], artifact_id=None, a2ui_envelope=None)
    assert attach_structured_artifact(response, mode) is None
    assert response.artifacts == []
