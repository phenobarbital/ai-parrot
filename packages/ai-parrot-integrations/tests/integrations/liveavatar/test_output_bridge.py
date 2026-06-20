"""Unit tests for the OutputBridge (FEAT-243, TASK-002).

The bridge is exercised with a fake socket manager so the test needs neither a
live WebSocket nor the ai-parrot-server package.
"""

import pytest

from parrot.integrations.liveavatar.output_bridge import OutputBridge
from parrot.integrations.liveavatar.models import StructuredOutputMessage


class FakeSocketManager:
    """Records broadcast_to_channel calls (mirrors UserSocketManager API)."""

    def __init__(self):
        self.calls = []

    async def broadcast_to_channel(self, channel, message, exclude_ws=None):
        self.calls.append((channel, message, exclude_ws))


@pytest.mark.asyncio
async def test_output_bridge_contract():
    """publish() broadcasts the P4 schema on a channel keyed by session_id."""
    sm = FakeSocketManager()
    bridge = OutputBridge(sm)
    msg = StructuredOutputMessage(type="chart", session_id="s1", payload={"k": "v"})

    await bridge.publish(msg)

    assert len(sm.calls) == 1
    channel, sent, exclude_ws = sm.calls[0]
    assert channel == "s1"  # keyed by session_id
    assert sent["type"] == "chart"
    assert sent["session_id"] == "s1"
    assert sent["payload"] == {"k": "v"}
    assert sent["turn_id"] is None
    assert exclude_ws is None


@pytest.mark.asyncio
async def test_output_bridge_preserves_turn_id():
    """turn_id is carried through to the broadcast payload."""
    sm = FakeSocketManager()
    bridge = OutputBridge(sm)
    msg = StructuredOutputMessage(
        type="canvas", session_id="s2", payload={"node": 1}, turn_id="t-9"
    )

    await bridge.publish(msg)

    _, sent, _ = sm.calls[0]
    assert sent["turn_id"] == "t-9"


@pytest.mark.asyncio
async def test_output_bridge_publishes_each_message():
    """Each publish() emits exactly one broadcast on its own channel."""
    sm = FakeSocketManager()
    bridge = OutputBridge(sm)

    await bridge.publish(
        StructuredOutputMessage(type="data", session_id="a", payload={})
    )
    await bridge.publish(
        StructuredOutputMessage(type="tool_call", session_id="b", payload={})
    )

    assert [c[0] for c in sm.calls] == ["a", "b"]
