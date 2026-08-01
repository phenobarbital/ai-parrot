"""Tests for parrot.bots.flows.core.checkpoint.model (TASK-2046).

Validates FlowCheckpoint and its embedded models round-trip correctly,
including the embedded FlowDefinition graph snapshot.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from parrot.bots.flows.core.checkpoint import (
    CheckpointNotFoundError,
    ContextSnapshot,
    FlowCheckpoint,
    FlowLockedError,
    FlowNotExportableError,
    MemoryRefs,
    NodeStateSnapshot,
)
from parrot.bots.flows.flow.definition import EdgeDefinition, FlowDefinition, NodeDefinition


@pytest.fixture
def linear_flow_definition() -> FlowDefinition:
    """3-node declarative FlowDefinition (start -> agent -> end)."""
    return FlowDefinition(
        flow="demo-flow",
        nodes=[
            NodeDefinition(id="start", type="start"),
            NodeDefinition(id="worker", type="agent", agent_ref="demo_agent"),
            NodeDefinition(id="end", type="end"),
        ],
        edges=[
            EdgeDefinition(**{"from": "start", "to": "worker", "condition": "always"}),
            EdgeDefinition(**{"from": "worker", "to": "end", "condition": "on_success"}),
        ],
    )


@pytest.fixture
def context_snapshot() -> ContextSnapshot:
    return ContextSnapshot(
        initial_task="do the thing",
        results={"worker": {"answer": 42}},
        completed_tasks=["start", "worker"],
        completion_order=["start", "worker"],
        shared_data={"foo": "bar"},
        errors={},
    )


def test_flow_checkpoint_model_roundtrip(linear_flow_definition, context_snapshot):
    cp = FlowCheckpoint(
        flow_id="f1",
        flow_name="demo",
        checkpoint_id=1,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        status="running",
        definition=linear_flow_definition,
        context=context_snapshot,
        node_states=[
            NodeStateSnapshot(node_id="start", fsm_state="completed"),
            NodeStateSnapshot(node_id="worker", fsm_state="running"),
        ],
        memory_refs=MemoryRefs(session_id="sess-1", chatbot_id="bot-1", user_id="user-1"),
    )

    restored = FlowCheckpoint.model_validate(cp.model_dump())
    assert restored == cp
    assert restored.definition == linear_flow_definition


def test_status_literal_rejects_unknown(linear_flow_definition, context_snapshot):
    with pytest.raises(ValidationError):
        FlowCheckpoint(
            flow_id="f1",
            flow_name="demo",
            checkpoint_id=1,
            created_at=datetime.now(timezone.utc),
            status="paused",  # not a valid Literal value
            definition=linear_flow_definition,
            context=context_snapshot,
        )


def test_errors_are_structured_dicts():
    snapshot = ContextSnapshot(
        initial_task="task",
        errors={
            "worker": {
                "type": "ValueError",
                "message": "boom",
                "repr": "ValueError('boom')",
            }
        },
    )
    assert snapshot.errors["worker"]["type"] == "ValueError"
    assert isinstance(snapshot.errors["worker"]["message"], str)


def test_context_snapshot_defaults():
    snapshot = ContextSnapshot(initial_task="task")
    assert snapshot.results == {}
    assert snapshot.responses is None
    assert snapshot.completed_tasks == []
    assert snapshot.shared_data == {}
    assert snapshot.errors == {}


def test_memory_refs_all_optional():
    refs = MemoryRefs()
    assert refs.session_id is None
    assert refs.chatbot_id is None
    assert refs.user_id is None


def test_error_types_are_distinct_and_subclass_expected_bases():
    assert issubclass(FlowLockedError, RuntimeError)
    assert issubclass(CheckpointNotFoundError, LookupError)
    assert issubclass(FlowNotExportableError, ValueError)

    with pytest.raises(RuntimeError):
        raise FlowLockedError("locked")
    with pytest.raises(LookupError):
        raise CheckpointNotFoundError("missing")
    with pytest.raises(ValueError):
        raise FlowNotExportableError("not exportable")
