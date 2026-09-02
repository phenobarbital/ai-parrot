"""Dual-publish shim tests (FEAT-322 TASK-1852).

Covers both shim sites:
- ``FlowEventPublisher.__call__`` (flow.py) — node lifecycle events.
- The dispatcher ``_publish_event`` definitions (dispatchers/*.py), which
  all fold through the ONE shared module-level ``_apply_to_session_host``
  helper via the ``_SESSION_HOST_CTX`` contextvar bound by ``dispatch()``.

Asserts: legacy envelopes are byte-identical whether or not a host is
present; the session-state fold and the legacy XADD are independent
failure domains in both directions; no host in shared state means
legacy-only behavior (today's behavior, unchanged).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncIterator, List
from unittest.mock import AsyncMock

import pytest

from parrot.flows.dev_loop import (
    ClaudeCodeDispatcher,
    ClaudeCodeDispatchProfile,
    DispatchExecutionError,
    ResearchOutput,
)
from parrot.flows.dev_loop.dispatchers._shared import _apply_to_session_host, _SESSION_HOST_CTX
from parrot.flows.dev_loop.flow import FlowEventPublisher
from parrot.flows.dev_loop.models import DispatchEvent
from parrot.flows.dev_loop.session_state import SessionHost, session_channel

RUN_ID = "run-dual0001"


# ---------------------------------------------------------------------------
# flow.py — FlowEventPublisher dual-publish
# ---------------------------------------------------------------------------


@pytest.fixture
def publisher(monkeypatch) -> FlowEventPublisher:
    pub = FlowEventPublisher(redis_url="redis://localhost:6399/9", run_id_holder={})
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(pub, "_ensure_redis", _ensure_redis)
    pub._fake_redis = fake_redis  # type: ignore[attr-defined]
    return pub


def _ctx_with(shared_data: dict) -> SimpleNamespace:
    return SimpleNamespace(shared_data=shared_data)


@pytest.mark.asyncio
async def test_flow_event_folds_into_host(publisher):
    host = SessionHost(RUN_ID)
    ctx = _ctx_with({"run_id": RUN_ID, "session_host": host})

    await publisher("node_started", "qa", {"flow": "dev-loop", "context": ctx})

    assert host.state.nodes["qa"].status == "running"
    # Legacy path still fires.
    publisher._fake_redis.xadd.assert_awaited_once()


@pytest.mark.asyncio
async def test_flow_event_without_host_is_legacy_only(publisher):
    ctx = _ctx_with({"run_id": RUN_ID})  # no "session_host" key

    # Must not raise — legacy-only behavior, exactly as today.
    await publisher("node_started", "qa", {"flow": "dev-loop", "context": ctx})
    publisher._fake_redis.xadd.assert_awaited_once()


@pytest.mark.asyncio
async def test_flow_event_node_failed_error_folds_into_host(publisher):
    host = SessionHost(RUN_ID)
    ctx = _ctx_with({"run_id": RUN_ID, "session_host": host})

    await publisher(
        "node_failed", "qa",
        {"flow": "dev-loop", "context": ctx, "error": "boom", "error_type": "RuntimeError"},
    )

    assert host.state.nodes["qa"].status == "failed"
    assert host.state.nodes["qa"].error == "boom"


@pytest.mark.asyncio
async def test_flow_event_host_apply_failure_does_not_break_legacy_publish(publisher):
    class _BrokenHost:
        def apply(self, action):
            raise RuntimeError("host is broken")

    ctx = _ctx_with({"run_id": RUN_ID, "session_host": _BrokenHost()})

    # Must not raise — the session-state fold is an independent failure
    # domain from the legacy XADD.
    await publisher("node_started", "qa", {"flow": "dev-loop", "context": ctx})
    publisher._fake_redis.xadd.assert_awaited_once()


@pytest.mark.asyncio
async def test_flow_legacy_xadd_failure_does_not_break_session_fold(monkeypatch):
    """Legacy XADD failing must not prevent the session-state fold."""
    pub = FlowEventPublisher(redis_url="redis://localhost:6399/9", run_id_holder={})

    async def _ensure_redis_raises():
        raise ConnectionError("redis is down")

    monkeypatch.setattr(pub, "_ensure_redis", _ensure_redis_raises)

    host = SessionHost(RUN_ID)
    ctx = _ctx_with({"run_id": RUN_ID, "session_host": host})

    await pub("node_started", "qa", {"flow": "dev-loop", "context": ctx})

    # Legacy XADD failed (swallowed) but the host still folded in-memory.
    assert host.state.nodes["qa"].status == "running"


@pytest.mark.asyncio
async def test_session_fold_precedes_the_redis_round_trip(monkeypatch):
    """The host must be folded before this coroutine's first ``await``.

    ``AgentsFlow._notify_node_event`` schedules this publisher
    fire-and-forget, so anything sequenced after an ``await`` races the end
    of the run. When the XADD came first, the last events of a run — the
    node that failed, then the terminal handler — were still parked on
    Redis when ``DevLoopRunner._close_host`` snapshotted the host, and the
    console showed a failed node as forever "running".
    """
    pub = FlowEventPublisher(redis_url="redis://localhost:6399/9", run_id_holder={})
    host = SessionHost(RUN_ID)
    ctx = _ctx_with({"run_id": RUN_ID, "session_host": host})

    status_seen_by_redis: list[str] = []

    class _SlowRedis:
        async def xadd(self, *args, **kwargs):
            # By the time the network call is reached, the fold is done.
            status_seen_by_redis.append(host.state.nodes["qa"].status)
            return b"1-0"

    async def _ensure_redis():
        return _SlowRedis()

    monkeypatch.setattr(pub, "_ensure_redis", _ensure_redis)

    await pub(
        "node_failed", "qa",
        {"flow": "dev-loop", "context": ctx, "error": "boom"},
    )

    assert status_seen_by_redis == ["failed"]


# ---------------------------------------------------------------------------
# dispatcher.py — _apply_to_session_host (the ONE shared shim helper)
# ---------------------------------------------------------------------------


def _dispatch_event(kind: str, node_id: str = "development", **payload: Any) -> DispatchEvent:
    return DispatchEvent(kind=kind, ts=1.0, run_id=RUN_ID, node_id=node_id, payload=payload)


def test_dispatch_event_bumps_counters():
    host = SessionHost(RUN_ID)
    token = _SESSION_HOST_CTX.set(host)
    try:
        _apply_to_session_host(_dispatch_event("dispatch.queued", dispatcher="claude-code"))
        _apply_to_session_host(_dispatch_event("dispatch.started", terminal="parrot-terminal:/x/development"))
        _apply_to_session_host(_dispatch_event("dispatch.message"))
        _apply_to_session_host(_dispatch_event("dispatch.tool_use", tool_name="Read"))
        _apply_to_session_host(_dispatch_event("dispatch.completed"))
    finally:
        _SESSION_HOST_CTX.reset(token)

    dispatch_state = host.state.nodes["development"].dispatch
    assert dispatch_state.status == "completed"
    assert dispatch_state.message_count == 1
    assert dispatch_state.tool_use_count == 1
    assert dispatch_state.dispatcher == "claude-code"


def test_pool_worker_seats_fold_into_their_owning_node():
    """A pooled `development` node used to report 0 msgs / 0 tools.

    `NodeId` is a closed Literal, so a "development.w1"-keyed action was
    rejected and swallowed. Seats now roll up to the node that owns them,
    and several workers accumulate onto that one node.
    """
    host = SessionHost(RUN_ID)
    token = _SESSION_HOST_CTX.set(host)
    try:
        for seat in ("development.w1", "development.w2"):
            _apply_to_session_host(
                _dispatch_event("dispatch.queued", node_id=seat, dispatcher="nvidia")
            )
            _apply_to_session_host(_dispatch_event("dispatch.message", node_id=seat))
            _apply_to_session_host(
                _dispatch_event("dispatch.tool_use", node_id=seat, tool_name="write_file")
            )
            _apply_to_session_host(
                _dispatch_event(
                    "dispatch.completed",
                    node_id=seat,
                    usage={"input_tokens": 100, "output_tokens": 20, "num_turns": 3},
                )
            )
        _apply_to_session_host(
            _dispatch_event("dispatch.tool_use", node_id="development.resolver", tool_name="Bash")
        )
    finally:
        _SESSION_HOST_CTX.reset(token)

    assert "development.w1" not in host.state.nodes
    dispatch_state = host.state.nodes["development"].dispatch
    assert dispatch_state.message_count == 2
    assert dispatch_state.tool_use_count == 3
    # Both workers' spend is summed, not overwritten by the last one.
    assert dispatch_state.input_tokens == 200
    assert dispatch_state.output_tokens == 40
    assert dispatch_state.num_turns == 6


def test_pool_worker_seats_are_also_projected_individually():
    """FEAT-496: the roll-up above is unchanged; seat detail is additive.

    Same event sequence as ``test_pool_worker_seats_fold_into_their_owning_node``
    (which must keep passing unchanged) — this test only adds NEW
    assertions about ``DispatchState.seats``.
    """
    host = SessionHost(RUN_ID)
    token = _SESSION_HOST_CTX.set(host)
    try:
        for seat in ("development.w1", "development.w2"):
            _apply_to_session_host(
                _dispatch_event("dispatch.queued", node_id=seat, dispatcher="nvidia")
            )
            _apply_to_session_host(
                _dispatch_event("dispatch.tool_use", node_id=seat, tool_name="write_file")
            )
        _apply_to_session_host(
            _dispatch_event("dispatch.tool_use", node_id="development.resolver", tool_name="Bash")
        )
    finally:
        _SESSION_HOST_CTX.reset(token)

    seats = host.state.nodes["development"].dispatch.seats
    assert set(seats) == {"development.w1", "development.w2", "development.resolver"}
    assert seats["development.w1"].last_tool == "write_file"
    assert seats["development.w2"].last_tool == "write_file"
    assert seats["development.resolver"].last_tool == "Bash"
    # Roll-up still correct alongside the new per-seat detail.
    assert host.state.nodes["development"].dispatch.tool_use_count == 3


def test_dispatch_completed_without_usage_keeps_earlier_totals():
    """An unreported second dispatch must not blank the first's numbers."""
    host = SessionHost(RUN_ID)
    token = _SESSION_HOST_CTX.set(host)
    try:
        _apply_to_session_host(
            _dispatch_event(
                "dispatch.completed",
                node_id="development.w1",
                usage={"input_tokens": 7, "output_tokens": 11},
            )
        )
        _apply_to_session_host(_dispatch_event("dispatch.completed", node_id="development.w2"))
    finally:
        _SESSION_HOST_CTX.reset(token)

    dispatch_state = host.state.nodes["development"].dispatch
    assert dispatch_state.input_tokens == 7
    assert dispatch_state.output_tokens == 11
    # Never fabricated: nothing reported cost anywhere.
    assert dispatch_state.total_cost_usd is None


