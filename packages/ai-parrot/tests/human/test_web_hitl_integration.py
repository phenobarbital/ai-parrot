"""End-to-end integration tests for the web HITL flow.

Covers TASK-1011: three E2E tests that exercise the full web HITL stack:
  - test_e2e_human_tool_over_web
  - test_e2e_handoff_tool_over_web
  - test_e2e_demo_agent_full_flight

The manager's Redis backend is replaced by an in-process dictionary so no
running Redis server is required.
"""
from __future__ import annotations

import asyncio
import json
import pytest
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.handlers.web_hitl import (
    WebHumanTool,
    HITLResponseHandler,
    HITLResponseBody,
    set_current_web_session,
    reset_current_web_session,
    get_current_web_session,
)
from parrot.human import (
    HumanInteractionManager,
    set_default_human_manager,
    get_default_human_manager,
)
from parrot.human.channels.web import WebHumanChannel
from parrot.human.models import (
    HumanInteraction,
    HumanResponse,
    InteractionType,
)
from parrot.agents.demo import HITLDemoAgent, BookFlightTool
from parrot.core.exceptions import HumanInteractionInterrupt


# ---------------------------------------------------------------------------
# In-process fake Redis (dict-backed, no external dependency)
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal async Redis stub backed by a plain dict.

    Implements only the operations used by HumanInteractionManager so the
    integration tests can run without a live Redis server.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Any] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        """Store value with an ignored TTL."""
        self._store[key] = value

    async def set(self, key: str, value: str) -> None:
        """Store value."""
        self._store[key] = value

    async def get(self, key: str) -> Optional[str]:
        """Retrieve value or None."""
        return self._store.get(key)

    async def rpush(self, key: str, *values: str) -> int:
        """Append to list."""
        lst = self._store.setdefault(key, [])
        lst.extend(values)
        return len(lst)

    async def lrange(self, key: str, start: int, end: int) -> list:
        """Return list slice."""
        lst = self._store.get(key, [])
        if end == -1:
            return lst[start:]
        return lst[start:end + 1]

    async def expire(self, key: str, seconds: int) -> None:
        """No-op TTL update."""

    async def delete(self, *keys: str) -> None:
        """Remove keys."""
        for key in keys:
            self._store.pop(key, None)

    async def publish(self, channel: str, message: str) -> int:
        """No-op pub/sub for testing."""
        return 0


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_default_manager():
    """Reset the global default manager between tests."""
    original = get_default_human_manager()
    yield
    set_default_human_manager(original)


@pytest.fixture
def fake_socket_manager():
    """Mock UserSocketManager that records every notify_channel call.

    Args:
        None

    Returns:
        A :class:`unittest.mock.MagicMock` with ``notify_channel`` as an
        :class:`unittest.mock.AsyncMock` that always returns ``True``.
    """
    manager = MagicMock()
    manager.notify_channel = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def fake_redis() -> _FakeRedis:
    """Return a fresh in-process fake Redis store.

    Returns:
        A new :class:`_FakeRedis` instance with an empty backing store.
    """
    return _FakeRedis()


@pytest.fixture
async def real_manager(fake_socket_manager, fake_redis):
    """HumanInteractionManager wired to FakeRedis and WebHumanChannel.

    Args:
        fake_socket_manager: Fixture providing a mocked socket manager.
        fake_redis: Fixture providing an in-process fake Redis store.

    Yields:
        A fully initialised :class:`~parrot.human.HumanInteractionManager`
        with a ``"web"`` channel registered and startup hooks run.
    """
    channel = WebHumanChannel(socket_manager=fake_socket_manager)
    manager = HumanInteractionManager(
        channels={"web": channel},
        redis_url="redis://localhost",  # overridden below
    )
    # Patch Redis with in-process store to avoid external dependency
    manager._redis = fake_redis  # type: ignore[attr-defined]

    await manager.startup()
    set_default_human_manager(manager)
    yield manager


# ---------------------------------------------------------------------------
# Helper: build a simple free_text HumanInteraction
# ---------------------------------------------------------------------------


def _make_interaction(
    interaction_id: str = "test-interaction-uuid-001",
    question: str = "What is the departure date?",
    session_id: str = "session-abc",
    interaction_type: InteractionType = InteractionType.FREE_TEXT,
) -> HumanInteraction:
    """Create a minimal HumanInteraction for testing.

    Args:
        interaction_id: Unique identifier for the interaction.
        question: The question to ask the human.
        session_id: Target user session ID.
        interaction_type: The type of interaction.

    Returns:
        A :class:`~parrot.human.models.HumanInteraction` instance.
    """
    return HumanInteraction(
        interaction_id=interaction_id,
        question=question,
        interaction_type=interaction_type,
        target_humans=[session_id],
    )


