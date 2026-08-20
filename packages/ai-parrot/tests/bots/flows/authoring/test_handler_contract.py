"""The HTTP contract, exercised without aiohttp or a live model.

The handler itself lives in ``ai-parrot-server`` and needs navigator +
navigator_auth to import, which the core test suite does not depend on.
What is asserted here is the part that must not drift regardless: the
request/result models the endpoint publishes and consumes, and the fact
that a result survives the JSON round-trip through a Redis-backed job
record.
"""
from __future__ import annotations

import json

import pytest

from parrot.bots.flows.authoring.contracts import (
    AuthoringProgress,
    AuthoringStage,
    AuthoringStatus,
    CapabilityGap,
    FlowAuthoringRequest,
    FlowAuthoringResult,
)


def test_request_schema_is_publishable():
    """The bare GET returns this schema, so it must build."""
    schema = FlowAuthoringRequest.model_json_schema()
    assert "description" in schema["properties"]
    assert schema["properties"]["engine"]["default"] == "auto"


def test_request_rejects_an_empty_description():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FlowAuthoringRequest(description="")


def test_request_rejects_unknown_fields():
    """Control keys are popped by the handler; anything else is a typo."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FlowAuthoringRequest(description="x", planner_llm="openai:gpt-4o")


def test_persist_defaults_to_off():
    """Authoring returns a definition; storing it is a separate decision."""
    assert FlowAuthoringRequest(description="x").persist is False


def test_max_nodes_is_bounded():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FlowAuthoringRequest(description="x", max_nodes=999)


def test_progress_is_json_serialisable():
    """It is written to Job.metadata, which is persisted to Redis."""
    progress = AuthoringProgress(
        stage=AuthoringStage.NODES, nodes_total=7, nodes_done=4, message="Authoring"
    )
    payload = json.loads(json.dumps(progress.model_dump(mode="json")))
    assert payload["stage"] == "nodes"
    assert payload["nodes_done"] == 4


def test_result_round_trips_through_json():
    result = FlowAuthoringResult(
        status=AuthoringStatus.DEGRADED,
        engine="crew",
        crew_definition={"name": "c", "agents": []},
        capability_gaps=[
            CapabilityGap(
                kind="tool",
                requested="wordpress_publish",
                reason="No such tool is registered on this platform.",
                suggestion="rest_api",
            )
        ],
        dropped_nodes=["seo_reviewer"],
    )
    payload = json.loads(json.dumps(result.model_dump(mode="json")))
    restored = FlowAuthoringResult.model_validate(payload)
    assert restored.status is AuthoringStatus.DEGRADED
    assert restored.capability_gaps[0].suggestion == "rest_api"
    assert restored.dropped_nodes == ["seo_reviewer"]


def test_result_schema_is_publishable():
    assert "status" in FlowAuthoringResult.model_json_schema()["properties"]


@pytest.mark.parametrize(
    "stage", [s.value for s in AuthoringStage]
)
def test_every_stage_is_a_plain_string(stage):
    """Stages go into job metadata and out over HTTP as strings."""
    assert isinstance(stage, str)
