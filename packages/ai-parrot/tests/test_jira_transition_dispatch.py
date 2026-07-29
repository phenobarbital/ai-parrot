"""Tests for JiraSpecialist transition dispatch and built-in action handlers.

Covers:
- _dispatch_transition matching logic (exact, wildcard, project filter, disabled)
- _action_notify_channel (success, no wrapper, no channel_id)
- _action_trigger_agent (logs intent, returns structured result)
- _action_log_transition (structured log at configured level)
- handle_hook_event routing for jira.transitioned events
- Backward compatibility: existing events still routed correctly
"""
from __future__ import annotations

import sys
import types as _types_mod
import pytest
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Pre-stub Cython extensions so this test module can be collected without
# requiring compiled .so files in the source tree.  These stubs must be
# installed into sys.modules BEFORE any parrot.bots import occurs.
# ---------------------------------------------------------------------------
_CYTHON_STUBS = {
    "parrot.utils.types": {"SafeDict": dict},
    "parrot.utils.parsers.toml": {"TOMLParser": object},
    "parrot.utils.parsers": {"TOMLParser": object},
}
for _mod_name, _attrs in _CYTHON_STUBS.items():
    if _mod_name not in sys.modules:
        _stub = _types_mod.ModuleType(_mod_name)
        for _attr, _val in _attrs.items():
            setattr(_stub, _attr, _val)
        sys.modules[_mod_name] = _stub

from navigator_eventbus.hooks.models import (  # noqa: E402
    HookEvent,
    HookType,
    TransitionAction,
    TransitionActionType,
)


def _make_specialist(transition_actions=None):
    """Create a minimal JiraSpecialist for testing dispatch logic.

    Uses ``object.__new__`` to bypass the heavy ``__init__`` (Redis, Jira,
    LLM client, Telegram) that is irrelevant to the dispatch tests.

    Args:
        transition_actions: Optional list of :class:`TransitionAction` entries.

    Returns:
        A partially-initialised :class:`JiraSpecialist` instance with only the
        attributes needed by the dispatch and action-handler methods.
    """
    from parrot.bots.jira_specialist import JiraSpecialist
    obj = object.__new__(JiraSpecialist)
    obj._transition_actions = transition_actions or []
    obj._wrapper = None
    obj._agent_dispatcher = None
    obj.logger = MagicMock()
    return obj


@pytest.fixture
def status_change_payload():
    """Standard transition payload: Open → In Progress for NAV-1234."""
    return {
        "issue_key": "NAV-1234",
        "summary": "Fix login timeout",
        "from_status": "Open",
        "to_status": "In Progress",
        "project_key": "NAV",
        "assignee": {"display_name": "Developer"},
    }


# ---------------------------------------------------------------------------
# TestAgentDispatcherSlot — _agent_dispatcher slot + set_agent_dispatcher()
# ---------------------------------------------------------------------------


class TestAgentDispatcherSlot:
    """Tests for the AgentDispatcher protocol + dispatcher slot (TASK-1678)."""

    def test_agent_dispatcher_defaults_to_none(self):
        """A fresh specialist starts with _agent_dispatcher is None."""
        specialist = _make_specialist()
        assert specialist._agent_dispatcher is None

    def test_set_agent_dispatcher_sets_attr(self):
        """set_agent_dispatcher() stores the callable on _agent_dispatcher."""
        specialist = _make_specialist()

        async def disp(agent_name, task, *, user_id=None, session_id=None):
            return None

        assert specialist._agent_dispatcher is None
        specialist.set_agent_dispatcher(disp)
        assert specialist._agent_dispatcher is disp

    def test_execute_agent_satisfies_protocol(self):
        """A callable matching AutonomousOrchestrator.execute_agent's shape
        is accepted as an AgentDispatcher (structural / duck-typed check).
        """
        from parrot.bots._types import AgentDispatcher

        class _Orch:
            async def execute_agent(self, agent_name, task, *, method_name=None,
                                    user_id=None, session_id=None, **kw):
                return {"ok": True}

        disp: AgentDispatcher = _Orch().execute_agent
        assert callable(disp)


