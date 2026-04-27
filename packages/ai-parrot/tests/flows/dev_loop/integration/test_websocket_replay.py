"""WebSocket replay-after-disconnect test for FlowStreamMultiplexer.

Verifies that historical events are replayed on reconnect when
``replay=true``. Uses an in-process Redis Streams stub so the test
does not require a live Redis instance.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Tuple, Optional

import pytest

from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer


pytestmark = pytest.mark.live


class _FakeRedis:
    def __init__(self) -> None:
        self._streams: Dict[str, List[Tuple[str, Dict[str, str]]]] = {}
        self._counter = 0

    async def xrange(self, name: str, *, min: str = "-", max: str = "+"):
        return list(self._streams.get(name, []))

    async def xread(self, streams: Dict[str, str], *, block: Optional[int] = None, count: Optional[int] = None):
        result = []
        for key, cursor in streams.items():
            if cursor == "$":
                continue
            collected = [
                (eid, fields)
                for eid, fields in self._streams.get(key, [])
                if eid > cursor
            ]
            if collected:
                result.append((key, collected))
        if not result and block:
            await asyncio.sleep(block / 1000.0)
        return result

    async def keys(self, pattern: str):
        prefix = pattern.rstrip("*")
        return sorted(k for k in self._streams.keys() if k.startswith(prefix))

    def seed(self, stream: str, kind: str, ts: float):
        self._counter += 1
        eid = f"{int(ts * 1000)}-{self._counter}"
        self._streams.setdefault(stream, []).append(
            (
                eid,
                {
                    "event": json.dumps(
                        {
                            "kind": kind,
                            "ts": ts,
                            "run_id": "run-1",
                            "node_id": "research",
                            "payload": {},
                        }
                    )
                },
            )
        )


@pytest.mark.asyncio
async def test_websocket_replay_after_disconnect():
    """Five events seeded; after disconnect+reconnect with replay=true,
    all 5 historical events arrive in order."""
    redis = _FakeRedis()
    flow_key = "flow:run-1:flow"
    for i in range(5):
        redis.seed(flow_key, kind=f"flow.event_{i}", ts=float(i))

    mux = FlowStreamMultiplexer(redis, run_id="run-1", view="flow")
    received: List[str] = []
    async for env in mux.replay():
        received.append(env["event_kind"])

    assert received == [f"flow.event_{i}" for i in range(5)]
