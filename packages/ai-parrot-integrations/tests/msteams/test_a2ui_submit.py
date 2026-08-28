"""MS Teams native A2UI-input submit routing tests (FEAT-470 TASK-2545).

An Adaptive Cards ``Action.Submit`` built by
``parrot.outputs.a2ui_renderers.adaptive_cards.AdaptiveCardsRenderer`` carries
``activity.value == {"a2ui_action": <v1.0 "action" envelope>, "surfaceId": ...,
**{<encoded input id>: <value>, ...}}``. The wrapper's
``_handle_card_submission`` must route that into a structured
``{"type": "a2ui_action", "action": <sobre>, "values": {...}}`` turn — the
SAME injection path (``form_orchestrator.process_message``) the existing
``a2ui_token`` deep-link-resume branch already uses (see
``_handle_card_submission`` around the ``a2ui_token``/``a2ui_action`` hook
points).

The wrapper module imports ``botbuilder``/``azure-teambots`` (Cython), which
are NOT installed in this worktree's dev venv (see
``test_deeplink_resume.py``'s own note) — ``pytest.importorskip`` below skips
this file cleanly here while still validating the real wrapper code in any
environment that has the ``msteams`` extra installed (e.g. CI).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("botbuilder")

from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper

pytestmark = pytest.mark.asyncio


def _wrapper(*, process_message_result=None) -> MSTeamsAgentWrapper:
    """A bare ``MSTeamsAgentWrapper`` with only the attributes
    ``_handle_card_submission``'s ``a2ui_action`` branch touches — building a
    full instance would require a real agent/adapter/config wiring irrelevant
    to this routing logic.
    """
    wrapper = MSTeamsAgentWrapper.__new__(MSTeamsAgentWrapper)
    wrapper.config = SimpleNamespace(allowed_conversation_ids=None, allowed_user_ids=None)
    wrapper.logger = MagicMock()
    wrapper._command_router = None
    wrapper.form_orchestrator = MagicMock()
    wrapper.form_orchestrator.process_message = AsyncMock(
        return_value=process_message_result
        or SimpleNamespace(raw_response=None, response_text="Action handled.")
    )
    wrapper.send_text = AsyncMock()
    wrapper._send_parsed_response = AsyncMock()
    wrapper._parse_response = MagicMock()
    return wrapper


def _turn_context(value: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.activity.value = value
    ctx.activity.conversation.id = "conv-1"
    ctx.activity.from_property.id = "user-1"
    return ctx


class TestTeamsWrapperRoutesA2UIAction:
    async def test_teams_wrapper_routes_a2ui_action(self):
        """`activity.value["a2ui_action"]` -> a structured `{"type":"a2ui_action", ...}` turn."""
        sobre = {
            "version": "v1.0",
            "action": {
                "name": "go",
                "surfaceId": "s1",
                "sourceComponentId": "btn1",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "context": {},
            },
        }
        submitted = {
            "a2ui_action": sobre,
            "surfaceId": "s1",
            "~1form~1email": "user@example.com",
        }
        wrapper = _wrapper()
        turn_context = _turn_context(submitted)

        await wrapper._handle_card_submission(turn_context, dialog_context=MagicMock())

        wrapper.form_orchestrator.process_message.assert_awaited_once()
        _, kwargs = wrapper.form_orchestrator.process_message.call_args
        assert kwargs["conversation_id"] == "conv-1"
        assert kwargs["context"] == {"user_id": "user-1", "session_id": "conv-1"}

        turn = json.loads(kwargs["message"])
        assert turn["type"] == "a2ui_action"
        assert turn["action"] == sobre
        assert turn["values"] == {"/form/email": "user@example.com"}

        wrapper.send_text.assert_awaited_once_with("Action handled.", turn_context)

    async def test_teams_wrapper_a2ui_action_returns_early_before_command_router(self):
        """The `a2ui_action` branch must short-circuit — never fall through to
        the slash-command / dialog-continuation handling below it."""
        sobre = {"version": "v1.0", "action": {"name": "go", "surfaceId": "s1", "sourceComponentId": "b", "timestamp": "t", "context": {}}}
        wrapper = _wrapper()
        wrapper._command_router = MagicMock()
        wrapper._command_router.try_dispatch = AsyncMock(side_effect=AssertionError("must not be reached"))
        turn_context = _turn_context({"a2ui_action": sobre, "surfaceId": "s1", "command": "/should_not_run"})

        await wrapper._handle_card_submission(turn_context, dialog_context=MagicMock())

        wrapper._command_router.try_dispatch.assert_not_awaited()

    async def test_teams_wrapper_no_a2ui_action_key_falls_through(self):
        """Without an `a2ui_action` key, the branch is a no-op — normal
        (e.g. slash-command) submission handling still runs."""
        wrapper = _wrapper()
        wrapper._command_router = MagicMock()
        wrapper._command_router.try_dispatch = AsyncMock(return_value=True)
        turn_context = _turn_context({"command": "/connect_jira"})

        await wrapper._handle_card_submission(turn_context, dialog_context=MagicMock())

        wrapper.form_orchestrator.process_message.assert_not_awaited()
        wrapper._command_router.try_dispatch.assert_awaited_once_with("/connect_jira", turn_context)


class TestDecodeA2UIInputId:
    def test_input_id_encoding_roundtrip(self):
        """Inverse of `adaptive_cards._encode_binding_id` (RFC 6901 tilde-escape)."""
        decode = MSTeamsAgentWrapper._decode_a2ui_input_id
        for encoded, expected in (
            ("~1form~1email", "/form/email"),
            ("~1a~1b~1c", "/a/b/c"),
            ("plain-id", "plain-id"),
            ("", ""),
        ):
            assert decode(encoded) == expected

    def test_decode_matches_adaptive_cards_encode(self):
        """Round-trips against the actual encoder used by the renderer."""
        pytest.importorskip("parrot.outputs.a2ui_renderers.adaptive_cards")
        from parrot.outputs.a2ui_renderers.adaptive_cards import _encode_binding_id

        decode = MSTeamsAgentWrapper._decode_a2ui_input_id
        for path in ("/form/name", "/a/b/c", "/weird~name/x"):
            assert decode(_encode_binding_id(path)) == path
