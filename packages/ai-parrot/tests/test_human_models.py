"""Tests for HITL core data models."""
import pytest

from parrot.human.models import (
    ChoiceOption,
    ConsensusMode,
    HumanInteraction,
    HumanResponse,
    InteractionResult,
    InteractionStatus,
    InteractionType,
    TimeoutAction,
)


class TestEnums:
    """Test enum definitions and values."""

    def test_interaction_type_values(self):
        assert InteractionType.FREE_TEXT == "free_text"
        assert InteractionType.SINGLE_CHOICE == "single_choice"
        assert InteractionType.MULTI_CHOICE == "multi_choice"
        assert InteractionType.APPROVAL == "approval"
        assert InteractionType.FORM == "form"
        assert InteractionType.POLL == "poll"

    def test_interaction_status_values(self):
        assert InteractionStatus.PENDING == "pending"
        assert InteractionStatus.DELIVERED == "delivered"
        assert InteractionStatus.PARTIAL == "partial"
        assert InteractionStatus.COMPLETED == "completed"
        assert InteractionStatus.TIMEOUT == "timeout"
        assert InteractionStatus.ESCALATED == "escalated"
        assert InteractionStatus.CANCELLED == "cancelled"

    def test_timeout_action_values(self):
        assert TimeoutAction.CANCEL == "cancel"
        assert TimeoutAction.DEFAULT == "default"
        assert TimeoutAction.ESCALATE == "escalate"
        assert TimeoutAction.RETRY == "retry"

    def test_consensus_mode_values(self):
        assert ConsensusMode.FIRST_RESPONSE == "first_response"
        assert ConsensusMode.ALL_REQUIRED == "all_required"
        assert ConsensusMode.MAJORITY == "majority"
        assert ConsensusMode.QUORUM == "quorum"


class TestChoiceOption:
    """Test ChoiceOption model."""

    def test_minimal_creation(self):
        opt = ChoiceOption(key="a", label="Option A")
        assert opt.key == "a"
        assert opt.label == "Option A"
        assert opt.description is None
        assert opt.metadata == {}

    def test_full_creation(self):
        opt = ChoiceOption(
            key="ticket_1",
            label="JIRA-123",
            description="Fix login bug",
            metadata={"priority": "high", "assignee": "alice"},
        )
        assert opt.metadata["priority"] == "high"

    def test_serialization(self):
        opt = ChoiceOption(key="x", label="X", metadata={"n": 42})
        data = opt.model_dump()
        restored = ChoiceOption.model_validate(data)
        assert restored.key == "x"
        assert restored.metadata["n"] == 42


class TestHumanInteraction:
    """Test HumanInteraction model."""

    def test_minimal_creation(self):
        hi = HumanInteraction(question="What is your name?")
        assert hi.question == "What is your name?"
        assert hi.interaction_type == InteractionType.FREE_TEXT
        assert hi.status == InteractionStatus.PENDING
        assert hi.timeout == 7200.0
        assert hi.interaction_id  # auto-generated UUID

    def test_full_creation(self):
        hi = HumanInteraction(
            question="Select a ticket to work on:",
            context="Sprint 42 backlog",
            interaction_type=InteractionType.SINGLE_CHOICE,
            options=[
                ChoiceOption(key="t1", label="JIRA-1"),
                ChoiceOption(key="t2", label="JIRA-2"),
            ],
            target_humans=["telegram:12345", "telegram:67890"],
            consensus_mode=ConsensusMode.FIRST_RESPONSE,
            timeout=3600.0,
            timeout_action=TimeoutAction.ESCALATE,
            escalation_targets=["telegram:99999"],
            source_agent="HRAgent",
            source_flow="onboarding_flow",
            source_node="ticket_selection",
        )
        assert len(hi.options) == 2
        assert hi.options[0].key == "t1"
        assert hi.timeout_action == TimeoutAction.ESCALATE
        assert len(hi.escalation_targets) == 1

    def test_json_round_trip(self):
        hi = HumanInteraction(
            question="Approve?",
            interaction_type=InteractionType.APPROVAL,
            default_response=True,
            target_humans=["user1"],
        )
        json_str = hi.model_dump_json()
        restored = HumanInteraction.model_validate_json(json_str)
        assert restored.question == "Approve?"
        assert restored.interaction_type == InteractionType.APPROVAL
        assert restored.default_response is True

    def test_auto_uuid(self):
        hi1 = HumanInteraction(question="q1")
        hi2 = HumanInteraction(question="q2")
        assert hi1.interaction_id != hi2.interaction_id


class TestHumanResponse:
    """Test HumanResponse model."""

    def test_free_text_response(self):
        resp = HumanResponse(
            interaction_id="abc123",
            respondent="user1",
            response_type=InteractionType.FREE_TEXT,
            value="The answer is 42",
        )
        assert resp.value == "The answer is 42"

    def test_approval_response(self):
        resp = HumanResponse(
            interaction_id="abc123",
            respondent="user1",
            response_type=InteractionType.APPROVAL,
            value=True,
        )
        assert resp.value is True

    def test_multi_choice_response(self):
        resp = HumanResponse(
            interaction_id="abc123",
            respondent="user1",
            response_type=InteractionType.MULTI_CHOICE,
            value=["t1", "t3"],
        )
        assert isinstance(resp.value, list)
        assert len(resp.value) == 2

    def test_serialization(self):
        resp = HumanResponse(
            interaction_id="id1",
            respondent="u1",
            response_type=InteractionType.SINGLE_CHOICE,
            value="opt_a",
            metadata={"device": "mobile"},
        )
        data = resp.model_dump()
        restored = HumanResponse.model_validate(data)
        assert restored.value == "opt_a"
        assert restored.metadata["device"] == "mobile"


class TestInteractionResult:
    """Test InteractionResult model."""

    def test_completed_result(self):
        result = InteractionResult(
            interaction_id="abc",
            status=InteractionStatus.COMPLETED,
            consolidated_value=True,
        )
        assert result.timed_out is False
        assert result.escalated is False
        assert result.consolidated_value is True

    def test_timeout_result(self):
        result = InteractionResult(
            interaction_id="abc",
            status=InteractionStatus.TIMEOUT,
            timed_out=True,
        )
        assert result.timed_out is True
        assert result.consolidated_value is None

    def test_with_multiple_responses(self):
        responses = [
            HumanResponse(
                interaction_id="abc",
                respondent="u1",
                response_type=InteractionType.APPROVAL,
                value=True,
            ),
            HumanResponse(
                interaction_id="abc",
                respondent="u2",
                response_type=InteractionType.APPROVAL,
                value=False,
            ),
        ]
        result = InteractionResult(
            interaction_id="abc",
            status=InteractionStatus.COMPLETED,
            responses=responses,
            consolidated_value={"conflict": True, "responses": [True, False]},
        )
        assert len(result.responses) == 2
        assert result.consolidated_value["conflict"] is True
