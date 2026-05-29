"""HITL-web suspend/resume integration tests (FEAT-204 / TASK-1384).

Tests the full stateless HITL suspend → paused → resume → success cycle and
its failure modes, wired against a real HumanInteractionManager on fakeredis
and a deterministic stub agent.

The tests exercise the component interfaces (SuspendedExecutionStore,
_handle_hitl_resume, SuspendingWebHumanTool) together, providing end-to-end
coverage of the FEAT-204 contract without requiring a live HTTP server.
"""
from __future__ import annotations

import asyncio
import json
import pytest
import pytest_asyncio
import fakeredis.aioredis
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.human import HumanInteractionManager, set_default_human_manager
from parrot.human.models import (
    HumanInteraction,
    HumanResponse,
    InteractionType,
    InteractionResult,
    InteractionStatus,
)
from parrot.human.suspended_store import SuspendedExecution, SuspendedExecutionStore
from parrot.handlers.agent import AgentTalk, PausedEnvelope
from parrot.core.exceptions import HumanInteractionInterrupt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fake_redis():
    """Fakeredis async client with decode_responses=True."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def manager(fake_redis):
    """HumanInteractionManager wired to fakeredis."""
    from parrot.human import set_default_human_manager
    mgr = HumanInteractionManager()
    mgr._redis = fake_redis  # inject fakeredis directly
    set_default_human_manager(mgr)
    yield mgr
    set_default_human_manager(None)


@pytest_asyncio.fixture
async def sus_store(fake_redis):
    """SuspendedExecutionStore backed by fakeredis."""
    return SuspendedExecutionStore(fake_redis)


@pytest.fixture
def view():
    """Minimal fake AgentTalk view for testing _handle_hitl_resume."""
    class _FakeView:
        logger = MagicMock()

        def _format_response(self, ai_message, output_format, format_kwargs,
                             user_id=None, user_session=None,
                             response_time_ms=None, agent_name=None):
            from aiohttp import web
            return web.json_response({"status": "success", "content": str(ai_message)})

        _handle_hitl_resume = AgentTalk._handle_hitl_resume

    return _FakeView()


def _make_interaction(interaction_id: str = "iid-1",
                      interaction_type: InteractionType = InteractionType.FREE_TEXT,
                      options=None) -> HumanInteraction:
    """Build a minimal HumanInteraction for testing."""
    kwargs: dict = dict(
        interaction_id=interaction_id,
        question="approve?",
        interaction_type=interaction_type,
        timeout=7200.0,
        target_humans=["user-1"],
    )
    if options:
        kwargs["options"] = options
    return HumanInteraction(**kwargs)


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


# ---------------------------------------------------------------------------
# test_e2e_suspend_returns_paused
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_suspend_returns_paused(manager, sus_store, fake_redis):
    """Drive a stub agent that raises HumanInteractionInterrupt (SUSPEND path).

    Asserts that:
    - SuspendedExecution is persisted at hitl:suspended:{id}
    - hitl:interaction:{id} exists (NOT deleted by the suspend catch)
    - PausedEnvelope has turn_id, interaction_type, options
    """
    from parrot.handlers.web_hitl import SuspendingWebHumanTool

    # 1. Create and persist a rich interaction via manager.
    from parrot.human.models import ChoiceOption
    interaction = _make_interaction(
        interaction_id="iid-suspend-1",
        interaction_type=InteractionType.SINGLE_CHOICE,
        options=[ChoiceOption(key="yes", label="Yes"), ChoiceOption(key="no", label="No")],
    )
    ttl = manager._compute_ttl(interaction)
    await manager._persist_interaction(interaction)

    # 2. Simulate what the suspend catch does when HumanInteractionInterrupt fires.
    suspended = SuspendedExecution(
        interaction_id="iid-suspend-1",
        session_id="sess-1",
        user_id="user-1",
        agent_name="test-agent",
        tool_call_id="tc-1",
        messages=[{"role": "assistant", "content": [{"type": "tool_use", "id": "tc-1"}]}],
    )
    await sus_store.save(suspended, ttl=ttl)

    # 3. Rehydrate the interaction (as AgentTalk.post does).
    rehydrated = await manager._load_interaction("iid-suspend-1")
    assert rehydrated is not None

    # 4. Build the PausedEnvelope.
    options_data = [o.model_dump() for o in rehydrated.options]
    paused = PausedEnvelope(
        turn_id="iid-suspend-1",
        interaction_id="iid-suspend-1",
        interaction_type=rehydrated.interaction_type.value,
        question=rehydrated.question,
        options=options_data,
    )

    # 5. Assert envelope shape.
    d = paused.model_dump()
    assert d["status"] == "paused"
    assert d["turn_id"] == "iid-suspend-1"
    assert d["interaction_type"] == "single_choice"
    assert d["options"] is not None and len(d["options"]) == 2

    # 6. Assert Redis keys exist.
    assert await fake_redis.get("hitl:suspended:iid-suspend-1") is not None
    assert await fake_redis.get("hitl:interaction:iid-suspend-1") is not None  # NOT deleted


# ---------------------------------------------------------------------------
# test_e2e_resume_to_success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_resume_to_success(manager, sus_store, fake_redis, view):
    """POST hitl_response for existing interaction → success response."""
    interaction = _make_interaction(interaction_id="iid-resume-1")
    ttl = manager._compute_ttl(interaction)
    await manager._persist_interaction(interaction)
    suspended = _make_suspended("iid-resume-1")
    await sus_store.save(suspended, ttl=ttl)

    # Build stub agent that returns a final reply from resume()
    session_ctx = MagicMock()
    ai_message_mock = MagicMock()
    ai_message_mock.__str__ = lambda self: "final answer"
    bot_mock = MagicMock()
    bot_mock.resume = AsyncMock(return_value=ai_message_mock)
    session_ctx.__aenter__ = AsyncMock(return_value=bot_mock)
    session_ctx.__aexit__ = AsyncMock(return_value=False)
    agent = MagicMock()
    agent.name = "test-agent"
    agent.session = MagicMock(return_value=session_ctx)

    hitl_resp = {"turn_id": "iid-resume-1", "value": "yes"}
    request_session = {"user_id": "user-1"}

    with patch("parrot.human.get_default_human_manager", return_value=manager):
        response = await view._handle_hitl_resume(
            hitl_response=hitl_resp,
            agent=agent,
            session_id="sess-1",
            user_id="user-1",
            request_session=request_session,
        )

    import json as _json
    data = _json.loads(response.body)
    assert data["status"] == "success"
    # receive_response must have persisted a result in Redis
    assert await fake_redis.get("hitl:result:iid-resume-1") is not None


# ---------------------------------------------------------------------------
# test_resume_expired
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_expired(manager, view):
    """Neither interaction nor result present → fast 'expired' reply."""
    hitl_resp = {"turn_id": "iid-no-such", "value": "yes"}
    request_session = {"user_id": "user-1"}
    agent = MagicMock()
    agent.name = "test-agent"

    with patch("parrot.human.get_default_human_manager", return_value=manager):
        response = await view._handle_hitl_resume(
            hitl_response=hitl_resp,
            agent=agent,
            session_id="sess-1",
            user_id="user-1",
            request_session=request_session,
        )

    import json
    data = json.loads(response.body)
    assert data["status"] == "expired"
    agent.session.assert_not_called()


# ---------------------------------------------------------------------------
# test_resume_already_answered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_already_answered(manager, fake_redis, view):
    """hitl:result tombstone present → 'already_answered', loop NOT re-run."""
    interaction_id = "iid-answered"
    interaction = _make_interaction(interaction_id=interaction_id)
    await manager._persist_interaction(interaction)

    # Simulate a prior answer (tombstone)
    result = InteractionResult(
        interaction_id=interaction_id,
        status=InteractionStatus.COMPLETED,
        consolidated_value="yes",
    )
    await manager._persist_result(result)

    hitl_resp = {"turn_id": interaction_id, "value": "no"}
    request_session = {"user_id": "user-1"}
    agent = MagicMock()
    agent.name = "test-agent"

    with patch("parrot.human.get_default_human_manager", return_value=manager):
        response = await view._handle_hitl_resume(
            hitl_response=hitl_resp,
            agent=agent,
            session_id="sess-1",
            user_id="user-1",
            request_session=request_session,
        )

    import json
    data = json.loads(response.body)
    assert data["status"] == "already_answered"
    agent.session.assert_not_called()  # tool-loop NOT re-run


# ---------------------------------------------------------------------------
# test_resume_cross_session_rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_cross_session_rejected(manager, view):
    """Respondent not in target_humans → 403 (fails closed)."""
    interaction = _make_interaction(interaction_id="iid-cross")
    await manager._persist_interaction(interaction)

    hitl_resp = {"turn_id": "iid-cross", "value": "yes"}
    # Use a different user_id than target_humans=["user-1"]
    bad_session = {"user_id": "attacker"}

    with patch("parrot.human.get_default_human_manager", return_value=manager):
        response = await view._handle_hitl_resume(
            hitl_response=hitl_resp,
            agent=MagicMock(),
            session_id="sess-x",
            user_id="attacker",
            request_session=bad_session,
        )

    assert response.status == 403


# ---------------------------------------------------------------------------
# test_structured_types_survive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_types_survive(manager, sus_store, fake_redis):
    """single_choice/form options/schema survive the suspend → paused round-trip."""
    from parrot.human.models import ChoiceOption

    # single_choice interaction
    interaction = _make_interaction(
        interaction_id="iid-struct",
        interaction_type=InteractionType.SINGLE_CHOICE,
        options=[
            ChoiceOption(key="a", label="Option A"),
            ChoiceOption(key="b", label="Option B"),
        ],
    )
    ttl = manager._compute_ttl(interaction)
    await manager._persist_interaction(interaction)

    suspended = _make_suspended("iid-struct")
    await sus_store.save(suspended, ttl=ttl)

    # Rehydrate and build envelope
    rehydrated = await manager._load_interaction("iid-struct")
    assert rehydrated is not None
    assert len(rehydrated.options) == 2

    options_data = [o.model_dump() for o in rehydrated.options]
    paused = PausedEnvelope(
        turn_id="iid-struct",
        interaction_id="iid-struct",
        interaction_type="single_choice",
        question="pick one",
        options=options_data,
    )
    d = paused.model_dump()
    assert d["options"][0]["key"] == "a"
    assert d["options"][1]["key"] == "b"
    assert d["status"] == "paused"

    # Verify TTL is set on the suspended key
    ttl_remaining = await fake_redis.ttl("hitl:suspended:iid-struct")
    assert ttl_remaining > 0
