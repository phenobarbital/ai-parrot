"""
Unit tests for harness-state operator commands (FEAT-210 TASK-1396).

Tests: /health and /status — handlers that project HeartbeatManager state
(FEAT-209) and ephemeral sub-agent info (FEAT-208), each with independent
degradation when sources are absent.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# Shared stub + fixture (mirrors test_operator_commands_readonly pattern)
# ---------------------------------------------------------------------------

class _StubBase:
    """Minimal stand-in for TelegramAgentWrapper for testing the mixin methods."""

    def _is_operator(self, chat_id: int) -> bool:
        op_ids = getattr(self.config, 'operator_chat_ids', None)
        if not getattr(self.config, 'enable_operator_commands', True):
            return False
        if not op_ids:
            return False
        return chat_id in op_ids


def _make_op_wrapper(operator_chat_ids=None, app=None):
    """Build a minimal wrapper stand-in with OperatorCommandsMixin."""
    from parrot.integrations.telegram.operator_commands import OperatorCommandsMixin

    class _CombinedWrapper(OperatorCommandsMixin, _StubBase):
        pass

    w = _CombinedWrapper.__new__(_CombinedWrapper)
    w.logger = MagicMock()
    w.conversations = {}
    w.agent = MagicMock(name="agent")
    w.config = MagicMock()
    w.config.name = "test-bot"
    w.config.operator_chat_ids = operator_chat_ids if operator_chat_ids is not None else [111]
    w.config.enable_operator_commands = True
    w.app = app if app is not None else {}   # no heartbeat/bot_manager → degrade
    w._send_safe_message = AsyncMock()
    return w


def _make_message(chat_id: int, text: str = "") -> MagicMock:
    """Create a mock aiogram Message."""
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def _make_fake_heartbeat(states=None):
    """Create a fake HeartbeatManager with configurable get_all_states() return."""
    fake_hb = MagicMock()
    if states is None:
        states = []
    fake_hb.get_all_states.return_value = states
    return fake_hb


def _make_fake_state(agent_name: str, tick_count: int = 3):
    """Create a fake HeartbeatState object."""
    from datetime import datetime
    state = MagicMock()
    state.agent_name = agent_name
    state.tick_count = tick_count
    state.last_tick = datetime(2026, 6, 1, 12, 0, 0)
    return state


# ---------------------------------------------------------------------------
# /health tests
# ---------------------------------------------------------------------------

class TestHandleHealth:
    @pytest.mark.asyncio
    async def test_degrades_without_heartbeat_in_app(self):
        """No heartbeat_manager in app → 'not configured' message (runtime degrade)."""
        import parrot.integrations.telegram.operator_commands as oc_module
        original = oc_module.HeartbeatManager
        oc_module.HeartbeatManager = object  # pretend FEAT-209 is installed

        try:
            w = _make_op_wrapper(operator_chat_ids=[111], app={})
            msg = _make_message(chat_id=111)
            await w.handle_health(msg)
            text = w._send_safe_message.call_args[0][1]
            assert "not configured" in text.lower()
        finally:
            oc_module.HeartbeatManager = original

    @pytest.mark.asyncio
    async def test_degrades_when_heartbeat_import_absent(self):
        """HeartbeatManager is None (not installed) → degrade."""
        import parrot.integrations.telegram.operator_commands as oc_module
        original = oc_module.HeartbeatManager
        oc_module.HeartbeatManager = None  # simulate import failure

        try:
            w = _make_op_wrapper(operator_chat_ids=[111])
            msg = _make_message(chat_id=111)
            await w.handle_health(msg)
            text = w._send_safe_message.call_args[0][1]
            assert "not configured" in text.lower() or "not available" in text.lower()
        finally:
            oc_module.HeartbeatManager = original

    @pytest.mark.asyncio
    async def test_projects_heartbeat_state(self):
        """HeartbeatManager present with states → shows tick count and agent names."""
        import parrot.integrations.telegram.operator_commands as oc_module
        original = oc_module.HeartbeatManager
        oc_module.HeartbeatManager = object  # truthy sentinel

        try:
            fake_hb = _make_fake_heartbeat(states=[
                _make_fake_state("AgentAlpha", tick_count=42),
                _make_fake_state("AgentBeta", tick_count=7),
            ])
            w = _make_op_wrapper(
                operator_chat_ids=[111],
                app={'heartbeat_manager': fake_hb},
            )
            msg = _make_message(chat_id=111)
            await w.handle_health(msg)
            text = w._send_safe_message.call_args[0][1]
            assert "AgentAlpha" in text
            assert "42" in text
            assert "AgentBeta" in text
        finally:
            oc_module.HeartbeatManager = original

    @pytest.mark.asyncio
    async def test_non_operator_blocked(self):
        """Non-operator gets rejection message, not health info."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        msg = _make_message(chat_id=999)
        await w.handle_health(msg)
        msg.answer.assert_awaited_once()
        w._send_safe_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_projects_empty_states(self):
        """HeartbeatManager returns empty list → shows 'no agents' message."""
        import parrot.integrations.telegram.operator_commands as oc_module
        original = oc_module.HeartbeatManager
        oc_module.HeartbeatManager = object

        try:
            fake_hb = _make_fake_heartbeat(states=[])
            w = _make_op_wrapper(
                operator_chat_ids=[111],
                app={'heartbeat_manager': fake_hb},
            )
            msg = _make_message(chat_id=111)
            await w.handle_health(msg)
            text = w._send_safe_message.call_args[0][1]
            assert "heartbeat" in text.lower() or "agent" in text.lower()
        finally:
            oc_module.HeartbeatManager = original


