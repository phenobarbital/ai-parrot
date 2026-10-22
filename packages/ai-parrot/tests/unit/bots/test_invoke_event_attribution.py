"""FEAT-710 TASK-4549 — invoke events carry tenant/user/session."""

from typing import Any

import pytest

from parrot.core.events.lifecycle.events import AfterInvokeEvent, InvokeFailedEvent

_ASK_KWARGS = {
    "use_conversation_history": False,
    "use_tools": False,
    "use_vector_context": False,
}


@pytest.mark.asyncio
async def test_after_invoke_carries_attribution(make_bot: Any) -> None:
    """Successful invoke events carry the call's attribution values."""
    bot = make_bot()
    await bot.configure()
    events: list[AfterInvokeEvent] = []

    async def capture(event: AfterInvokeEvent) -> None:
        events.append(event)

    bot.events.subscribe(AfterInvokeEvent, capture)

    await bot.ask("hello", user_id="u", session_id="s", tenant="t", **_ASK_KWARGS)

    assert len(events) == 1
    assert events[0].tenant == "t"
    assert events[0].user_id == "u"
    assert events[0].session_id == "s"


@pytest.mark.asyncio
async def test_invoke_failed_carries_attribution(make_bot: Any) -> None:
    """Failed invoke events carry the call's attribution values."""
    bot = make_bot()
    events: list[InvokeFailedEvent] = []

    async def capture(event: InvokeFailedEvent) -> None:
        events.append(event)

    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("invoke failed")

    bot.events.subscribe(InvokeFailedEvent, capture)
    bot._run_input_pipeline = fail

    with pytest.raises(RuntimeError, match="invoke failed"):
        await bot.ask("hello", user_id="u", session_id="s", tenant="t", **_ASK_KWARGS)

    assert len(events) == 1
    assert events[0].tenant == "t"
    assert events[0].user_id == "u"
    assert events[0].session_id == "s"
