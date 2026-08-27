"""The actions stream must be ordered by ``server_seq``, and lossless.

Regression (run-949f8afa). ``DevLoopRunner``'s envelope sink used to spawn
one task per envelope; concurrent tasks on a pooled Redis client each take
their own connection, so arrival order at Redis did not have to match
``server_seq``. Because ``FlowStreamMultiplexer.state_tail`` stops on the
first terminal action it sees, an envelope that landed after ``run/closed``
was invisible to every console — the run's Handoff node showed as "running"
forever and its ``pr_url``/``jira_issue_key`` projections were dropped, so a
run that had opened a PR rendered "Run finished without a pull request".

Three guarantees are covered here:

1. the sink serialises its XADDs, so stream order == ``server_seq`` order;
2. ``_close_host`` flushes the queue, so ``run/closed`` really is last;
3. the read side is defensive anyway — ``state_replay`` folds in
   ``server_seq`` order and ``state_tail`` sweeps once more after a terminal
   action — so streams written by the old sink (they stay readable for the
   whole retention window) replay correctly instead of truncating.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

import pytest

from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_loop import BugBrief, DevLoopRunner, ShellCriterion
from parrot.flows.dev_loop.session_state import (
    NodeCompleted,
    NodeStarted,
    RunClosed,
    RunCreated,
    SessionHost,
)
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer

RUN_ID = "run-order001"


def _actions_key(run_id: str = RUN_ID) -> str:
    return f"flow:{run_id}:actions"


# ---------------------------------------------------------------------------
# Write side — DevLoopRunner's envelope sink
# ---------------------------------------------------------------------------


@pytest.fixture
def brief() -> BugBrief:
    return BugBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


class _JitteryRedis:
    """Records XADDs, sleeping LESS on each successive call.

    The descending delay is the point: with one task per envelope, later
    envelopes overtake earlier ones and the recorded order comes out
    reversed. With a single writer awaiting each XADD, order is preserved.
    """

    def __init__(self) -> None:
        self.seqs: List[int] = []
        self.types: List[str] = []
        self._calls = 0

    async def xadd(self, key: str, fields: Dict[str, str], **_kwargs: Any) -> str:
        self._calls += 1
        await asyncio.sleep(max(0.0, 0.02 - self._calls * 0.001))
        envelope = json.loads(fields["envelope"])
        self.seqs.append(envelope["server_seq"])
        self.types.append(envelope["action"]["type"])
        return f"{self._calls}-0"


class _ChattyFlow:
    """``run_flow`` stub that folds a burst of node events into the host."""

    def __init__(self, responses: Optional[Dict[str, Any]] = None) -> None:
        self.responses = responses or {}

    async def run_flow(self, ctx, **_kwargs: Any) -> FlowResult:
        host: SessionHost = ctx.shared_data["session_host"]
        for node_id in ("research", "development", "qa", "deployment_handoff"):
            host.apply(NodeStarted(node_id=node_id))
            host.apply(NodeCompleted(node_id=node_id))
        return FlowResult(
            output=ctx.shared_data.get("run_id"),
            status=FlowStatus.COMPLETED,
            responses=dict(self.responses),
        )


def _runner_with(redis_stub: _JitteryRedis, flow: Any) -> DevLoopRunner:
    runner = DevLoopRunner(  # type: ignore[arg-type]
        flow, max_concurrent_runs=2, redis_url="redis://fake:6379/0"
    )
    async def _ensure():
        return redis_stub
    runner._ensure_actions_redis = _ensure  # type: ignore[method-assign]
    return runner


@pytest.mark.asyncio
async def test_sink_publishes_in_server_seq_order(brief):
    """Stream order must match `server_seq` even when XADD latency varies."""
    redis_stub = _JitteryRedis()
    runner = _runner_with(redis_stub, _ChattyFlow())

    await runner.run(brief, run_id=RUN_ID)

    assert redis_stub.seqs, "nothing reached the actions stream"
    assert redis_stub.seqs == sorted(redis_stub.seqs), (
        f"actions stream is out of server_seq order: {redis_stub.seqs}"
    )
    # No duplicates, no gaps — a contiguous run of sequence numbers.
    assert redis_stub.seqs == list(range(1, len(redis_stub.seqs) + 1))


@pytest.mark.asyncio
async def test_close_host_flushes_so_run_closed_is_last(brief):
    """`run/closed` must be the final entry — that is what lets a console
    stop tailing on it without truncating anything."""
    redis_stub = _JitteryRedis()
    runner = _runner_with(redis_stub, _ChattyFlow())

    await runner.run(brief, run_id=RUN_ID)
    # Deliberately NO `await asyncio.sleep(...)` here: the flush is awaited
    # inside `_close_host`, so the stream is already complete.

    assert redis_stub.types[-1] == "run/closed"
    assert "node/completed" in redis_stub.types
    # Every node event precedes the terminal action.
    assert redis_stub.types.index("run/closed") == len(redis_stub.types) - 1


@pytest.mark.asyncio
async def test_sink_writer_is_retired_after_the_run(brief):
    """No leaked queue or writer task per finished run."""
    redis_stub = _JitteryRedis()
    runner = _runner_with(redis_stub, _ChattyFlow())

    await runner.run(brief, run_id=RUN_ID)

    assert RUN_ID not in runner._actions_queues
    assert RUN_ID not in runner._actions_writers


class _ExplodingFlow:
    """``run_flow`` stub that folds a few events, then raises."""

    async def run_flow(self, ctx, **_kwargs: Any) -> FlowResult:
        host: SessionHost = ctx.shared_data["session_host"]
        host.apply(NodeStarted(node_id="research"))
        raise RuntimeError("node graph exploded")


@pytest.mark.asyncio
async def test_abandoned_run_retires_its_writer(brief):
    """`_close_host` never runs when `run_flow` raises — the long-lived
    writer task must not be left parked on `queue.get()` forever."""
    redis_stub = _JitteryRedis()
    runner = _runner_with(redis_stub, _ExplodingFlow())

    with pytest.raises(RuntimeError, match="exploded"):
        await runner.run(brief, run_id=RUN_ID)

    assert RUN_ID not in runner._actions_queues
    assert RUN_ID not in runner._actions_writers
    # And the original exception is what surfaced — not a cancellation
    # leaking out of the cleanup path.


# ---------------------------------------------------------------------------
# Read side — tolerate a stream the OLD sink wrote out of order
# ---------------------------------------------------------------------------


class _FakeStreamsRedis:
    """In-process fake Redis Streams (mirrors test_streaming.py's)."""

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
            if cursor == "$":
                continue
            collected = [
                (entry_id, fields)
                for entry_id, fields in self._streams.get(key, [])
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


async def _seed_out_of_order(fake_redis: _FakeStreamsRedis) -> SessionHost:
    """Write the exact shape run-949f8afa produced: the Handoff node's
    ``node/completed`` lands AFTER ``run/closed``."""
    host = SessionHost(RUN_ID)
    created = host.apply(
        RunCreated(run_id=RUN_ID, work_kind="bug", summary="weak sha1")
    )
    started = host.apply(NodeStarted(node_id="deployment_handoff"))
    completed = host.apply(NodeCompleted(node_id="deployment_handoff"))
    closed = host.apply(RunClosed(
        outcome="succeeded",
        jira_issue_key="SKIP-0",
        pr_url="https://github.com/phenobarbital/ai-parrot/pull/1250",
    ))
    # Note the inversion: `closed` is written before `completed`.
    for envelope in (created, started, closed, completed):
        await fake_redis.xadd(
            _actions_key(), {"envelope": envelope.model_dump_json()}
        )
    return host


@pytest.mark.asyncio
async def test_state_replay_folds_in_server_seq_order(fake_redis):
    """An out-of-order stream must still rebuild the true terminal state."""
    await _seed_out_of_order(fake_redis)

    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state", block_ms=50)
    frames = [f async for f in mux.state_replay(last_seen=None)]

    assert len(frames) == 1
    state = frames[0]["payload"]["state"]
    # Folded in stream order, `node/completed` would land after the
    # terminal-sticky `run/closed` and still win... but `from_seq` would be
    # wrong and the reconnect yield order would be inverted. Assert both.
    assert state["nodes"]["deployment_handoff"]["status"] == "completed"
    assert state["phase"] == "succeeded"
    assert state["pr_url"].endswith("/pull/1250")
    assert frames[0]["payload"]["from_seq"] == 4


@pytest.mark.asyncio
async def test_state_replay_gap_yield_is_seq_ordered(fake_redis):
    """A reconnecting console must receive the gap in `server_seq` order."""
    await _seed_out_of_order(fake_redis)

    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state", block_ms=50)
    frames = [f async for f in mux.state_replay(last_seen=2)]

    seqs = [f["payload"]["server_seq"] for f in frames]
    assert seqs == [3, 4], seqs
    assert frames[0]["payload"]["action"]["type"] == "node/completed"
    assert frames[1]["payload"]["action"]["type"] == "run/closed"


@pytest.mark.asyncio
async def test_state_tail_sweeps_entries_written_after_run_closed(fake_redis):
    """The tail must not truncate an envelope that trails a terminal action."""
    host = SessionHost(RUN_ID)
    closed = host.apply(RunClosed(outcome="succeeded", pr_url="https://x/pull/7"))
    trailing = host.apply(NodeCompleted(node_id="deployment_handoff"))
    for envelope in (closed, trailing):
        await fake_redis.xadd(
            _actions_key(), {"envelope": envelope.model_dump_json()}
        )

    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state", block_ms=50)
    mux._state_cursor = "0-0"

    frames = [f async for f in mux.state_tail()]

    types = [f["payload"]["action"]["type"] for f in frames]
    assert types == ["run/closed", "node/completed"], types


@pytest.mark.asyncio
async def test_state_tail_still_stops_on_terminal_action(fake_redis):
    """The sweep must not turn the tail into an endless generator."""
    host = SessionHost(RUN_ID)
    closed = host.apply(RunClosed(outcome="succeeded"))
    await fake_redis.xadd(_actions_key(), {"envelope": closed.model_dump_json()})

    mux = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state", block_ms=50)
    mux._state_cursor = "0-0"

    frames = await asyncio.wait_for(
        _collect(mux.state_tail()), timeout=2,
    )
    assert [f["payload"]["action"]["type"] for f in frames] == ["run/closed"]


async def _collect(agen) -> List[Dict[str, Any]]:
    return [f async for f in agen]