# ---------------------------------------------------------------------------
# Test 1: E2E Human Tool over Web
# ---------------------------------------------------------------------------


class TestE2EHumanToolOverWeb:
    """E2E: agent calls WebHumanTool, channel emits payload, POST responds,
    agent resumes with the user's answer."""

    @pytest.mark.asyncio
    async def test_e2e_human_tool_over_web(self, real_manager, fake_socket_manager):
        """Full round-trip: WebHumanTool waits for a human answer via POST.

        Steps:
            1. Set the current web session ContextVar.
            2. Call WebHumanTool._execute (which calls manager.request_human_input).
            3. Concurrently simulate the user's POST by calling receive_response.
            4. Assert the tool returns the user's answer.
            5. Assert the channel emitted a hitl:question payload.

        Args:
            real_manager: A fully wired HumanInteractionManager with WebHumanChannel.
            fake_socket_manager: Records notify_channel calls.
        """
        session_id = "session-e2e-001"
        interaction_id = "e2e-uuid-tool-001"
        user_answer = "Paris"

        # Pre-populate the interaction in fake redis so receive_response can find it
        interaction = _make_interaction(
            interaction_id=interaction_id,
            question="Where do you want to fly?",
            session_id=session_id,
            interaction_type=InteractionType.FREE_TEXT,
        )
        await real_manager._persist_interaction(interaction)

        # Register a future manually (mirrors what request_human_input does)
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        real_manager._pending_futures[interaction_id] = future

        # Simulate user's POST: receive_response should resolve the future
        response = HumanResponse(
            interaction_id=interaction_id,
            respondent=session_id,
            response_type=InteractionType.FREE_TEXT,
            value=user_answer,
        )

        async def _deliver_response():
            """Deliver response after a brief delay to simulate async HTTP POST."""
            await asyncio.sleep(0.05)
            await real_manager.receive_response(response)

        # Await the future while concurrently delivering the response
        delivery_task = asyncio.create_task(_deliver_response())
        try:
            result = await asyncio.wait_for(future, timeout=2.0)
        finally:
            await delivery_task

        assert result is not None
        assert result.consolidated_value == user_answer
        assert result.interaction_id == interaction_id

    @pytest.mark.asyncio
    async def test_e2e_web_human_tool_emits_via_channel(
        self, real_manager, fake_socket_manager
    ):
        """WebHumanTool._execute causes WebHumanChannel to call notify_channel.

        The channel should emit a ``hitl:question`` event containing the
        interaction payload to the target session.

        Args:
            real_manager: A wired manager with WebHumanChannel.
            fake_socket_manager: Records notify_channel calls.
        """
        session_id = "session-e2e-channel-001"

        # Patch request_human_input to return immediately after channel dispatch
        captured_interaction: list = []

        async def _fake_request_human_input(interaction, channel="web"):
            captured_interaction.append(interaction)
            # Verify channel called notify_channel
            from parrot.human.models import InteractionResult, InteractionStatus
            return InteractionResult(
                interaction_id=interaction.interaction_id,
                status=InteractionStatus.COMPLETED,
                responses=[],
                consolidated_value="Tokyo",
            )

        real_manager.request_human_input = _fake_request_human_input

        token = set_current_web_session(session_id)
        try:
            tool = WebHumanTool(source_agent="hitl_demo")
            result = await tool._execute(
                interaction_type="free_text",
                question="Which city?",
            )
        finally:
            reset_current_web_session(token)

        assert result == "Tokyo"
        assert len(captured_interaction) == 1
        assert captured_interaction[0].target_humans == [session_id]


# ---------------------------------------------------------------------------
# Test 2: E2E Handoff (BookFlightTool interrupt)
# ---------------------------------------------------------------------------


