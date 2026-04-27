"""Unit tests for parrot.flows.dev_loop.streaming (TASK-879).

The tests use a small in-process fake of a Redis Streams client (no
fakeredis needed). The fake supports ``xrange``, ``xread`` (with
``BLOCK`` interpreted as a single sleep + return), ``keys``, and
``aclose``.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest

from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer


# ---------------------------------------------------------------------------
# Mini fake Redis (just enough for the multiplexer)
# ---------------------------------------------------------------------------


class _FakeStreamsRedis:
    def __init__(self) -> None:
        self._streams: Dict[str, List[Tuple[str, Dict[str, str]]]] = {}
        self._counter = 0

    async def xadd(
        self, key: str, fields: Dict[str, str], **_kwargs: Any
    ) -> str:
        self._counter += 1
        entry_id = f"{int(time.time() * 1000)}-{self._counter}"
        self._streams.setdefault(key, []).append((entry_id, fields))
        return entry_id

    async def xrange(
        self, name: str, *, min: str = "-", max: str = "+"  # noqa: A002
    ) -> List[Tuple[str, Dict[str, str]]]:
        return list(self._streams.get(name, []))

    async def xread(
        self,
        streams: Dict[str, str],
        *,
        block: Optional[int] = None,
        count: Optional[int] = None,
    ) -> List[Tuple[str, List[Tuple[str, Dict[str, str]]]]]:
        # Return everything strictly after each cursor; if nothing new,
        # respect the BLOCK timeout once and return [].
        result: List[Tuple[str, List[Tuple[str, Dict[str, str]]]]] = []
        for key, cursor in streams.items():
            entries = self._streams.get(key, [])
            if cursor == "$":
                continue
            collected = []
            for entry_id, fields in entries:
                if entry_id > cursor:
                    collected.append((entry_id, fields))
            if collected:
                result.append((key, collected))
        if not result and block:
            await asyncio.sleep(block / 1000.0)
        return result

    async def keys(self, pattern: str) -> List[str]:
        # Very rough wildcard handling: only support trailing '*'.
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return sorted(k for k in self._streams.keys() if k.startswith(prefix))
        return sorted(k for k in self._streams.keys() if k == pattern)

    async def aclose(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def fake_redis():
    return _FakeStreamsRedis()


def _seed_event(
    redis: _FakeStreamsRedis,
    stream: str,
    *,
    kind: str,
    ts: float,
    run_id: str = "run-1",
    node_id: str = "research",
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Synchronously append a DispatchEvent-shaped event to a stream."""
    redis._counter += 1
    entry_id = f"{int(ts * 1000)}-{redis._counter}"
    fields = {
        "event": json.dumps(
            {
                "kind": kind,
                "ts": ts,
                "run_id": run_id,
                "node_id": node_id,
                "payload": payload or {},
            }
        )
    }
    redis._streams.setdefault(stream, []).append((entry_id, fields))


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


class TestReplay:
    async def test_merges_two_streams_in_ts_order(self, fake_redis):
        run_id = "run-1"
        flow_key = f"flow:{run_id}:flow"
        dispatch_key = f"flow:{run_id}:dispatch:research"

        _seed_event(fake_redis, flow_key, kind="flow.started", ts=10.0)
        _seed_event(fake_redis, dispatch_key, kind="dispatch.queued", ts=11.0)
        _seed_event(fake_redis, flow_key, kind="flow.node_entered", ts=12.0)
        _seed_event(fake_redis, dispatch_key, kind="dispatch.started", ts=12.5)

        mux = FlowStreamMultiplexer(fake_redis, run_id=run_id)
        envelopes = [env async for env in mux.replay()]

        assert [e["event_kind"] for e in envelopes] == [
            "flow.started",
            "dispatch.queued",
            "flow.node_entered",
            "dispatch.started",
        ]
        assert [e["source"] for e in envelopes] == [
            "flow",
            "dispatch",
            "flow",
            "dispatch",
        ]


# ---------------------------------------------------------------------------
# View filter
# ---------------------------------------------------------------------------


class TestViewFilter:
    async def test_view_flow_only(self, fake_redis):
        run_id = "run-2"
        flow_key = f"flow:{run_id}:flow"
        dispatch_key = f"flow:{run_id}:dispatch:research"
        _seed_event(fake_redis, flow_key, kind="flow.started", ts=1.0)
        _seed_event(fake_redis, dispatch_key, kind="dispatch.started", ts=2.0)

        mux = FlowStreamMultiplexer(fake_redis, run_id=run_id, view="flow")
        envelopes = [env async for env in mux.replay()]
        assert len(envelopes) == 1
        assert envelopes[0]["source"] == "flow"

    async def test_view_dispatch_only(self, fake_redis):
        run_id = "run-3"
        flow_key = f"flow:{run_id}:flow"
        dispatch_key = f"flow:{run_id}:dispatch:research"
        _seed_event(fake_redis, flow_key, kind="flow.started", ts=1.0)
        _seed_event(fake_redis, dispatch_key, kind="dispatch.started", ts=2.0)

        mux = FlowStreamMultiplexer(fake_redis, run_id=run_id, view="dispatch")
        envelopes = [env async for env in mux.replay()]
        assert len(envelopes) == 1
        assert envelopes[0]["source"] == "dispatch"
        assert envelopes[0]["node_id"] == "research"


# ---------------------------------------------------------------------------
# Tail (live)
# ---------------------------------------------------------------------------


class TestTail:
    async def test_tail_forwards_new_events(self, fake_redis):
        run_id = "run-4"
        flow_key = f"flow:{run_id}:flow"

        # Seed initial event so replay sets a cursor.
        _seed_event(fake_redis, flow_key, kind="flow.started", ts=1.0)

        mux = FlowStreamMultiplexer(
            fake_redis, run_id=run_id, view="flow", block_ms=50
        )
        # Drain replay first.
        replayed = [env async for env in mux.replay()]
        assert len(replayed) == 1

        async def _produce_then_close():
            await asyncio.sleep(0.05)
            _seed_event(fake_redis, flow_key, kind="flow.completed", ts=2.0)
            await asyncio.sleep(0.2)
            await mux.close()

        producer = asyncio.create_task(_produce_then_close())
        envelopes: List[Dict[str, Any]] = []
        async for env in mux.tail():
            envelopes.append(env)
            if env["event_kind"] == "flow.completed":
                break
        await mux.close()
        await producer

        assert any(e["event_kind"] == "flow.completed" for e in envelopes)