def test_dispatch_event_no_host_bound_is_noop():
    # No _SESSION_HOST_CTX.set() call — must not raise (default is None).
    _apply_to_session_host(_dispatch_event("dispatch.queued"))


def test_dispatch_event_host_apply_failure_is_swallowed():
    class _BrokenHost:
        def apply(self, action):
            raise RuntimeError("host is broken")

    token = _SESSION_HOST_CTX.set(_BrokenHost())
    try:
        # Must not raise.
        _apply_to_session_host(_dispatch_event("dispatch.queued"))
    finally:
        _SESSION_HOST_CTX.reset(token)


# ---------------------------------------------------------------------------
# Full round-trip: dispatch() with/without session_host — legacy envelope
# byte-identical, actions fold when a host is present.
# ---------------------------------------------------------------------------


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _AssistantMessage:
    def __init__(self, content: List[Any]) -> None:
        self.content = content


class _ResultMessage:
    def __init__(self, *, success: bool = True) -> None:
        self.subtype = "success" if success else "failure"
        self.is_error = False
        self.api_error_status = None
        self.result = None
        self.num_turns = 1
        self.permission_denials = None
        self.content: List[Any] = []


class _FakeClient:
    def __init__(self, messages: List[Any]) -> None:
        self._messages = messages

    async def stream_messages(self, prompt: str, *, run_options: Any) -> AsyncIterator[Any]:
        for msg in self._messages:
            yield msg


