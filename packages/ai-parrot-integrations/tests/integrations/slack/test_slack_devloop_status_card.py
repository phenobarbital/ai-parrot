"""Status card debounce tests (TASK-3209)."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.devloop.models import Requester, RunRecord
from parrot.integrations.slack.devloop.blocks import status_card_blocks
from parrot.integrations.slack.devloop.transport import SlackDevLoopTransport

_REQ = Requester(transport="slack", tenant_id="T1", user_id="U1")


def _record(**overrides) -> RunRecord:
    payload = dict(
        run_id="run-abcd1234",
        kind="feature",
        title="Token budget",
        requester=_REQ,
        channel_id="C1",
        thread_ts="1234.5678",
        phase="running",
        started_at=time.time(),
    )
    payload.update(overrides)
    return RunRecord(**payload)


def test_status_card_blocks_glyphs_and_order():
    """completed/running/idle/failed/skipped map to the five glyphs, known nodes first in graph order."""
    nodes = {
        "qa": {"status": "idle"},
        "ideation": {"status": "completed"},
        "planner": {"status": "running"},
        "custom_node": {"status": "failed", "error": "boom" * 100},
    }
    record = _record()
    blocks = status_card_blocks(record, nodes)
    text = blocks[0]["text"]["text"]

    # Known nodes render in graph order (ideation, planner, qa), unknown last.
    assert text.index("`ideation`") < text.index("`planner`") < text.index("`qa`") < text.index("`custom_node`")
    assert ":white_check_mark: `ideation`" in text
    assert ":arrows_counterclockwise: `planner`" in text
    assert ":white_circle: `qa`" in text
    assert ":x: `custom_node`" in text
    # Error text truncated to 120 chars — the full 400-char error never appears.
    assert "boom" * 100 not in text
    custom_node_line = next(line for line in text.splitlines() if "custom_node" in line)
    assert len(custom_node_line) < len("boom" * 100)


@pytest.mark.asyncio
async def test_status_card_debounce():
    """10 node events within a short window produce exactly ONE chat.update (after the first create)."""
    wrapper = MagicMock()
    wrapper.config = MagicMock()
    wrapper.config.devloop = MagicMock(status_card=True)
    wrapper.post_message = AsyncMock(return_value="1.0")
    wrapper.update_message = AsyncMock(return_value=True)

    transport = SlackDevLoopTransport(wrapper)
    transport.status_debounce_seconds = 0.05
    record = _record()

    # First event: schedules a debounced flush (2s trailing edge in production);
    # nothing is posted synchronously.
    await transport.update_status(record, {"nodes": {"ideation": {"status": "running"}}})
    wrapper.post_message.assert_not_called()
    await asyncio.sleep(0.2)
    wrapper.post_message.assert_awaited_once()
    assert record.status_message_ts == "1.0"

    # 10 more events within a fresh debounce window: only ONE chat.update fires.
    for _ in range(10):
        await transport.update_status(
            record, {"nodes": {"ideation": {"status": "running"}, "planner": {"status": "idle"}}}
        )

    await asyncio.sleep(0.2)
    assert wrapper.update_message.await_count == 1


@pytest.mark.asyncio
async def test_status_card_terminal_flushes_immediately():
    """A terminal phase flushes without waiting for the debounce window."""
    wrapper = MagicMock()
    wrapper.config = MagicMock()
    wrapper.config.devloop = MagicMock(status_card=True)
    wrapper.post_message = AsyncMock(return_value="1.0")
    wrapper.update_message = AsyncMock(return_value=True)

    transport = SlackDevLoopTransport(wrapper)
    transport.status_debounce_seconds = 60.0  # would never fire on its own within the test
    record = _record(phase="running")

    # Establish the card first (so update_status has a ts to chat.update).
    record.status_message_ts = "1.0"

    record.phase = "completed"
    await transport.update_status(record, {"nodes": {"ideation": {"status": "completed"}}})
    # Flushed immediately despite the huge debounce window — no post_message
    # needed since status_message_ts is already set.
    wrapper.update_message.assert_awaited_once()
    wrapper.post_message.assert_not_called()


@pytest.mark.asyncio
async def test_status_card_disabled_and_never_raises():
    """status_card=False ⇒ no Slack call; a failing wrapper is swallowed."""
    wrapper = MagicMock()
    wrapper.config = MagicMock()
    wrapper.config.devloop = MagicMock(status_card=False)
    wrapper.post_message = AsyncMock(return_value="1.0")

    transport = SlackDevLoopTransport(wrapper)
    record = _record()

    await transport.update_status(record, {"nodes": {"ideation": {"status": "running"}}})
    wrapper.post_message.assert_not_called()

    wrapper.config.devloop.status_card = True
    wrapper.post_message = AsyncMock(side_effect=RuntimeError("boom"))
    record2 = _record(run_id="run-other0001")
    # Must not raise even though the underlying wrapper call fails.
    await transport.update_status(record2, {"nodes": {"ideation": {"status": "running"}}})


@pytest.mark.asyncio
async def test_status_card_missing_devloop_config_is_noop():
    wrapper = MagicMock()
    wrapper.config = MagicMock()
    wrapper.config.devloop = None
    wrapper.post_message = AsyncMock(return_value="1.0")

    transport = SlackDevLoopTransport(wrapper)
    await transport.update_status(_record(), {"nodes": {"ideation": {"status": "running"}}})
    wrapper.post_message.assert_not_called()