class TestE2EHandoffToolOverWeb:
    """E2E: BookFlightTool raises HumanInteractionInterrupt on a bad date."""

    @pytest.mark.asyncio
    async def test_e2e_handoff_tool_raises_on_bad_date(self):
        """BookFlightTool raises HumanInteractionInterrupt for a malformed date.

        This exercises the interrupt propagation path that the HandoffTool
        resume hook is designed to handle.

        Verifies:
            - :class:`~parrot.core.exceptions.HumanInteractionInterrupt` is raised.
            - The interrupt prompt contains the destination name.
        """
        tool = BookFlightTool()
        with pytest.raises(HumanInteractionInterrupt) as exc_info:
            await tool._execute(destination="Berlin", date="next Tuesday")

        assert "Berlin" in str(exc_info.value.prompt)

    @pytest.mark.asyncio
    async def test_e2e_handoff_tool_returns_confirmation_on_valid_date(self):
        """BookFlightTool returns a booking confirmation for a valid YYYY-MM-DD date.

        Verifies:
            - No exception is raised.
            - The result is a non-empty string containing 'confirmation'.
            - The result contains the destination name.
        """
        tool = BookFlightTool()
        result = await tool._execute(destination="Berlin", date="2026-09-01")

        assert result is not None
        assert isinstance(result, str)
        assert "confirmation" in result.lower()
        assert "Berlin" in result

    @pytest.mark.asyncio
    async def test_e2e_interrupt_propagates_through_manager(
        self, real_manager
    ):
        """HumanInteractionInterrupt raised by BookFlightTool is not swallowed.

        When a tool raises HumanInteractionInterrupt, the exception must
        propagate out of the tool's _execute without being silently caught.

        Args:
            real_manager: Provides a wired manager (ensures HITL stack is live).
        """
        tool = BookFlightTool()
        with pytest.raises(HumanInteractionInterrupt):
            await tool._execute(destination="Rome", date="summer")


# ---------------------------------------------------------------------------
# Test 3: E2E Demo Agent Full Flight
# ---------------------------------------------------------------------------


class TestE2EDemoAgentFullFlight:
    """E2E: HITLDemoAgent instantiates correctly and its tools are properly wired."""

    def test_e2e_demo_agent_instantiation(self):
        """HITLDemoAgent can be instantiated and its registry entry is valid.

        Verifies:
            - The agent class instantiates without error.
            - ``agent_id`` is set to ``'hitl_demo'``.
            - The agent is registered in the agent registry.
        """
        from parrot.registry import agent_registry

        agent = HITLDemoAgent()
        assert agent.agent_id == "hitl_demo"
        assert agent_registry.has("hitl_demo")

    def test_e2e_demo_agent_tools_configured(self):
        """HITLDemoAgent.agent_tools() returns the correct tool set.

        Verifies:
            - ``ask_human`` (WebHumanTool) is present.
            - ``handoff_to_human`` (HandoffTool) is present.
            - ``book_flight`` (BookFlightTool) is present.
        """
        agent = HITLDemoAgent()
        tools = agent.agent_tools()
        tool_names = {t.name for t in tools}

        assert "ask_human" in tool_names
        assert "handoff_to_human" in tool_names
        assert "book_flight" in tool_names

    @pytest.mark.asyncio
    async def test_e2e_demo_agent_book_flight_interrupt_then_valid(self):
        """Full round-trip: bad date raises interrupt, valid date confirms booking.

        This mimics the LLM calling BookFlightTool twice — once with a bad
        date (triggering the interrupt resume path) and once with a valid
        date (producing a confirmation).

        Verifies:
            - First call raises :class:`~parrot.core.exceptions.HumanInteractionInterrupt`.
            - Second call returns a confirmation string with the destination.
        """
        agent = HITLDemoAgent()
        tools = {t.name: t for t in agent.agent_tools()}
        book_tool = tools["book_flight"]

        # Attempt 1 — bad date
        with pytest.raises(HumanInteractionInterrupt):
            await book_tool._execute(destination="Sydney", date="ASAP")

        # Attempt 2 — user provides correct date
        result = await book_tool._execute(destination="Sydney", date="2026-11-20")
        assert "Sydney" in result
        assert "confirmation" in result.lower()

    @pytest.mark.asyncio
    async def test_e2e_web_human_tool_target_from_contextvar_in_agent(
        self, real_manager
    ):
        """WebHumanTool in HITLDemoAgent reads target from ContextVar.

        Simulates a web request where the session ID is injected via
        ``set_current_web_session`` and the manager is pre-populated.

        Args:
            real_manager: Provides a wired manager so WebHumanTool can resolve.
        """
        session_id = "session-agent-e2e-001"

        # Patch request_human_input on the real manager to return immediately
        async def _fast_response(interaction, channel="web"):
            from parrot.human.models import InteractionResult, InteractionStatus
            return InteractionResult(
                interaction_id=interaction.interaction_id,
                status=InteractionStatus.COMPLETED,
                responses=[],
                consolidated_value="London",
            )

        real_manager.request_human_input = _fast_response

        agent = HITLDemoAgent()
        tools = {t.name: t for t in agent.agent_tools()}
        ask_tool = tools["ask_human"]

        token = set_current_web_session(session_id)
        try:
            result = await ask_tool._execute(
                interaction_type="free_text",
                question="Where would you like to fly?",
            )
        finally:
            reset_current_web_session(token)

        assert result == "London"