def _research_payload() -> str:
    return (
        '{"jira_issue_key":"OPS-1","spec_path":"sdd/specs/x.spec.md",'
        '"feat_id":"FEAT-130","branch_name":"feat-130-fix",'
        '"worktree_path":"/abs/.claude/worktrees/feat-130-fix",'
        '"log_excerpts":[]}'
    )


@pytest.fixture(autouse=True)
def _patch_worktree_base(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.claude.conf.WORKTREE_BASE_PATH", str(tmp_path)
    )
    return tmp_path


def _make_dispatcher(monkeypatch) -> ClaudeCodeDispatcher:
    disp = ClaudeCodeDispatcher(
        max_concurrent=2, redis_url="redis://localhost:6379/0", stream_ttl_seconds=300,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_ensure_redis", _ensure_redis)
    disp._fake_redis = fake_redis  # type: ignore[attr-defined]
    return disp


async def _run_dispatch(dispatcher, monkeypatch, tmp_path, *, session_host=None):
    messages = [
        _AssistantMessage(content=[_TextBlock(_research_payload())]),
        _ResultMessage(success=True),
    ]
    fake_client = _FakeClient(messages)
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.claude.LLMFactory.create",
        lambda *a, **kw: fake_client,
    )
    brief = ResearchOutput(
        jira_issue_key="OPS-0", spec_path="x", feat_id="FEAT-0",
        branch_name="b", worktree_path=str(tmp_path),
    )
    return await dispatcher.dispatch(
        brief=brief,
        profile=ClaudeCodeDispatchProfile(),
        output_model=ResearchOutput,
        run_id=RUN_ID,
        node_id="research",
        cwd=str(tmp_path),
        session_host=session_host,
    )


