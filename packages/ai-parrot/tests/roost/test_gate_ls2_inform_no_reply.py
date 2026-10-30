"""Gate L-S2 — an inform is absorbed without a reply (FEAT-747 AC-21)."""

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.roost import (
    CarrierKind,
    GatingDispatcher,
    GrantPolicy,
    HandlerRegistry,
    InMemoryBlackboard,
    InProcessCarrier,
    ProtocolEngine,
    RoostAgentConfig,
    RoostEndpoint,
    WriterPolicy,
)
from parrot.roost.messages import RoostMessage


def _endpoint(
    name: str,
    carrier: InProcessCarrier,
    cfg: Optional[RoostAgentConfig],
    *,
    blackboard: Optional[InMemoryBlackboard] = None,
    working_memory: Any = None,
) -> RoostEndpoint:
    """Build one endpoint with a stubbed tool manager and a wake callback that must never fire."""
    eng = ProtocolEngine()
    disp = GatingDispatcher(self_name=name, config=cfg, engine=eng, handlers=HandlerRegistry(), grant=GrantPolicy())
    tm = MagicMock()
    tm.execute_tool = AsyncMock(return_value=None)
    return RoostEndpoint(
        agent_name=name,
        config=cfg,
        engine=eng,
        dispatcher=disp,
        carriers={CarrierKind.IN_PROCESS: carrier},
        tool_manager=tm,
        blackboard=blackboard,
        working_memory=working_memory,
        wake=AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_inform_updates_state_without_outbound_messages() -> None:
    """A capability-addressed inform with a no-decision handler is stored, not answered."""
    carrier = InProcessCarrier()
    blackboard = InMemoryBlackboard(scope="channel", policy=WriterPolicy())
    memory = MagicMock()
    memory.store_result = AsyncMock()
    receiver = _endpoint(
        "digester",
        carrier,
        RoostAgentConfig(capabilities=["digest.write"]),
        blackboard=blackboard,
        working_memory=memory,
    )
    sender = _endpoint("reporter", carrier, None)
    handled = asyncio.Event()

    async def on_status(msg: RoostMessage) -> None:
        entry = await blackboard.get("status", reader="digester")
        await blackboard.put(
            "status",
            msg.content,
            writer="digester",
            expected_version=None if entry is None else entry.version,
        )
        handled.set()

    receiver.register_handler("*", on_status, needs_decision=False)
    await receiver.start()
    await sender.start()
    content = {"status": "complete"}
    try:
        sent = await sender.inform(capability_filter="digest.*", content=content)
        await asyncio.wait_for(handled.wait(), 1)
        for _ in range(20):
            if memory.store_result.await_count:
                break
            await asyncio.sleep(0)

        entry = await blackboard.get("status", reader="digester")
        assert entry is not None and entry.value is content
        memory.store_result.assert_awaited_once()
        assert receiver.metrics["messages_out"] == 0
        assert receiver.metrics["wakes"] == 0
        receiver.wake.assert_not_awaited()
        served = [e for e in receiver.ledger.entries(conversation_id=sent.conversation_id) if e.direction == "served"]
        assert len(served) == 1
    finally:
        await sender.stop()
        await receiver.stop()
        await carrier.close()
