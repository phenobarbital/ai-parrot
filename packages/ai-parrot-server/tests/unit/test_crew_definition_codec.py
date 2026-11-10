"""Regression tests for the shared stored-crew definition codec."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from parrot.handlers.crew.definition_codec import (
    crew_definition_from_dict,
    crew_definition_to_document,
    strip_unknown_keys,
)
from parrot.handlers.crew.models import AgentDefinition, CrewDefinition, FlowRelation, ToolNodeDefinition


def test_nested_unknown_fields_and_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Drop root and nested historical fields while preserving a drift warning."""
    document = {
        "crew_id": "crew-1",
        "name": "legacy-crew",
        "agents": [{"agent_id": "research", "role": "lead"}],
        "tool_nodes": [{"node_id": "publish", "tool": "rest_api", "retries": 3}],
        "flow_relations": [{"source": "research", "target": "publish", "weight": 1}],
        "tasks": [],
    }

    with caplog.at_level(logging.WARNING):
        cleaned = strip_unknown_keys(document, "crew-1", logging.getLogger(__name__))

    assert "tasks" not in cleaned
    assert cleaned["agents"] == [{"agent_id": "research"}]
    assert cleaned["tool_nodes"] == [{"node_id": "publish", "tool": "rest_api"}]
    assert cleaned["flow_relations"] == [{"source": "research", "target": "publish"}]
    assert "agents[0].role" in caplog.text
    assert "tool_nodes[0].retries" in caplog.text
    assert "flow_relations[0].weight" in caplog.text
    assert "tasks" in caplog.text

    with pytest.raises(ValueError, match="unknown crew members"):
        crew_definition_from_dict(
            {
                "name": "invalid",
                "agents": [{"agent_id": "research"}],
                "flow_relations": [{"source": "ghost", "target": "research"}],
            },
            logging.getLogger(__name__),
        )


def test_iso_timestamps_and_round_trip() -> None:
    """Parse ISO timestamps and round-trip a complete crew document exactly."""
    created_at = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    crew = CrewDefinition(
        crew_id="crew-2",
        name="complete-crew",
        agents=[AgentDefinition(agent_id="research", name="Research")],
        tool_nodes=[ToolNodeDefinition(node_id="publish", tool="rest_api")],
        flow_relations=[FlowRelation(source="Research", target="publish")],
        created_at=created_at,
        updated_at=created_at,
    )

    document = crew_definition_to_document(crew)
    iso_document = {
        **document,
        "created_at": created_at.isoformat(),
        "updated_at": created_at.isoformat(),
    }
    restored = crew_definition_from_dict(iso_document, logging.getLogger(__name__))

    assert restored.created_at == created_at
    assert restored.updated_at == created_at
    assert crew_definition_to_document(restored) == document