# ---------------------------------------------------------------------------
# TestDispatchTransition — matching / filtering logic
# ---------------------------------------------------------------------------


class TestDispatchTransition:
    """Tests for _dispatch_transition matching logic."""

    @pytest.mark.asyncio
    async def test_exact_match_fires(self, status_change_payload):
        """Action with exact (from, to) match is executed."""
        actions = [
            TransitionAction(
                from_status="Open",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["status"] == "ok"
        assert result["actions_matched"] >= 1

    @pytest.mark.asyncio
    async def test_wildcard_from_matches(self, status_change_payload):
        """Action with from_status='*' matches any source status."""
        actions = [
            TransitionAction(
                from_status="*",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] >= 1

    @pytest.mark.asyncio
    async def test_wildcard_to_matches(self, status_change_payload):
        """Action with to_status='*' matches any target status."""
        actions = [
            TransitionAction(
                from_status="Open",
                to_status="*",
                action_type=TransitionActionType.LOG,
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] >= 1

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self, status_change_payload):
        """Matching is case-insensitive for from_status and to_status."""
        actions = [
            TransitionAction(
                from_status="open",
                to_status="in progress",
                action_type=TransitionActionType.LOG,
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] >= 1

    @pytest.mark.asyncio
    async def test_disabled_action_skipped(self, status_change_payload):
        """Action with enabled=False is not executed."""
        actions = [
            TransitionAction(
                from_status="*",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
                enabled=False,
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] == 0

    @pytest.mark.asyncio
    async def test_project_key_filter_mismatch(self, status_change_payload):
        """Action restricted to a different project_key is not executed."""
        actions = [
            TransitionAction(
                from_status="*",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
                project_key="OTHER",
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] == 0

    @pytest.mark.asyncio
    async def test_project_key_filter_match(self, status_change_payload):
        """Action restricted to the same project_key fires correctly."""
        actions = [
            TransitionAction(
                from_status="*",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
                project_key="NAV",
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] >= 1

    @pytest.mark.asyncio
    async def test_no_actions_configured(self, status_change_payload):
        """With an empty registry, status is ok and zero actions matched."""
        specialist = _make_specialist([])
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["status"] == "ok"
        assert result["actions_matched"] == 0

    @pytest.mark.asyncio
    async def test_result_keys_present(self, status_change_payload):
        """Result dict always contains the standard keys."""
        specialist = _make_specialist([])
        result = await specialist._dispatch_transition(status_change_payload)
        assert "status" in result
        assert "issue_key" in result
        assert "from_status" in result
        assert "to_status" in result
        assert "actions_matched" in result
        assert "results" in result

    @pytest.mark.asyncio
    async def test_log_transition_always_called(self, status_change_payload):
        """_action_log_transition is called for every dispatch, even with empty registry."""
        specialist = _make_specialist([])
        await specialist._dispatch_transition(status_change_payload)
        # The logger.info should have been called for the default log_transition
        specialist.logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_status_mismatch_not_matched(self, status_change_payload):
        """Action with non-matching to_status does not fire."""
        actions = [
            TransitionAction(
                from_status="*",
                to_status="Done",
                action_type=TransitionActionType.LOG,
            )
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        # payload has to_status="In Progress", action expects "Done"
        assert result["actions_matched"] == 0


# ---------------------------------------------------------------------------
# TestActionNotifyChannel
# ---------------------------------------------------------------------------


class TestActionNotifyChannel:
    """Tests for the _action_notify_channel built-in handler."""

    @pytest.mark.asyncio
    async def test_sends_telegram_message(self, status_change_payload):
        """Sends a message via self._wrapper.bot.send_message when wrapper present."""
        specialist = _make_specialist()
        mock_bot = AsyncMock()
        specialist._wrapper = MagicMock(bot=mock_bot)
        result = await specialist._action_notify_channel(
            status_change_payload,
            {"channel_id": "-100123"},
        )
        assert result["status"] == "ok"
        assert result["channel_id"] == "-100123"
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_custom_template(self, status_change_payload):
        """Formats the message using the provided template."""
        specialist = _make_specialist()
        mock_bot = AsyncMock()
        specialist._wrapper = MagicMock(bot=mock_bot)
        await specialist._action_notify_channel(
            status_change_payload,
            {
                "channel_id": "-100123",
                "template": "Ticket {issue_key} moved to {to_status}",
            },
        )
        call_kwargs = mock_bot.send_message.call_args
        # Ensure the custom template was used (NAV-1234 should appear in the call)
        assert "NAV-1234" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_skips_when_no_wrapper(self, status_change_payload):
        """Returns status='skipped' when _wrapper is None."""
        specialist = _make_specialist()
        specialist._wrapper = None
        result = await specialist._action_notify_channel(
            status_change_payload,
            {"channel_id": "-100123"},
        )
        assert result["status"] == "skipped"
        assert "Telegram" in result.get("reason", "")

    @pytest.mark.asyncio
    async def test_skips_when_no_channel_id(self, status_change_payload):
        """Returns status='skipped' when channel_id is not in config."""
        specialist = _make_specialist()
        result = await specialist._action_notify_channel(
            status_change_payload, {},
        )
        assert result["status"] == "skipped"
        assert "channel_id" in result.get("reason", "")

    @pytest.mark.asyncio
    async def test_skips_when_wrapper_has_no_bot(self, status_change_payload):
        """Returns status='skipped' when wrapper exists but has no bot attribute."""
        specialist = _make_specialist()
        specialist._wrapper = MagicMock(bot=None)
        result = await specialist._action_notify_channel(
            status_change_payload,
            {"channel_id": "-100123"},
        )
        assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# TestActionTriggerAgent
# ---------------------------------------------------------------------------


class _RecordingDispatcher:
    """Fake AgentDispatcher that records every call it receives."""

    def __init__(self):
        self.calls = []

    async def __call__(self, agent_name, task, *, user_id=None, session_id=None):
        self.calls.append((agent_name, task, user_id, session_id))
        return {"ok": True}


class TestActionTriggerAgent:
    """Tests for the _action_trigger_agent built-in handler."""

    @pytest.mark.asyncio
    async def test_logs_trigger_intent(self, status_change_payload):
        """With no dispatcher wired, logs intent (WARNING) and returns
        status='skipped' — does NOT raise (backward-compatible degrade)."""
        specialist = _make_specialist()
        result = await specialist._action_trigger_agent(
            status_change_payload,
            {"agent_id": "deploy_bot", "task_template": "Deploy {issue_key}"},
        )
        assert result["status"] == "skipped"
        assert result["agent_id"] == "deploy_bot"
        specialist.logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_formats_task_from_template(self, status_change_payload):
        """Formats the task string using the task_template placeholders."""
        specialist = _make_specialist()
        result = await specialist._action_trigger_agent(
            status_change_payload,
            {
                "agent_id": "deploy_bot",
                "task_template": "Handle {issue_key} transition to {to_status}",
            },
        )
        assert "NAV-1234" in result["task"]
        assert "In Progress" in result["task"]

    @pytest.mark.asyncio
    async def test_no_template_produces_default_task(self, status_change_payload):
        """Without a task_template, a default task string is generated."""
        specialist = _make_specialist()
        result = await specialist._action_trigger_agent(
            status_change_payload,
            {"agent_id": "my_agent"},
        )
        assert result["status"] == "skipped"
        assert result["task"] != ""

    @pytest.mark.asyncio
    async def test_no_agent_id_skips(self, status_change_payload):
        """Missing agent_id returns status='skipped' (unchanged guard)."""
        specialist = _make_specialist()
        result = await specialist._action_trigger_agent(status_change_payload, {})
        assert result["status"] == "skipped"
        assert "agent_id" in result.get("reason", "")

    @pytest.mark.asyncio
    async def test_dispatches_to_wired_dispatcher(self, status_change_payload):
        """With a dispatcher set, _action_trigger_agent awaits it exactly once
        with the resolved agent_id and rendered task; returns status='dispatched'."""
        specialist = _make_specialist()
        disp = _RecordingDispatcher()
        specialist.set_agent_dispatcher(disp)
        result = await specialist._action_trigger_agent(
            status_change_payload,
            {"agent_id": "deploy_bot", "task_template": "Deploy {issue_key}"},
        )
        assert result["status"] == "dispatched"
        assert len(disp.calls) == 1
        assert disp.calls[0][0] == "deploy_bot"
        assert disp.calls[0][1] == "Deploy NAV-1234"

    @pytest.mark.asyncio
    async def test_skips_when_no_dispatcher(self, status_change_payload):
        """With no dispatcher, returns status='skipped' and does NOT raise."""
        specialist = _make_specialist()
        result = await specialist._action_trigger_agent(
            status_change_payload, {"agent_id": "deploy_bot"}
        )
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_dispatcher_error_is_caught(self, status_change_payload):
        """A dispatcher exception is caught and surfaced as status='error';
        it must not raise out of the action handler."""
        specialist = _make_specialist()

        async def boom(*args, **kwargs):
            raise RuntimeError("nope")

        specialist.set_agent_dispatcher(boom)
        result = await specialist._action_trigger_agent(
            status_change_payload, {"agent_id": "deploy_bot"}
        )
        assert result["status"] == "error"
        assert "nope" in result["error"]

    @pytest.mark.asyncio
    async def test_task_template_rendered_before_dispatch(self, status_change_payload):
        """task_template placeholders are filled in the task passed to the
        dispatcher (not the raw template)."""
        specialist = _make_specialist()
        disp = _RecordingDispatcher()
        specialist.set_agent_dispatcher(disp)
        await specialist._action_trigger_agent(
            status_change_payload,
            {
                "agent_id": "deploy_bot",
                "task_template": (
                    "{issue_key}: {from_status} -> {to_status} "
                    "({summary}) assignee={assignee}"
                ),
            },
        )
        assert len(disp.calls) == 1
        rendered_task = disp.calls[0][1]
        assert rendered_task == (
            "NAV-1234: Open -> In Progress (Fix login timeout) assignee=Developer"
        )


# ---------------------------------------------------------------------------
# TestActionLogTransition
# ---------------------------------------------------------------------------


class TestActionLogTransition:
    """Tests for the _action_log_transition built-in handler."""

    def test_logs_at_info_by_default(self, status_change_payload):
        """Uses self.logger.info when no level is specified."""
        specialist = _make_specialist()
        result = specialist._action_log_transition(status_change_payload, {})
        assert result["status"] == "logged"
        assert result["level"] == "info"
        specialist.logger.info.assert_called()

    def test_logs_at_custom_level(self, status_change_payload):
        """Uses self.logger.warning when level='warning' is configured."""
        specialist = _make_specialist()
        result = specialist._action_log_transition(
            status_change_payload, {"level": "warning"}
        )
        assert result["level"] == "warning"
        specialist.logger.warning.assert_called()

    def test_logs_at_debug_level(self, status_change_payload):
        """Uses self.logger.debug when level='debug' is configured."""
        specialist = _make_specialist()
        specialist._action_log_transition(
            status_change_payload, {"level": "debug"}
        )
        specialist.logger.debug.assert_called()

    def test_returns_logged_status(self, status_change_payload):
        """Always returns a dict with status='logged' and the effective level."""
        specialist = _make_specialist()
        result = specialist._action_log_transition(status_change_payload, {})
        assert result["status"] == "logged"
        assert "level" in result


# ---------------------------------------------------------------------------
# TestHandleHookEventRouting
# ---------------------------------------------------------------------------


class TestHandleHookEventRouting:
    """Tests for handle_hook_event routing to _dispatch_transition."""

    @pytest.mark.asyncio
    async def test_transitioned_event_dispatched(self, status_change_payload):
        """jira.transitioned events reach _dispatch_transition and return ok."""
        specialist = _make_specialist()
        event = HookEvent(
            hook_id="test-hook",
            hook_type=HookType.JIRA_WEBHOOK,
            event_type="jira.transitioned",
            payload=status_change_payload,
        )
        result = await specialist.handle_hook_event(event)
        assert result is not None
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_unknown_event_still_returns_none(self):
        """Unrecognised event types are ignored and return None."""
        specialist = _make_specialist()
        event = HookEvent(
            hook_id="test-hook",
            hook_type=HookType.JIRA_WEBHOOK,
            event_type="jira.unknown_type",
            payload={},
        )
        result = await specialist.handle_hook_event(event)
        assert result is None

    @pytest.mark.asyncio
    async def test_existing_created_event_routed(self):
        """jira.created still routes to handle_jira_ticket_created (no regression)."""
        specialist = _make_specialist()
        # Patch the handler to avoid heavy logic
        specialist.handle_jira_ticket_created = AsyncMock(
            return_value={"status": "ok"}
        )
        event = HookEvent(
            hook_id="test-hook",
            hook_type=HookType.JIRA_WEBHOOK,
            event_type="jira.created",
            payload={"issue_key": "NAV-1"},
        )
        await specialist.handle_hook_event(event)
        specialist.handle_jira_ticket_created.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_assigned_event_routed(self):
        """jira.assigned still routes to handle_jira_assignment (no regression)."""
        specialist = _make_specialist()
        specialist.handle_jira_assignment = AsyncMock(return_value={"status": "ok"})
        event = HookEvent(
            hook_id="test-hook",
            hook_type=HookType.JIRA_WEBHOOK,
            event_type="jira.assigned",
            payload={},
        )
        await specialist.handle_hook_event(event)
        specialist.handle_jira_assignment.assert_called_once()

    @pytest.mark.asyncio
    async def test_existing_ready_for_test_event_routed(self):
        """jira.ready_for_test still routes to handle_ready_for_test (no regression)."""
        specialist = _make_specialist()
        specialist.handle_ready_for_test = AsyncMock(return_value={"status": "ok"})
        event = HookEvent(
            hook_id="test-hook",
            hook_type=HookType.JIRA_WEBHOOK,
            event_type="jira.ready_for_test",
            payload={},
        )
        await specialist.handle_hook_event(event)
        specialist.handle_ready_for_test.assert_called_once()


# ---------------------------------------------------------------------------
# TestIntegration — end-to-end scenarios
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration tests: webhook payload → classify → dispatch → handler."""

    @pytest.mark.asyncio
    async def test_transition_with_no_matching_actions(self, status_change_payload):
        """With an empty registry, dispatch logs and returns gracefully."""
        specialist = _make_specialist([])
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["status"] == "ok"
        assert result["actions_matched"] == 0
        specialist.logger.info.assert_called()  # log_transition always fires

    @pytest.mark.asyncio
    async def test_multiple_actions_all_fire(self, status_change_payload):
        """Multiple matching actions are all executed and counted."""
        actions = [
            TransitionAction(
                from_status="*",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
            ),
            TransitionAction(
                from_status="Open",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
            ),
        ]
        specialist = _make_specialist(actions)
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] == 2
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_notify_and_log_actions_combined(self, status_change_payload):
        """A NOTIFY_CHANNEL and a LOG action on the same transition both fire."""
        actions = [
            TransitionAction(
                from_status="*",
                to_status="In Progress",
                action_type=TransitionActionType.LOG,
                action_config={"level": "info"},
            ),
            TransitionAction(
                from_status="*",
                to_status="In Progress",
                action_type=TransitionActionType.NOTIFY_CHANNEL,
                action_config={"channel_id": "-100123"},
            ),
        ]
        specialist = _make_specialist(actions)
        # No wrapper — notify will skip, log will fire
        result = await specialist._dispatch_transition(status_change_payload)
        assert result["actions_matched"] == 2
        notify_result = next(
            (r for r in result["results"] if r.get("status") == "skipped"), None
        )
        assert notify_result is not None  # notify skipped (no wrapper)

    @pytest.mark.asyncio
    async def test_transition_triggers_agent_end_to_end(self, status_change_payload):
        """A jira.transitioned payload with a TRIGGER_AGENT action, dispatcher
        wired to a stub orchestrator, drives handle_hook_event →
        _dispatch_transition → _action_trigger_agent → the stub dispatcher
        records exactly one execute_agent-shaped call."""
        actions = [
            TransitionAction(
                from_status="*",
                to_status="Ready For Deploy",
                action_type=TransitionActionType.TRIGGER_AGENT,
                action_config={
                    "agent_id": "deploy_bot",
                    "task_template": "Deploy {issue_key}",
                },
            )
        ]
        specialist = _make_specialist(actions)
        disp = _RecordingDispatcher()
        specialist.set_agent_dispatcher(disp)

        payload = dict(status_change_payload)
        payload["to_status"] = "Ready For Deploy"
        event = HookEvent(
            hook_id="test-hook",
            hook_type=HookType.JIRA_WEBHOOK,
            event_type="jira.transitioned",
            payload=payload,
        )
        result = await specialist.handle_hook_event(event)

        assert result["actions_matched"] == 1
        assert len(disp.calls) == 1
        assert disp.calls[0][0] == "deploy_bot"
        assert disp.calls[0][1] == "Deploy NAV-1234"
        assert result["results"][0]["status"] == "dispatched"


# ---------------------------------------------------------------------------
# TestActionCallHandler
# ---------------------------------------------------------------------------


class TestActionCallHandler:
    """Tests for the _action_call_handler built-in handler."""

    @pytest.mark.asyncio
    async def test_missing_method_name_returns_skipped(self, status_change_payload):
        """Returns status='skipped' when method_name is not in action_config."""
        specialist = _make_specialist()
        result = await specialist._action_call_handler(status_change_payload, {})
        assert result["status"] == "skipped"
        assert "method_name" in result.get("reason", "")

    @pytest.mark.asyncio
    async def test_method_not_found_returns_error(self, status_change_payload):
        """Returns status='error' when the named method does not exist on the instance."""
        specialist = _make_specialist()
        result = await specialist._action_call_handler(
            status_change_payload,
            {"method_name": "nonexistent_handler_xyz"},
        )
        assert result["status"] == "skipped"
        assert "nonexistent_handler_xyz" in result.get("reason", "")

    @pytest.mark.asyncio
    async def test_sync_handler_invoked(self, status_change_payload):
        """Synchronous handler is called and its return value is returned."""
        specialist = _make_specialist()
        expected = {"status": "ok", "handled_by": "sync_handler"}
        specialist.my_sync_handler = MagicMock(return_value=expected)
        result = await specialist._action_call_handler(
            status_change_payload,
            {"method_name": "my_sync_handler"},
        )
        assert result == expected
        specialist.my_sync_handler.assert_called_once_with(
            status_change_payload, {"method_name": "my_sync_handler"}
        )

    @pytest.mark.asyncio
    async def test_async_handler_invoked(self, status_change_payload):
        """Async (coroutine) handler is awaited and its return value is returned."""
        specialist = _make_specialist()
        expected = {"status": "ok", "handled_by": "async_handler"}
        specialist.my_async_handler = AsyncMock(return_value=expected)
        result = await specialist._action_call_handler(
            status_change_payload,
            {"method_name": "my_async_handler"},
        )
        assert result == expected
        specialist.my_async_handler.assert_called_once_with(
            status_change_payload, {"method_name": "my_async_handler"}
        )


# ---------------------------------------------------------------------------
# TestTransitionActionModel
# ---------------------------------------------------------------------------


class TestTransitionActionModel:
    """Tests for TransitionAction Pydantic model validation."""

    def test_both_wildcards_rejected(self):
        """from_status='*' AND to_status='*' raises ValidationError."""
        import pydantic

        with pytest.raises(pydantic.ValidationError, match="non-wildcard"):
            TransitionAction(
                from_status="*",
                to_status="*",
                action_type=TransitionActionType.LOG,
            )

    def test_single_wildcard_ok(self):
        """from_status='*' with a concrete to_status is valid."""
        action = TransitionAction(
            from_status="*",
            to_status="Done",
            action_type=TransitionActionType.LOG,
        )
        assert action.from_status == "*"
        assert action.to_status == "Done"