# ---------------------------------------------------------------------------
# /status tests
# ---------------------------------------------------------------------------

class TestHandleStatus:
    @pytest.mark.asyncio
    async def test_degrades_both_absent(self):
        """No heartbeat, no sub-agents → both sections show 'not configured'."""
        import parrot.integrations.telegram.operator_commands as oc_module
        original = oc_module.HeartbeatManager
        oc_module.HeartbeatManager = None  # not installed

        try:
            w = _make_op_wrapper(operator_chat_ids=[111], app={})
            msg = _make_message(chat_id=111)
            await w.handle_status(msg)
            text = w._send_safe_message.call_args[0][1]
            assert "not configured" in text.lower() or "not available" in text.lower()
        finally:
            oc_module.HeartbeatManager = original

    @pytest.mark.asyncio
    async def test_heartbeat_only(self):
        """HeartbeatManager present, sub-agents absent → heartbeat shown, sub-agents degrade."""
        import parrot.integrations.telegram.operator_commands as oc_module
        original = oc_module.HeartbeatManager
        oc_module.HeartbeatManager = object

        try:
            fake_hb = _make_fake_heartbeat(states=[
                _make_fake_state("MainAgent", tick_count=10)
            ])
            w = _make_op_wrapper(
                operator_chat_ids=[111],
                app={'heartbeat_manager': fake_hb},
                # No 'bot_manager' key → sub-agents degrade
            )
            msg = _make_message(chat_id=111)
            await w.handle_status(msg)
            text = w._send_safe_message.call_args[0][1]
            # Heartbeat section shows agent info
            assert "MainAgent" in text
            # Sub-agents section shows unavailable/not configured
            assert "not available" in text.lower() or "sub-agent" in text.lower()
        finally:
            oc_module.HeartbeatManager = original

    @pytest.mark.asyncio
    async def test_full_status(self):
        """Both present → composite view with heartbeat and sub-agent info."""
        import parrot.integrations.telegram.operator_commands as oc_module
        original = oc_module.HeartbeatManager
        oc_module.HeartbeatManager = object

        try:
            fake_hb = _make_fake_heartbeat(states=[
                _make_fake_state("MainAgent", tick_count=5)
            ])
            fake_bm = MagicMock()
            fake_bm.get_ephemeral_status.return_value = "2 active sub-agents"

            w = _make_op_wrapper(
                operator_chat_ids=[111],
                app={
                    'heartbeat_manager': fake_hb,
                    'bot_manager': fake_bm,
                },
            )
            msg = _make_message(chat_id=111)
            await w.handle_status(msg)
            text = w._send_safe_message.call_args[0][1]
            assert "MainAgent" in text
            assert "2 active sub-agents" in text
        finally:
            oc_module.HeartbeatManager = original

    @pytest.mark.asyncio
    async def test_non_operator_blocked(self):
        """Non-operator gets rejection, not status info."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        msg = _make_message(chat_id=999)
        await w.handle_status(msg)
        msg.answer.assert_awaited_once()
        w._send_safe_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_sub_agents_only(self):
        """No heartbeat but bot_manager present → heartbeat degrades, sub-agents shown."""
        import parrot.integrations.telegram.operator_commands as oc_module
        original = oc_module.HeartbeatManager
        oc_module.HeartbeatManager = None  # heartbeat not installed

        try:
            fake_bm = MagicMock()
            fake_bm.get_ephemeral_status.return_value = "3 active sub-agents"

            w = _make_op_wrapper(
                operator_chat_ids=[111],
                app={'bot_manager': fake_bm},
            )
            msg = _make_message(chat_id=111)
            await w.handle_status(msg)
            text = w._send_safe_message.call_args[0][1]
            # heartbeat section should degrade
            assert "not configured" in text.lower() or "not available" in text.lower()
            # sub-agents should be shown
            assert "3 active sub-agents" in text
        finally:
            oc_module.HeartbeatManager = original
