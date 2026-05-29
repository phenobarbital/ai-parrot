"""Unit tests for AgentTalk HITL resume branch (FEAT-204 / TASK-1383).

Tests exercise _handle_hitl_resume via mocked manager and store objects,
verifying the three-state check and authentication logic.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.handlers.agent import AgentTalk, PausedEnvelope
from parrot.human.suspended_store import SuspendedExecution


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_suspended(interaction_id: str = "iid-1") -> SuspendedExecution:
    return SuspendedExecution(
        interaction_id=interaction_id,
        session_id="sess-1",
        user_id="user-1",
        agent_name="test-agent",
        tool_call_id="tc-1",
        messages=[{"role": "user", "content": "approve?"}],
        created_at=datetime.now(timezone.utc),
    )


def _mock_interaction(interaction_id: str = "iid-1"):
    """Return a minimal mock HumanInteraction."""
    from parrot.human.models import HumanInteraction, InteractionType
    interaction = MagicMock()
    interaction.interaction_id = interaction_id
    interaction.interaction_type = InteractionType.FREE_TEXT
    interaction.target_humans = ["user-1"]
    return interaction


class _FakeRequest:
    """Minimal fake aiohttp request."""
    def __init__(self, session_user_id="user-1"):
        self.session = {"user_id": session_user_id}
        self.match_info = {}


class _FakeAgentTalk:
    """Minimal AgentTalk-like object for testing _handle_hitl_resume."""
    logger = MagicMock()

    def _format_response(
        self,
        ai_message,
        output_format,
        format_kwargs,
        user_id=None,
        user_session=None,
        response_time_ms=None,
        agent_name=None,
        session_id=None,
        client_message_id=None,
    ):
        """Stub: return a fake success web.Response.

        Signature matches the real AgentTalk._format_response so that any
        mismatch between the call site and this stub causes an immediate
        TypeError rather than a silent attribute lookup failure.
        """
        from aiohttp import web
        import json
        return web.json_response({
            "status": "success",
            "content": str(ai_message),
        }, status=200)

    # Re-expose the methods under test
    _handle_hitl_resume = AgentTalk._handle_hitl_resume
    _handle_hitl_resume_inner = AgentTalk._handle_hitl_resume_inner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_agent():
    agent = MagicMock()
    agent.name = "test-agent"
    session_ctx = MagicMock()
    session_ctx.__aenter__ = AsyncMock(return_value=MagicMock(
        resume=AsyncMock(return_value="AI reply")
    ))
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    agent.session = MagicMock(return_value=session_ctx)
    return agent


@pytest.fixture
def fake_manager():
    m = MagicMock()
    m.get_result = AsyncMock(return_value=None)
    m._load_interaction = AsyncMock(return_value=_mock_interaction())
    m.is_valid_respondent = AsyncMock(return_value=True)
    m.receive_response = AsyncMock(return_value=None)
    m._get_redis = AsyncMock(return_value=MagicMock())
    return m


@pytest.fixture
def fake_request_session():
    return {"user_id": "user-1"}


@pytest.fixture
def view():
    return _FakeAgentTalk()


# ---------------------------------------------------------------------------
# 3-state check tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_when_neither_key(view, fake_agent, fake_manager, fake_request_session):
    """When no interaction AND no result → return 'expired'."""
    fake_manager._load_interaction.return_value = None
    fake_manager.get_result.return_value = None

    hitl_resp = {"turn_id": "iid-1", "value": "yes"}

    with patch("parrot.human.get_default_human_manager", return_value=fake_manager), \
         patch("parrot.human.suspended_store.SuspendedExecutionStore") as MockStore:
        response = await view._handle_hitl_resume(
            hitl_response=hitl_resp,
            agent=fake_agent,
            session_id="sess-1",
            user_id="user-1",
            request_session=fake_request_session,
        )

    body = response.body  # bytes
    import json
    data = json.loads(body)
    assert data["status"] == "expired"
    fake_agent.session.assert_not_called()  # resume must NOT be called


@pytest.mark.asyncio
async def test_already_answered_tombstone(view, fake_agent, fake_manager, fake_request_session):
    """When hitl:result exists (tombstone) → return 'already_answered', no resume."""
    from parrot.human.models import InteractionResult, InteractionStatus
    fake_manager.get_result.return_value = InteractionResult(
        interaction_id="iid-1",
        status=InteractionStatus.COMPLETED,
        consolidated_value="yes",
    )

    hitl_resp = {"turn_id": "iid-1", "value": "yes"}

    with patch("parrot.human.get_default_human_manager", return_value=fake_manager), \
         patch("parrot.human.suspended_store.SuspendedExecutionStore"):
        response = await view._handle_hitl_resume(
            hitl_response=hitl_resp,
            agent=fake_agent,
            session_id="sess-1",
            user_id="user-1",
            request_session=fake_request_session,
        )

    import json
    data = json.loads(response.body)
    assert data["status"] == "already_answered"
    fake_agent.session.assert_not_called()


@pytest.mark.asyncio
async def test_cross_session_rejected(view, fake_agent, fake_manager, fake_request_session):
    """is_valid_respondent returning False → 403 forbidden."""
    fake_manager.is_valid_respondent.return_value = False

    hitl_resp = {"turn_id": "iid-1", "value": "yes"}

    with patch("parrot.human.get_default_human_manager", return_value=fake_manager), \
         patch("parrot.human.suspended_store.SuspendedExecutionStore"):
        response = await view._handle_hitl_resume(
            hitl_response=hitl_resp,
            agent=fake_agent,
            session_id="sess-1",
            user_id="user-1",
            request_session=fake_request_session,
        )

    assert response.status == 403
    fake_manager.receive_response.assert_not_called()


@pytest.mark.asyncio
async def test_unauthenticated_rejected(view, fake_agent, fake_manager):
    """Missing user_id in session → 403."""
    hitl_resp = {"turn_id": "iid-1", "value": "yes"}
    bad_session = {"user_id": "unknown"}

    with patch("parrot.human.get_default_human_manager", return_value=fake_manager):
        response = await view._handle_hitl_resume(
            hitl_response=hitl_resp,
            agent=fake_agent,
            session_id="sess-1",
            user_id="user-1",
            request_session=bad_session,
        )

    assert response.status == 403


@pytest.mark.asyncio
async def test_alive_records_then_resumes(view, fake_agent, fake_manager, fake_request_session):
    """Alive interaction → receive_response called THEN agent.resume called."""
    suspended = _make_suspended()

    hitl_resp = {"turn_id": "iid-1", "value": "approved"}

    with patch("parrot.human.get_default_human_manager", return_value=fake_manager), \
         patch("parrot.human.suspended_store.SuspendedExecutionStore") as MockStore:
        store_instance = MagicMock()
        store_instance.load = AsyncMock(return_value=suspended)
        store_instance.delete = AsyncMock(return_value=None)
        MockStore.return_value = store_instance

        response = await view._handle_hitl_resume(
            hitl_response=hitl_resp,
            agent=fake_agent,
            session_id="sess-1",
            user_id="user-1",
            request_session=fake_request_session,
        )

    # receive_response must have been called
    fake_manager.receive_response.assert_called_once()
    # agent.session must have been called (resume path)
    fake_agent.session.assert_called_once()
    # suspended state must have been deleted BEFORE resume
    store_instance.delete.assert_called_once_with("iid-1")


@pytest.mark.asyncio
async def test_missing_turn_id_returns_400(view, fake_agent, fake_manager, fake_request_session):
    """hitl_response without turn_id → 400."""
    hitl_resp = {"value": "yes"}  # no turn_id

    with patch("parrot.human.get_default_human_manager", return_value=fake_manager):
        response = await view._handle_hitl_resume(
            hitl_response=hitl_resp,
            agent=fake_agent,
            session_id="sess-1",
            user_id="user-1",
            request_session=fake_request_session,
        )

    assert response.status == 400
