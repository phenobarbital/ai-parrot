"""FlowStreamMultiplexer sub-stream discovery for the dev-agent pool (TASK-1864).

Verifies that ``FlowStreamMultiplexer._discover_dispatch_streams()`` — via
its existing ``SCAN``-based implementation, unchanged by FEAT-323 — picks
up the per-worker streams (``development.w1``, ``development.w2``, ...)
that a ``DevAgentPool`` run publishes, exactly as it already does for a
single-agent ``development`` stream.
"""

from __future__ import annotations

import pytest

from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer

from .conftest import FakeRedis


@pytest.mark.asyncio
class TestStreamDiscovery:
    async def test_multiplexer_discovers_worker_streams(self):
        redis = FakeRedis(
            keys=[
                "flow:run-1:flow",
                "flow:run-1:dispatch:development.w1",
                "flow:run-1:dispatch:development.w2",
                "flow:other-run:dispatch:development.w1",  # different run — must be excluded
            ]
        )
        multiplexer = FlowStreamMultiplexer(redis, run_id="run-1")

        discovered = await multiplexer._discover_dispatch_streams()

        assert discovered == [
            "flow:run-1:dispatch:development.w1",
            "flow:run-1:dispatch:development.w2",
        ]

    async def test_multiplexer_discovers_single_agent_stream_unchanged(self):
        """Back-compat: the pre-FEAT-323 single 'development' stream still discovers."""
        redis = FakeRedis(keys=["flow:run-2:flow", "flow:run-2:dispatch:development"])
        multiplexer = FlowStreamMultiplexer(redis, run_id="run-2")

        discovered = await multiplexer._discover_dispatch_streams()

        assert discovered == ["flow:run-2:dispatch:development"]

    async def test_no_dispatch_streams_returns_empty(self):
        redis = FakeRedis(keys=["flow:run-3:flow"])
        multiplexer = FlowStreamMultiplexer(redis, run_id="run-3")

        discovered = await multiplexer._discover_dispatch_streams()

        assert discovered == []