@pytest.mark.asyncio
async def test_legacy_envelope_unchanged_with_shim_active(monkeypatch, tmp_path):
    disp_legacy = _make_dispatcher(monkeypatch)
    await _run_dispatch(disp_legacy, monkeypatch, tmp_path, session_host=None)
    legacy_calls = disp_legacy._fake_redis.xadd.await_args_list

    disp_with_host = _make_dispatcher(monkeypatch)
    host = SessionHost(RUN_ID)
    await _run_dispatch(disp_with_host, monkeypatch, tmp_path, session_host=host)
    shimmed_calls = disp_with_host._fake_redis.xadd.await_args_list

    # Same number of legacy XADD calls, same args (stream key, fields dict
    # shape, maxlen/approximate) — the shim adds a SEPARATE fold, it never
    # touches the legacy envelope construction/XADD call.
    assert len(legacy_calls) == len(shimmed_calls) == 5
    for legacy_call, shimmed_call in zip(legacy_calls, shimmed_calls):
        assert legacy_call.args[0] == shimmed_call.args[0]  # stream_key
        assert legacy_call.kwargs == shimmed_call.kwargs
        # "event" JSON differs only in fields unaffected by the shim (ts is
        # the only per-call variable — both dispatched the same event kind
        # sequence against the same fake messages).
        import json as _json
        legacy_event = _json.loads(legacy_call.args[1]["event"])
        shimmed_event = _json.loads(shimmed_call.args[1]["event"])
        assert legacy_event["kind"] == shimmed_event["kind"]
        assert legacy_event["run_id"] == shimmed_event["run_id"]
        assert legacy_event["node_id"] == shimmed_event["node_id"]
        assert legacy_event["payload"] == shimmed_event["payload"]


@pytest.mark.asyncio
async def test_dispatch_folds_events_into_host_when_present(monkeypatch, tmp_path):
    disp = _make_dispatcher(monkeypatch)
    host = SessionHost(RUN_ID)

    result = await _run_dispatch(disp, monkeypatch, tmp_path, session_host=host)

    assert isinstance(result, ResearchOutput)
    dispatch_state = host.state.nodes["research"].dispatch
    assert dispatch_state.status == "completed"
    assert dispatch_state.message_count >= 1


