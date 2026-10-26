"""Gate L-S4 — an Arrow table crosses the in-process carrier by reference (FEAT-747 AC-23)."""

import asyncio
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pyarrow as pa
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


def _endpoint(name: str, carrier: InProcessCarrier, cfg: Optional[RoostAgentConfig]) -> RoostEndpoint:
    """Build one endpoint with a stubbed tool manager."""
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
        wake=AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_arrow_table_by_reference() -> None:
    """The receiver sees the identical table object and buffers; the handle lands on ``artifacts``."""
    carrier = InProcessCarrier()
    blackboard = InMemoryBlackboard(scope="channel", policy=WriterPolicy())
    producer = _endpoint("producer", carrier, None)
    consumer = _endpoint("consumer", carrier, RoostAgentConfig(capabilities=["analytics.ingest"]))
    received: asyncio.Future[RoostMessage] = asyncio.get_running_loop().create_future()

    async def capture(msg: RoostMessage) -> None:
        if not received.done():
            received.set_result(msg)

    consumer.register_handler("*", capture)
    await producer.start()
    await consumer.start()
    table = pa.table({"employee": ["E-1", "E-2"], "salary": [100, 200]})
    try:
        await producer.inform(capability_filter="analytics.*", content=table)
        msg = await asyncio.wait_for(received, 1)

        assert msg.content is table
        assert (
            msg.content.column(0).chunk(0).buffers()[1].address == table.column(0).chunk(0).buffers()[1].address
        )
        handle_id = f"arrow:{id(table)}"
        entry = await blackboard.put(
            "artifacts",
            {"handle_id": handle_id},
            writer="producer",
            expected_version=None,
            producer="producer",
        )
        stored = await blackboard.get("artifacts", reader="consumer")
        assert stored is entry
        assert stored.value["handle_id"] == handle_id
    finally:
        await producer.stop()
        await consumer.stop()
        await carrier.close()
