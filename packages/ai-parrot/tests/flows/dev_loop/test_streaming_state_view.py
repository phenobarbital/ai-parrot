"""Unit tests for ``FlowStreamMultiplexer`` ``view="state"`` (FEAT-322 TASK-1854).

Reuses ``test_streaming.py``'s in-process fake Redis Streams client (no
fakeredis needed) — see that module's docstring for the fake's semantics.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import pytest

from parrot.flows.dev_loop.session_state import (
    NodeCompleted,
    NodeStarted,
    RunClosed,
    RunCreated,
    SessionHost,
)
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer

RUN_ID = "run-state0001"


# ---------------------------------------------------------------------------
# Mini fake Redis (mirrors test_streaming.py's _FakeStreamsRedis)
# ---------------------------------------------------------------------------


class _FakeStreamsRedis:
    def __init__(self) -> None:
        self._streams: Dict[str, List[Tuple[str, Dict[str, str]]]] = {}
        self._counter = 0

    async def xadd(self, key: str, fields: Dict[str, str], **_kwargs: Any) -> str:
        self._counter += 1
        entry_id = f"{1_700_000_000_000 + self._counter}-0"
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
        result: List[Tuple[str, List[Tuple[str, Dict[str, str]]]]] = []
        for key, cursor in streams.items():
            entries = self._streams.get(key, [])
            if cursor == "$":
                continue
            collected = [
                (entry_id, fields) for entry_id, fields in entries
                if entry_id > cursor
            ]
            if collected:
                result.append((key, collected))
        if not result and block:
            await asyncio.sleep(block / 1000.0)
        return result

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_redis() -> _FakeStreamsRedis:
    return _FakeStreamsRedis()


def _actions_key() -> str:
    return f"flow:{RUN_ID}:actions"


async def _seed_lifecycle(redis: _FakeStreamsRedis, host: SessionHost) -> None:
    """Apply a few actions to ``host`` and XADD each resulting envelope."""
    for action in (
        RunCreated(run_id=RUN_ID, work_kind="bug", summary="fix it"),
        NodeStarted(node_id="qa"),
        NodeCompleted(node_id="qa", summary={"passed": "true"}),
    ):
        envelope = host.apply(action)
        await redis.xadd(_actions_key(), {"envelope": envelope.model_dump_json()})


# ---------------------------------------------------------------------------
# Snapshot-first, seq monotonic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_view_snapshot_first(fake_redis):
    host = SessionHost(RUN_ID)
    await _seed_lifecycle(fake_redis, host)

    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state")
    frames = [f async for f in mux.state_replay(last_seen=None)]

    assert len(frames) == 1
    frame = frames[0]
    assert frame["source"] == "state"
    assert frame["node_id"] is None
    assert frame["event_kind"] == "snapshot"
    payload = frame["payload"]
    assert payload["from_seq"] == 3
    assert payload["state"]["phase"] == "running"
    assert payload["state"]["nodes"]["qa"]["status"] == "completed"


@pytest.mark.asyncio
async def test_state_view_seq_monotonic(fake_redis):
    host = SessionHost(RUN_ID)
    await _seed_lifecycle(fake_redis, host)

    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state")
    frames = [f async for f in mux.state_replay(last_seen=0)]

    seqs = [f["payload"]["server_seq"] for f in frames]
    assert seqs == sorted(seqs)
    assert seqs == [1, 2, 3]


# ---------------------------------------------------------------------------
# last_seen reconnect replay — no gaps, no dupes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_last_seen_replay_no_gaps_no_dupes(fake_redis):
    host = SessionHost(RUN_ID)
    await _seed_lifecycle(fake_redis, host)

    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state")
    frames = [f async for f in mux.state_replay(last_seen=1)]

    # No snapshot frame when last_seen is given.
    assert all(f["event_kind"] == "action" for f in frames)
    seqs = [f["payload"]["server_seq"] for f in frames]
    assert seqs == [2, 3]  # strictly > 1, no gaps, no dupes


@pytest.mark.asyncio
async def test_last_seen_at_head_replays_nothing(fake_redis):
    host = SessionHost(RUN_ID)
    await _seed_lifecycle(fake_redis, host)

    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state")
    frames = [f async for f in mux.state_replay(last_seen=3)]
    assert frames == []


# ---------------------------------------------------------------------------
# Finished run (stream present, no live producer) — fold reflects final state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finished_run_fold(fake_redis):
    host = SessionHost(RUN_ID)
    await _seed_lifecycle(fake_redis, host)
    envelope = host.apply(RunClosed(outcome="succeeded", jira_issue_key="OPS-1", pr_url="http://pr"))
    await fake_redis.xadd(_actions_key(), {"envelope": envelope.model_dump_json()})

    # A FRESH multiplexer — no live host, no reference to the one above —
    # proves the crash-rebuild invariant (spec §7): folding the stream alone
    # reproduces the final state.
    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state")
    frames = [f async for f in mux.state_replay(last_seen=None)]

    assert len(frames) == 1
    payload = frames[0]["payload"]
    assert payload["state"]["phase"] == "succeeded"
    assert payload["state"]["jira_issue_key"] == "OPS-1"
    assert payload["state"]["pr_url"] == "http://pr"
    assert payload["from_seq"] == 4


# ---------------------------------------------------------------------------
# Malformed entries — skipped, never crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bad_frame_skipped_not_crash(fake_redis):
    host = SessionHost(RUN_ID)
    e1 = host.apply(RunCreated(run_id=RUN_ID))
    await fake_redis.xadd(_actions_key(), {"envelope": e1.model_dump_json()})
    # Malformed entry: not valid JSON.
    await fake_redis.xadd(_actions_key(), {"envelope": "{not json"})
    # Entry missing the "envelope" field entirely.
    await fake_redis.xadd(_actions_key(), {"something_else": "x"})
    e2 = host.apply(NodeStarted(node_id="qa"))
    await fake_redis.xadd(_actions_key(), {"envelope": e2.model_dump_json()})

    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state")
    frames = [f async for f in mux.state_replay(last_seen=None)]  # must not raise

    assert len(frames) == 1
    payload = frames[0]["payload"]
    # Only the 2 valid envelopes folded; from_seq reflects the LAST valid one
    # read (seq numbering comes from the envelope itself, not stream position).
    assert payload["from_seq"] == 2
    assert payload["state"]["nodes"]["qa"]["status"] == "running"


# ---------------------------------------------------------------------------
# state_tail — live continuation after state_replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_tail_continues_from_replay_cursor(fake_redis):
    host = SessionHost(RUN_ID)
    await _seed_lifecycle(fake_redis, host)

    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state", block_ms=50)
    frames = [f async for f in mux.state_replay(last_seen=None)]
    assert len(frames) == 1  # just the snapshot

    # A new action arrives live.
    new_envelope = host.apply(NodeStarted(node_id="deployment_handoff"))
    await fake_redis.xadd(_actions_key(), {"envelope": new_envelope.model_dump_json()})

    tail_frame = await asyncio.wait_for(mux.state_tail().__anext__(), timeout=2)
    assert tail_frame["source"] == "state"
    assert tail_frame["event_kind"] == "action"
    assert tail_frame["payload"]["server_seq"] == 4
    assert tail_frame["payload"]["action"]["node_id"] == "deployment_handoff"


# ---------------------------------------------------------------------------
# Legacy views untouched — sanity (full coverage lives in test_streaming.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_flow_view_unaffected_by_state_view_additions(fake_redis):
    await fake_redis.xadd(
        f"flow:{RUN_ID}:flow",
        {"event": '{"kind":"flow.node_started","ts":1.0,"run_id":"' + RUN_ID + '","node_id":"qa","payload":{}}'},
    )
    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="flow")
    frames = [f async for f in mux.replay()]
    assert len(frames) == 1
    assert frames[0]["source"] == "flow"
    assert frames[0]["event_kind"] == "flow.node_started"