@pytest.mark.asyncio
async def test_actions_xadd_failure_does_not_break_legacy(monkeypatch, tmp_path):
    """A broken SessionHost must never break the dispatch or its legacy XADD."""
    disp = _make_dispatcher(monkeypatch)

    class _BrokenHost:
        def apply(self, action):
            raise RuntimeError("session-state fold blew up")

    result = await _run_dispatch(disp, monkeypatch, tmp_path, session_host=_BrokenHost())

    assert isinstance(result, ResearchOutput)
    # Legacy publish still fired for every event (queued/started/2 messages/completed).
    assert disp._fake_redis.xadd.await_count == 5


@pytest.mark.asyncio
async def test_dispatch_without_session_host_is_legacy_only(monkeypatch, tmp_path):
    disp = _make_dispatcher(monkeypatch)
    result = await _run_dispatch(disp, monkeypatch, tmp_path, session_host=None)

    assert isinstance(result, ResearchOutput)
    assert disp._fake_redis.xadd.await_count == 5


@pytest.mark.asyncio
async def test_dispatch_session_host_ctx_isolated_across_concurrent_dispatches(monkeypatch, tmp_path):
    """Two concurrent dispatch() calls on the SAME instance never cross-contaminate hosts."""
    import asyncio

    disp = _make_dispatcher(monkeypatch)
    host_a = SessionHost("run-a")
    host_b = SessionHost("run-b")

    async def _dispatch_for(run_id, host):
        messages = [
            _AssistantMessage(content=[_TextBlock(_research_payload())]),
            _ResultMessage(success=True),
        ]
        fake_client = _FakeClient(messages)
        # NOTE: LLMFactory.create is monkeypatched once, shared across both
        # concurrent calls — fine, it just returns a fresh fake client here.
        monkeypatch.setattr(
            "parrot.flows.dev_loop.dispatchers.claude.LLMFactory.create",
            lambda *a, **kw: fake_client,
        )
        brief = ResearchOutput(
            jira_issue_key="OPS-0", spec_path="x", feat_id="FEAT-0",
            branch_name="b", worktree_path=str(tmp_path),
        )
        return await disp.dispatch(
            brief=brief, profile=ClaudeCodeDispatchProfile(),
            output_model=ResearchOutput, run_id=run_id, node_id="research",
            cwd=str(tmp_path), session_host=host,
        )

    await asyncio.gather(
        _dispatch_for("run-a", host_a),
        _dispatch_for("run-b", host_b),
    )

    assert host_a.state.nodes["research"].dispatch.status == "completed"
    assert host_b.state.nodes["research"].dispatch.status == "completed"
    assert host_a.state.run_id == "run-a"
    assert host_b.state.run_id == "run-b"


# ---------------------------------------------------------------------------
# Sanity: session_channel helper still importable/usable in this test module
# (guards against an accidental import-shape regression in session_state.py).
# ---------------------------------------------------------------------------


def test_session_channel_sanity():
    assert session_channel(RUN_ID) == f"parrot-session:/{RUN_ID}"


# ---------------------------------------------------------------------------
# Regression: _SESSION_HOST_CTX must reset even on the pre-semaphore
# early-exit path (code-review finding — cwd validation used to raise
# BEFORE the try/finally that resets the contextvar).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_host_ctx_reset_on_cwd_validation_failure(monkeypatch, tmp_path):
    disp = _make_dispatcher(monkeypatch)
    host = SessionHost(RUN_ID)

    # cwd outside WORKTREE_BASE_PATH (never patched in this test) makes
    # _enforce_cwd_under_worktree_base raise BEFORE the semaphore/try block
    # that owns the "normal" reset.
    with pytest.raises(DispatchExecutionError):
        await disp.dispatch(
            brief=ResearchOutput(
                jira_issue_key="OPS-0", spec_path="x", feat_id="FEAT-0",
                branch_name="b", worktree_path=str(tmp_path),
            ),
            profile=ClaudeCodeDispatchProfile(),
            output_model=ResearchOutput,
            run_id=RUN_ID,
            node_id="research",
            cwd="/definitely/not/under/worktree/base",
            session_host=host,
        )

    # The contextvar must NOT still be bound to `host` after the raise —
    # confirms the fix actually resets on this path instead of leaking.
    assert _SESSION_HOST_CTX.get() is None
