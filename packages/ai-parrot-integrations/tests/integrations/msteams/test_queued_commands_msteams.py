"""Regression coverage for Teams queued commands and proactive delivery."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from botbuilder.core import TurnContext

from parrot.integrations.core.queued import JobNotice, SubmitOutcome, queued_command
from parrot.integrations.manager import IntegrationBotManager
from parrot.integrations.msteams.commands import MSTeamsCommandRouter
from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler
from parrot.integrations.msteams.commands.queued_commands import TeamsQueuedCommands


class _Agent:
    """Expose one queued method for adapter and generic-command tests."""

    def __init__(self) -> None:
        """Record whether an inline route invoked the queued method."""

        self.calls = 0

    @queued_command("review", "Review an item", aliases=("review-item",))
    async def review(self, value: str = "") -> str:
        """Return a deterministic queued result."""

        self.calls += 1
        return value


class _Service:
    """Capture the queued command callback without scheduling background work."""

    def __init__(self) -> None:
        self.submissions: list[tuple[Any, str, Any, Any]] = []

    async def submit(self, command: Any, args: str, requester: Any, deliver: Any) -> SubmitOutcome:
        """Record admission and return an immediate acknowledgement."""

        self.submissions.append((command, args, requester, deliver))
        return SubmitOutcome(status="accepted", job_id="job-1", label="review", message="")

    async def stop(self) -> None:
        """Satisfy the adapter shutdown protocol."""

        return None


class _Adapter:
    """Run a proactive callback and retain its captured destination."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, str]] = []
        self.context = SimpleNamespace(activity=SimpleNamespace())

    async def continue_conversation(self, reference: Any, callback: Any, client_id: str) -> None:
        """Record proactive delivery and execute its callback."""

        self.calls.append((reference, client_id))
        await callback(self.context)


def _turn_context(args: str = "") -> Any:
    """Build the narrow activity surface consumed by the Teams adapter."""

    return SimpleNamespace(
        activity=SimpleNamespace(
            from_property=SimpleNamespace(id="user-1", name="Ada"),
            conversation=SimpleNamespace(id="conversation-1"),
        ),
        turn_state={"msteams.command_args": args},
    )


def _wrapper(client_id: str = "app-1") -> Any:
    """Build the wrapper surface consumed by the Teams queued adapter."""

    wrapper = SimpleNamespace(
        agent=_Agent(),
        config=SimpleNamespace(name="test-bot", client_id=client_id),
        adapter=_Adapter(),
    )
    wrapper.send_text = AsyncMock()
    wrapper._send_parsed_response = AsyncMock()
    return wrapper


async def test_teams_submit_and_proactive_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    """A command acknowledges immediately and proactively delivers to its captured conversation."""

    reference = object()
    monkeypatch.setattr(TurnContext, "get_conversation_reference", staticmethod(lambda _activity: reference))
    wrapper = _wrapper()
    from parrot.integrations.core.queued import discover_queued_commands

    adapter = TeamsQueuedCommands(wrapper, discover_queued_commands(wrapper.agent))
    service = _Service()
    adapter.service = service  # type: ignore[assignment]
    router = MSTeamsCommandRouter()
    adapter.register(router)
    assert set(router.registered_commands) == {"review", "review-item", "jobs", "job_status", "job_cancel"}

    context = _turn_context("42")
    await router._handlers["review"](context)

    wrapper.send_text.assert_awaited_once_with(
        "⏳ Accepted — job `job-1`: review.\nI'll post the result here. Track it with /job_status job-1", context
    )
    _command, args, requester, deliver = service.submissions[0]
    assert args == "42"
    assert requester.actor == "msteams:user-1"
    await deliver(JobNotice(job_id="job-1", command="review", label="review", status="completed", result="done"))

    assert wrapper.adapter.calls == [(reference, "app-1")]
    parsed = wrapper._send_parsed_response.await_args.args[0]
    assert parsed.text == "✅ Job `job-1` finished in 0s — review\n\ndone"


async def test_teams_without_client_id_does_not_submit() -> None:
    """A missing application id is rejected before a queued job is submitted."""

    wrapper = _wrapper(client_id="")
    from parrot.integrations.core.queued import discover_queued_commands

    adapter = TeamsQueuedCommands(wrapper, discover_queued_commands(wrapper.agent))
    service = _Service()
    adapter.service = service  # type: ignore[assignment]
    router = MSTeamsCommandRouter()
    adapter.register(router)
    context = _turn_context()

    await router._handlers["review"](context)

    assert service.submissions == []
    wrapper.send_text.assert_awaited_once_with("Queued commands require a configured client_id.", context)


async def test_teams_function_and_call_refuse_queued_method() -> None:
    """Generic Teams invokers refuse queued methods without calling them inline."""

    agent = _Agent()
    wrapper = SimpleNamespace(
        send_text=AsyncMock(),
        send_typing=AsyncMock(),
        _remove_mentions=lambda _activity, text: text,
    )
    handler = AgentCommandHandler(agent, wrapper)

    await handler.handle_function(SimpleNamespace(activity=SimpleNamespace(text="/function review")))
    await handler.handle_call(SimpleNamespace(activity=SimpleNamespace(text="/call review")))

    assert agent.calls == 0
    assert wrapper.send_text.await_args_list[0].args[0] == "Use /review — it runs in the background."
    assert wrapper.send_text.await_args_list[1].args[0] == "Use /review — it runs in the background."


async def test_teams_manager_shutdown_closes_queued() -> None:
    """Manager shutdown closes queued jobs for every Teams wrapper before other resources."""

    bot_manager = MagicMock()
    bot_manager.get_app.return_value = MagicMock()
    manager = IntegrationBotManager(bot_manager=bot_manager)
    wrapper = MagicMock()
    wrapper.close_queued_commands = AsyncMock()
    wrapper.close_formdesigner_client = AsyncMock()
    wrapper.close_voice_transcriber = AsyncMock()
    manager.msteams_bots["teams"] = wrapper

    await manager.shutdown()

    wrapper.close_queued_commands.assert_awaited_once()
