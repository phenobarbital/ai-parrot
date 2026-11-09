"""Regression coverage for Slack queued commands and bounded acknowledgement."""

import asyncio
import logging
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.core.queued import (
    PreparedCommand,
    QueuedCommandService,
    discover_queued_commands,
    queued_command,
)
from parrot.integrations.slack.commands import SlackCommandRouter
from parrot.integrations.slack.commands.queued_commands import SlackQueuedCommands
from parrot.integrations.slack.wrapper import SlackAgentWrapper
from parrot.jobs import JobManager


class _Agent:
    """Expose one deterministic queued command for Slack adapter tests."""

    @queued_command("pr_review", "Review a pull request", aliases=("pr-review",))
    async def review(self, raw: str) -> str:
        """Return the supplied arguments as a stable completion payload."""

        return f"reviewed {raw}"


def _wrapper(agent: Any = None) -> Any:
    """Build the wrapper surface consumed by ``SlackQueuedCommands``."""

    wrapper = SimpleNamespace(
        agent=agent or _Agent(),
        config=SimpleNamespace(name="test-bot"),
        post_message=AsyncMock(return_value="1.2"),
        _build_blocks=MagicMock(return_value=[{"type": "section"}]),
    )
    return wrapper


def _adapter(wrapper: Any = None, *, manager: JobManager | None = None) -> tuple[Any, SlackQueuedCommands, Any]:
    """Create a registered adapter using an in-memory manager by default."""

    wrapper = wrapper or _wrapper()
    holder = SlackQueuedCommands(wrapper, discover_queued_commands(wrapper.agent))
    holder.service = QueuedCommandService(
        owner="slack:test-bot",
        job_manager=manager or JobManager(id="slack-test"),
        use_redis=False,
        prepare_timeout=2.0,
        admission_timeout=2.0,
    )
    router = SlackCommandRouter()
    holder.register(router)
    return wrapper, holder, router


def _payload(text: str = "acme/widgets#12") -> dict[str, str]:
    """Return a complete Slack router payload."""

    return {
        "team_id": "T1",
        "user_id": "U123",
        "channel_id": "C456",
        "text": text,
        "response_url": "https://example.invalid/response",
    }


@pytest.mark.asyncio
async def test_slack_handler_returns_ephemeral_ack() -> None:
    """Dispatch canonical and alias names with an ephemeral acknowledgement."""

    wrapper, holder, router = _adapter()

    result = await router.dispatch("pr_review", _payload())

    assert result is not None
    assert result["response_type"] == "ephemeral"
    assert result["text"].startswith("⏳ Accepted — job `")
    assert {
        "pr_review",
        "pr-review",
        "jobs",
        "job_status",
        "job_cancel",
    }.issubset(router.registered_commands)
    assert "/pr_review — Review a pull request" in SlackAgentWrapper._help_text(
        SimpleNamespace(_queued_commands=holder)
    )
    await holder.shutdown()
    wrapper.post_message.assert_awaited()


@pytest.mark.asyncio
async def test_slack_delivery_posts_to_channel_with_mention() -> None:
    """Post parsed completion blocks to the captured channel and mention the requester."""

    wrapper, holder, router = _adapter()
    delivered = asyncio.Event()

    async def post_message(*args: Any, **kwargs: Any) -> str:
        delivered.set()
        return "1.2"

    wrapper.post_message.side_effect = post_message
    result = await router.dispatch("pr-review", _payload("acme/widgets#12"))
    await asyncio.wait_for(delivered.wait(), timeout=1.0)

    assert result is not None
    assert wrapper.post_message.await_args.args == ("C456",)
    text = wrapper.post_message.await_args.kwargs["text"]
    assert text.startswith("<@U123> ✅ Job `")
    assert text.endswith("reviewed acme/widgets#12")
    assert wrapper.post_message.await_args.kwargs["blocks"] == [{"type": "section"}]
    await holder.shutdown()


@pytest.mark.asyncio
async def test_slack_stop_shuts_down_queued() -> None:
    """Shut down queued work before cancelling ordinary wrapper background tasks."""

    order: list[str] = []
    cancelled = asyncio.Event()

    async def background() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            order.append("background")
            cancelled.set()

    task = asyncio.create_task(background())
    await asyncio.sleep(0)
    queued = SimpleNamespace()

    async def shutdown() -> None:
        assert not task.done()
        order.append("queued")

    queued.shutdown = shutdown
    wrapper = SlackAgentWrapper.__new__(SlackAgentWrapper)
    wrapper._queued_commands = queued
    wrapper._knowledge_upload = None
    wrapper._dedup = SimpleNamespace(stop=AsyncMock())
    wrapper._background_tasks = {task}
    wrapper.config = SimpleNamespace(name="test-bot")
    wrapper.logger = logging.getLogger("test.slack.queued")

    await wrapper.stop()

    await asyncio.wait_for(cancelled.wait(), timeout=1.0)
    assert order == ["queued", "background"]
    assert wrapper._background_tasks == set()


@pytest.mark.asyncio
async def test_slack_ack_with_slow_or_unavailable_redis() -> None:
    """Keep repeated router acknowledgements local and reject timed-out preparation atomically."""

    class SlowStore:
        async def connect(self) -> None:
            await asyncio.Event().wait()

        async def save(self, job: Any) -> None:
            del job
            await asyncio.Event().wait()

        async def close(self) -> None:
            return None

    manager = JobManager(id="slow-slack", store=SlowStore(), persistence_timeout=0.01)
    wrapper, holder, router = _adapter(manager=manager)
    started = time.monotonic()
    first = await router.dispatch("pr_review", _payload("one"))
    second = await router.dispatch("pr_review", _payload("two"))
    elapsed = time.monotonic() - started

    assert elapsed < 3.0
    assert first is not None and first["text"].startswith("⏳ Accepted")
    assert second is not None and second["text"].startswith("⏳ Accepted")
    deadline = asyncio.get_running_loop().time() + 1.0
    while wrapper.post_message.await_count < 2 and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.001)
    assert wrapper.post_message.await_count == 2
    await holder.shutdown()

    class SlowPrepareAgent:
        async def prepare(self, raw: str) -> PreparedCommand:
            del raw
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        @queued_command("slow", "Slow preparation", prepare="prepare")
        async def slow(self) -> str:
            return "unreachable"

    timeout_wrapper = _wrapper(SlowPrepareAgent())
    timeout_holder = SlackQueuedCommands(
        timeout_wrapper,
        discover_queued_commands(timeout_wrapper.agent),
    )
    timeout_holder.service = QueuedCommandService(
        owner="slack:timeout",
        job_manager=JobManager(id="timeout"),
        use_redis=False,
        prepare_timeout=0.01,
        admission_timeout=0.05,
    )
    timeout_router = SlackCommandRouter()
    timeout_holder.register(timeout_router)

    rejected = await timeout_router.dispatch("slow", _payload())

    assert rejected == {
        "response_type": "ephemeral",
        "text": "Command preparation timed out; please try again.",
    }
    assert timeout_holder.service.manager is not None
    assert timeout_holder.service.manager.jobs == {}
    assert timeout_holder.service._reservations == {}
    await timeout_holder.shutdown()
