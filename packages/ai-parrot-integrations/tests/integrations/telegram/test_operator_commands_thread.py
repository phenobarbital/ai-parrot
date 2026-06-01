"""
Unit tests for /thread operator command (FEAT-210 TASK-1397).

Tests: /thread <task> — fork work to an ephemeral sub-agent (FEAT-208),
with degrade paths when the sub-agent infrastructure is absent.
"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# Shared stub + fixture
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
    w.app = app if app is not None else {}
    w._send_safe_message = AsyncMock()
    return w


def _make_message(chat_id: int, text: str = "/thread") -> MagicMock:
    """Create a mock aiogram Message."""
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.text = text
    msg.answer = AsyncMock()
    return msg


# ---------------------------------------------------------------------------
# /thread tests
# ---------------------------------------------------------------------------

class TestHandleThread:
    @pytest.mark.asyncio
    async def test_degrades_without_spawn(self):
        """No bot_manager in app → 'sub-agents not available' message."""
        w = _make_op_wrapper(operator_chat_ids=[111], app={})
        msg = _make_message(chat_id=111, text="/thread Summarise news")
        await w.handle_thread(msg)
        # At least one call to _send_safe_message
        assert w._send_safe_message.await_count >= 1
        calls = [c[0][1] for c in w._send_safe_message.call_args_list]
        all_text = " ".join(calls).lower()
        assert "not available" in all_text or "sub-agent" in all_text

    @pytest.mark.asyncio
    async def test_no_task_shows_usage(self):
        """/thread with no arguments → usage message."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        msg = _make_message(chat_id=111, text="/thread")
        await w.handle_thread(msg)
        w._send_safe_message.assert_awaited_once()
        text = w._send_safe_message.call_args[0][1].lower()
        assert "usage" in text or "/thread" in text

    @pytest.mark.asyncio
    async def test_no_task_whitespace_only_shows_usage(self):
        """/thread with only whitespace after command → usage message."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        msg = _make_message(chat_id=111, text="/thread   ")
        await w.handle_thread(msg)
        w._send_safe_message.assert_awaited_once()
        text = w._send_safe_message.call_args[0][1].lower()
        assert "usage" in text or "/thread" in text

    @pytest.mark.asyncio
    async def test_non_operator_blocked(self):
        """Non-operator gets rejection message."""
        w = _make_op_wrapper(operator_chat_ids=[111])
        msg = _make_message(chat_id=999, text="/thread Do something")
        await w.handle_thread(msg)
        msg.answer.assert_awaited_once()
        w._send_safe_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_spawns_subagent_async(self):
        """/thread <task> invokes async spawn and returns result."""

        async def fake_spawn(task: str) -> str:
            return f"Result for: {task}"

        fake_bm = MagicMock()
        fake_bm.create_ephemeral_user_bot = fake_spawn

        w = _make_op_wrapper(
            operator_chat_ids=[111],
            app={'bot_manager': fake_bm},
        )
        msg = _make_message(chat_id=111, text="/thread Summarise news articles")
        await w.handle_thread(msg)

        calls = [c[0][1] for c in w._send_safe_message.call_args_list]
        all_text = " ".join(calls)
        # Should have spawning indicator and result
        assert "Summarise news articles" in all_text or "sub-agent" in all_text.lower()
        assert "Result for:" in all_text

    @pytest.mark.asyncio
    async def test_spawns_subagent_sync(self):
        """/thread <task> invokes sync spawn callable and returns result."""

        def fake_spawn_sync(task: str) -> str:
            return f"Sync result for: {task}"

        fake_bm = MagicMock()
        fake_bm.create_ephemeral_user_bot = fake_spawn_sync

        w = _make_op_wrapper(
            operator_chat_ids=[111],
            app={'bot_manager': fake_bm},
        )
        msg = _make_message(chat_id=111, text="/thread Write a report")
        await w.handle_thread(msg)

        calls = [c[0][1] for c in w._send_safe_message.call_args_list]
        all_text = " ".join(calls)
        assert "Sync result for:" in all_text

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Sub-agent exceeds timeout → timeout message sent."""
        from parrot.integrations.telegram.operator_commands import _THREAD_TIMEOUT

        async def slow_spawn(task: str) -> str:
            # Sleep longer than the timeout
            await asyncio.sleep(_THREAD_TIMEOUT + 10)
            return "This should not arrive"

        fake_bm = MagicMock()
        fake_bm.create_ephemeral_user_bot = slow_spawn

        w = _make_op_wrapper(
            operator_chat_ids=[111],
            app={'bot_manager': fake_bm},
        )
        msg = _make_message(chat_id=111, text="/thread Long running task")

        # Patch _THREAD_TIMEOUT to a very small value for the test
        import parrot.integrations.telegram.operator_commands as oc_module
        original_timeout = oc_module._THREAD_TIMEOUT
        oc_module._THREAD_TIMEOUT = 0.05  # 50 ms

        try:
            await w.handle_thread(msg)
        finally:
            oc_module._THREAD_TIMEOUT = original_timeout

        calls = [c[0][1] for c in w._send_safe_message.call_args_list]
        all_text = " ".join(calls).lower()
        assert "timed out" in all_text or "timeout" in all_text

    @pytest.mark.asyncio
    async def test_spawn_method_absent_on_bot_manager(self):
        """bot_manager present but no create_ephemeral_user_bot → method unavailable msg."""
        fake_bm = MagicMock(spec=[])  # no methods

        w = _make_op_wrapper(
            operator_chat_ids=[111],
            app={'bot_manager': fake_bm},
        )
        msg = _make_message(chat_id=111, text="/thread Some task")
        await w.handle_thread(msg)

        calls = [c[0][1] for c in w._send_safe_message.call_args_list]
        all_text = " ".join(calls).lower()
        assert "not available" in all_text or "spawn" in all_text or "unavailable" in all_text
