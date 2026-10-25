"""Routing tests for the FEAT-551 `_formdesigner` branch (skips without botbuilder, like test_a2ui_submit.py)."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

pytest.importorskip("botbuilder")
from parrot.integrations.msteams import wrapper as wrapper_mod
from parrot.integrations.msteams.formdesigner_submit import SubmitOutcome
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper

pytestmark = pytest.mark.asyncio


def _wrapper(allowed_hosts=("forms.test",)) -> MSTeamsAgentWrapper:
    w = MSTeamsAgentWrapper.__new__(MSTeamsAgentWrapper)
    w.config = SimpleNamespace(
        allowed_conversation_ids=None,
        allowed_user_ids=None,
        formdesigner_allowed_hosts=list(allowed_hosts),
        formdesigner_submit_token=None,
        formdesigner_submit_secret=None,
        formdesigner_submit_timeout=5.0,
    )
    w.logger = MagicMock()
    w._command_router = MagicMock()
    w._command_router.try_dispatch = AsyncMock(return_value=True)
    w.form_orchestrator = MagicMock()
    w.send_text = AsyncMock()
    w.send_card = AsyncMock()
    w._formdesigner_session = None
    w._formdesigner_recent = wrapper_mod.RecentActivityCache()
    return w


def _ctx(value: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.activity.value = value
    ctx.activity.id = "act-1"
    ctx.activity.conversation.id = "conv-1"
    ctx.activity.from_property.id = "user-1"
    return ctx


async def test_teams_wrapper_routes_formdesigner_submit():
    """FormDesigner envelope in card submit -> POST to submit_url, reply with card, never continue dialog."""
    # Valid envelope dict + submit action + field value
    envelope = {
        "v": 1,
        "wire": "legacy",
        "form_uid": "f0000000-0000-0000-0000-000000000001",
        "tenant": "testtenant",
        "form_version": "1.0",
        "is_public": True,
        "submit_url": "https://forms.test/api/v1/testtenant/forms/f0000000-0000-0000-0000-000000000001/data",
        "form_url": "https://forms.test/testtenant/forms/f0000000-0000-0000-0000-000000000001",
    }
    value = {
        "_formdesigner": envelope,
        "_action": "submit",
        "name": "John Doe",
    }

    w = _wrapper()
    dialog_context = MagicMock(continue_dialog=AsyncMock())

    # Mock post_submission to return a successful outcome
    with patch.object(wrapper_mod, "post_submission", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = SubmitOutcome(status=200, body={"submission_id": "s1"})
        await w._handle_card_submission(_ctx(value), dialog_context)

        # post_submission should be called with the extracted answers
        mock_post.assert_awaited_once()
        call_args = mock_post.call_args
        answers = call_args[0][2]  # Third positional arg is answers
        assert answers == {"name": "John Doe"}

        # send_card should be called with the reply card
        w.send_card.assert_awaited_once()

        # continue_dialog should NOT be called (branch returns early)
        dialog_context.continue_dialog.assert_not_awaited()

        # command router should NOT be called (bounded by AC "returns before command routing")
        w._command_router.try_dispatch.assert_not_awaited()


async def test_teams_wrapper_formdesigner_disabled_without_allowlist():
    """Empty allowlist -> 'not enabled' message, no HTTP call."""
    w = _wrapper(allowed_hosts=())
    envelope = {
        "v": 1,
        "wire": "legacy",
        "form_uid": "f0000000-0000-0000-0000-000000000001",
        "tenant": "testtenant",
        "form_version": "1.0",
        "is_public": True,
        "submit_url": "https://forms.test/api/v1/testtenant/forms/f0000000-0000-0000-0000-000000000001/data",
        "form_url": "https://forms.test/testtenant/forms/f0000000-0000-0000-0000-000000000001",
    }
    value = {
        "_formdesigner": envelope,
        "_action": "submit",
        "name": "John",
    }
    dialog_context = MagicMock(continue_dialog=AsyncMock())

    with patch.object(wrapper_mod, "post_submission", new_callable=AsyncMock) as mock_post:
        await w._handle_card_submission(_ctx(value), dialog_context)

        # Should send "not enabled" text
        w.send_text.assert_awaited_once_with(
            "Form submissions are not enabled for this bot.", w.send_text.call_args[0][1]
        )

        # post_submission should NOT be called
        mock_post.assert_not_awaited()


async def test_teams_wrapper_malformed_envelope_is_text_reply():
    """Malformed envelope -> send_text with error, never continue dialog."""
    w = _wrapper()
    value = {
        "_formdesigner": {"bad": 1},
        "_action": "submit",
    }
    dialog_context = MagicMock(continue_dialog=AsyncMock())

    with patch.object(wrapper_mod, "post_submission", new_callable=AsyncMock) as mock_post:
        await w._handle_card_submission(_ctx(value), dialog_context)

        # Should send a text reply about malformed envelope
        w.send_text.assert_awaited_once()
        # The error message should mention "malformed" or "valid"
        error_text = w.send_text.call_args[0][0]
        assert "malformed" in error_text.lower() or "valid" in error_text.lower()

        # post_submission should NOT be called
        mock_post.assert_not_awaited()

        # continue_dialog should NOT be called
        dialog_context.continue_dialog.assert_not_awaited()


class _FDAgent:
    """Minimal FormDesigner mixin stand-in with observable request-local state."""

    formdesigner_serving = True

    def __init__(self, handled: bool = True) -> None:
        self.handled = handled
        self.events: list[str] = []
        self.handle_formdesigner_card = AsyncMock(side_effect=self._handle_card)
        self.apply_teams_config = MagicMock()
        self.bind_teams_identity = MagicMock()
        self.getform_handler = AsyncMock()
        self.listforms_handler = AsyncMock()
        self.flush_formdesigner_cards = AsyncMock(side_effect=self._flush)

    async def _handle_card(self, *args) -> bool:
        return self.handled

    def teams_commands(self) -> dict[str, AsyncMock]:
        return {"getform": self.getform_handler, "listforms": self.listforms_handler}

    @asynccontextmanager
    async def formdesigner_turn(self, turn_context):
        self.events.append("enter")
        try:
            yield None
        finally:
            self.events.append("exit")

    async def _flush(self, turn_context) -> None:
        self.events.append("flush")


async def test_wrapper_falls_back_without_mixin():
    """A non-mixin agent keeps the legacy envelope route."""
    w = _wrapper()
    w.agent = MagicMock()
    w._handle_formdesigner_submit = AsyncMock()
    context = _ctx({"_formdesigner": {}})

    await w._handle_card_submission(context, MagicMock())

    w._handle_formdesigner_submit.assert_awaited_once_with(context, {"_formdesigner": {}})


async def test_wrapper_asks_mixin_first():
    """A mixin that handles an envelope prevents the legacy POST branch."""
    w = _wrapper()
    agent = _FDAgent(handled=True)
    w.agent = agent
    w._handle_formdesigner_submit = AsyncMock()
    context = _ctx({"_formdesigner": {}})

    await w._handle_card_submission(context, MagicMock())

    agent.handle_formdesigner_card.assert_awaited_once_with(context, {"_formdesigner": {}})
    w._handle_formdesigner_submit.assert_not_awaited()


async def test_mixin_declines_unknown_envelope_falls_back():
    """A declined envelope continues into the legacy submission handler."""
    w = _wrapper()
    agent = _FDAgent(handled=False)
    w.agent = agent
    w._handle_formdesigner_submit = AsyncMock()
    context = _ctx({"_formdesigner": {}})

    await w._handle_card_submission(context, MagicMock())

    agent.handle_formdesigner_card.assert_awaited_once()
    w._handle_formdesigner_submit.assert_awaited_once_with(context, {"_formdesigner": {}})


async def test_picker_action_routed_to_mixin():
    """Picker actions are handled by the mixin before dialog processing."""
    w = _wrapper()
    agent = _FDAgent(handled=True)
    w.agent = agent
    context = _ctx({"_formdesigner_action": "get_form"})
    dialog_context = MagicMock(continue_dialog=AsyncMock())

    await w._handle_card_submission(context, dialog_context)

    agent.handle_formdesigner_card.assert_awaited_once_with(context, {"_formdesigner_action": "get_form"})
    dialog_context.continue_dialog.assert_not_awaited()


async def test_wire_registers_commands_and_binds_store():
    """Wiring uses the wrapper-owned config and session store exactly once."""
    w = _wrapper()
    agent = _FDAgent()
    w.agent = agent
    w.config.name = "forms-agent"
    w._session_store = object()

    w._wire_formdesigner_agent()

    agent.apply_teams_config.assert_called_once_with(w.config)
    agent.bind_teams_identity.assert_called_once_with(w._session_store)
    assert w._command_router.register.call_args_list == [
        (("getform", agent.getform_handler),),
        (("listforms", agent.listforms_handler),),
    ]


async def test_toolkit_voice_and_card_continuations():
    """A2UI and voice process-message calls bind and flush only successful turns."""
    w = _wrapper()
    agent = _FDAgent()
    w.agent = agent
    successful = SimpleNamespace(has_error=False, raw_response=None, response_text="done", needs_form=False)
    failed = SimpleNamespace(has_error=True, error="failed")
    w.form_orchestrator.process_message = AsyncMock(side_effect=[successful, failed])
    w._effective_user_id = AsyncMock(return_value="user-1")
    w.dialogs = MagicMock(create_context=AsyncMock(return_value=MagicMock()))
    w.send_typing = AsyncMock()

    await w._handle_card_submission(_ctx({"a2ui_action": {"name": "save"}}), MagicMock())
    await w._process_transcribed_message(_ctx({}), "voice note", "conv-1")

    assert agent.events == ["enter", "flush", "exit", "enter", "exit"]
    agent.flush_formdesigner_cards.assert_awaited_once()


async def test_magicmock_agent_is_not_treated_as_mixin():
    """MagicMock's synthetic attributes cannot activate FormDesigner seams."""
    w = _wrapper()
    w.agent = MagicMock()

    assert w._formdesigner_agent() is None
