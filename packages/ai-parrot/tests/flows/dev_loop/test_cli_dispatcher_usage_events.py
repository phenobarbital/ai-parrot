"""Unit tests for FEAT-479 Module 6 — CLI dispatchers emit AfterClientCallEvent
after harvest.

``ClaudeCodeDispatcher`` runs out of process: there is no ``AbstractClient``,
so none of ``clients/base.py``'s lifecycle emission happens. This module
covers routing the harvested terminal-``ResultMessage`` usage
(``_extract_result_usage``) through the same accounting path in-process
clients use, keyed by a free-string seat — fixing spec Finding 3
(pool-worker seats silently dropped) and Finding 4's model gap for this
backend.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from navigator_eventbus.lifecycle.registry import EventRegistry
from parrot.flows.dev_loop import (
    ClaudeCodeDispatcher,
    ClaudeCodeDispatchProfile,
    ResearchOutput,
)
from parrot.observability.recorders.run_ledger import RunLedgerRecorder
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _AssistantMessage:
    def __init__(self, content: list[Any]) -> None:
        self.content = content


class _UsageObj:
    """Object-shaped ``usage`` (attributes instead of dict keys)."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _ResultMessage:
    """Terminal-ResultMessage duck-type carrying usage (mirrors
    test_dispatch_telemetry.py's fake)."""

    def __init__(
        self,
        *,
        is_error: bool = False,
        usage: Any = None,
        total_cost_usd: Any = None,
        num_turns: int = 1,
        duration_ms: Any = None,
    ) -> None:
        self.subtype = "success"
        self.is_error = is_error
        self.api_error_status = None
        self.result = None
        self.num_turns = num_turns
        self.permission_denials = None
        self.usage = usage
        self.total_cost_usd = total_cost_usd
        self.duration_ms = duration_ms


class _FakeClient:
    def __init__(self, messages: list[Any]) -> None:
        self._messages = messages

    async def stream_messages(self, prompt: str, *, run_options: Any) -> AsyncIterator[Any]:
        for msg in self._messages:
            yield msg


def _make_research_payload() -> str:
    return (
        '{"jira_issue_key":"OPS-1","spec_path":"sdd/specs/x.spec.md",'
        '"feat_id":"FEAT-130","branch_name":"feat-130-fix",'
        '"worktree_path":"/abs/.claude/worktrees/feat-130-fix",'
        '"log_excerpts":[]}'
    )


@pytest.fixture(autouse=True)
def _patch_worktree_base(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.claude.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    return tmp_path


@pytest.fixture
def brief(_patch_worktree_base) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-0",
        spec_path="x",
        feat_id="FEAT-0",
        branch_name="b",
        worktree_path=str(_patch_worktree_base),
    )


@pytest.fixture
def ledger() -> RunLedgerRecorder:
    return RunLedgerRecorder(run_id="run-1")


@pytest.fixture
def run_registry(ledger) -> EventRegistry:
    registry = EventRegistry(forward_to_global=False)
    registry.add_provider(UsageRecordingSubscriber(recorders=[ledger], cost_calculator=None))
    return registry


def _dispatcher(monkeypatch, messages, *, registry=None) -> ClaudeCodeDispatcher:
    disp = ClaudeCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _ensure_redis():
        return fake_redis

    monkeypatch.setattr(disp, "_ensure_redis", _ensure_redis)
    fake_client = _FakeClient(messages)
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.claude.LLMFactory.create",
        lambda *a, **kw: fake_client,
    )
    if registry is not None:
        disp.set_event_registry_resolver({"run-1": registry}.get)
    return disp


async def test_claude_dispatch_emits_after_call_with_model(
    monkeypatch, brief, _patch_worktree_base, run_registry, ledger
):
    """Out-of-process usage must reach the ledger with its real model."""
    messages = [
        _AssistantMessage(content=[_TextBlock(_make_research_payload())]),
        _ResultMessage(
            usage={"input_tokens": 100, "output_tokens": 50},
            duration_ms=1200,
        ),
    ]
    dispatcher = _dispatcher(monkeypatch, messages, registry=run_registry)

    await dispatcher.dispatch(
        brief=brief,
        profile=ClaudeCodeDispatchProfile(model="claude-opus-5"),
        output_model=ResearchOutput,
        run_id="run-1",
        node_id="development",
        cwd=str(_patch_worktree_base),
    )

    (rec,) = ledger.records
    assert rec.model == "claude-opus-5"
    assert rec.input_tokens == 100
    assert rec.output_tokens == 50
    assert rec.seat == "development"


async def test_pool_worker_seat_reaches_ledger(monkeypatch, brief, _patch_worktree_base, run_registry, ledger):
    """Regression guard for FEAT-479 Finding 3: 'development.w1' cannot
    validate against the closed NodeId Literal, so _apply_to_session_host
    swallowed it at DEBUG and all fan-out usage was lost."""
    messages = [
        _AssistantMessage(content=[_TextBlock(_make_research_payload())]),
        _ResultMessage(usage={"input_tokens": 10, "output_tokens": 5}),
    ]
    dispatcher = _dispatcher(monkeypatch, messages, registry=run_registry)

    await dispatcher.dispatch(
        brief=brief,
        profile=ClaudeCodeDispatchProfile(),
        output_model=ResearchOutput,
        run_id="run-1",
        node_id="development.w1",
        cwd=str(_patch_worktree_base),
    )

    (rec,) = ledger.records
    assert rec.seat == "development.w1"
    assert rec.node_id == "development"


async def test_no_usage_no_event(monkeypatch, brief, _patch_worktree_base, run_registry, ledger):
    """No harvest -> no event. '—' is honest; 0 is a lie."""
    messages = [
        _AssistantMessage(content=[_TextBlock(_make_research_payload())]),
        _ResultMessage(usage=None, total_cost_usd=None, duration_ms=None),
    ]
    messages[1].num_turns = None  # force "nothing extractable" in the harvest
    dispatcher = _dispatcher(monkeypatch, messages, registry=run_registry)

    await dispatcher.dispatch(
        brief=brief,
        profile=ClaudeCodeDispatchProfile(),
        output_model=ResearchOutput,
        run_id="run-1",
        node_id="qa",
        cwd=str(_patch_worktree_base),
    )

    assert ledger.records == []


async def test_usage_as_object_and_as_dict(monkeypatch, brief, _patch_worktree_base, run_registry, ledger):
    """The harvest docstring promises both shapes are supported."""
    messages = [
        _AssistantMessage(content=[_TextBlock(_make_research_payload())]),
        _ResultMessage(usage=_UsageObj(input_tokens=20, output_tokens=8)),
    ]
    dispatcher = _dispatcher(monkeypatch, messages, registry=run_registry)

    await dispatcher.dispatch(
        brief=brief,
        profile=ClaudeCodeDispatchProfile(),
        output_model=ResearchOutput,
        run_id="run-1",
        node_id="qa",
        cwd=str(_patch_worktree_base),
    )

    (rec,) = ledger.records
    assert rec.input_tokens == 20
    assert rec.output_tokens == 8


async def test_telemetry_failure_does_not_break_dispatch(monkeypatch, brief, _patch_worktree_base):
    """A raising registry must not fail the dispatch."""
    messages = [
        _AssistantMessage(content=[_TextBlock(_make_research_payload())]),
        _ResultMessage(usage={"input_tokens": 1, "output_tokens": 1}),
    ]

    class _BrokenRegistry:
        async def emit(self, event):
            raise RuntimeError("boom")

    dispatcher = _dispatcher(monkeypatch, messages, registry=_BrokenRegistry())

    result = await dispatcher.dispatch(
        brief=brief,
        profile=ClaudeCodeDispatchProfile(),
        output_model=ResearchOutput,
        run_id="run-1",
        node_id="qa",
        cwd=str(_patch_worktree_base),
    )
    assert result is not None


async def test_no_resolver_wired_does_not_break_dispatch(monkeypatch, brief, _patch_worktree_base):
    """A dispatcher not owned by a DevLoopRunner (no resolver ever wired)
    must dispatch successfully — no event emitted, no error."""
    messages = [
        _AssistantMessage(content=[_TextBlock(_make_research_payload())]),
        _ResultMessage(usage={"input_tokens": 1, "output_tokens": 1}),
    ]
    dispatcher = _dispatcher(monkeypatch, messages)  # no registry= kwarg

    result = await dispatcher.dispatch(
        brief=brief,
        profile=ClaudeCodeDispatchProfile(),
        output_model=ResearchOutput,
        run_id="run-1",
        node_id="qa",
        cwd=str(_patch_worktree_base),
    )
    assert result is not None


# ---------------------------------------------------------------------------
# Failure paths — every branch of dispatch() must reach the ledger, not
# only the success path (code-review finding: the first version of this
# module only wired the success completion, silently dropping every
# failed-dispatch record and contradicting the "every failed node/LLM
# call appears in the report" acceptance criterion).
# ---------------------------------------------------------------------------


async def test_timeout_failure_reaches_ledger(monkeypatch, brief, _patch_worktree_base, run_registry, ledger):
    """A wall-clock timeout must still produce a failed ledger record."""
    import asyncio

    class _SlowClient:
        async def stream_messages(self, prompt: str, *, run_options: Any):
            await asyncio.sleep(5)
            yield  # pragma: no cover

    disp = ClaudeCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")
    monkeypatch.setattr(disp, "_ensure_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.claude.LLMFactory.create",
        lambda *a, **kw: _SlowClient(),
    )
    disp.set_event_registry_resolver({"run-1": run_registry}.get)

    real_timeout = asyncio.timeout
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.claude.asyncio.timeout",
        lambda _seconds: real_timeout(0.05),
    )

    from parrot.flows.dev_loop import DispatchExecutionError

    with pytest.raises(DispatchExecutionError):
        await disp.dispatch(
            brief=brief,
            profile=ClaudeCodeDispatchProfile(timeout_seconds=60),
            output_model=ResearchOutput,
            run_id="run-1",
            node_id="qa",
            cwd=str(_patch_worktree_base),
        )

    (rec,) = ledger.records
    assert rec.status == "failed"
    assert rec.error_type == "TimeoutError"


async def test_session_failure_reaches_ledger_with_partial_usage(
    monkeypatch, brief, _patch_worktree_base, run_registry, ledger
):
    """A session failure after a usage-bearing ResultMessage must retain
    BOTH the tokens burned and the failure — two ledger records, since
    ClientCallFailedEvent structurally carries no token fields."""
    partial_result = _ResultMessage(usage={"input_tokens": 900, "output_tokens": 100})

    class _ErrAfterResultClient:
        async def stream_messages(self, prompt: str, *, run_options: Any):
            yield partial_result
            raise RuntimeError("transport lost")

    disp = ClaudeCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")
    monkeypatch.setattr(disp, "_ensure_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.claude.LLMFactory.create",
        lambda *a, **kw: _ErrAfterResultClient(),
    )
    disp.set_event_registry_resolver({"run-1": run_registry}.get)

    from parrot.flows.dev_loop import DispatchExecutionError

    with pytest.raises(DispatchExecutionError):
        await disp.dispatch(
            brief=brief,
            profile=ClaudeCodeDispatchProfile(),
            output_model=ResearchOutput,
            run_id="run-1",
            node_id="qa",
            cwd=str(_patch_worktree_base),
        )

    assert len(ledger.records) == 2
    completed = next(r for r in ledger.records if r.status == "completed")
    failed = next(r for r in ledger.records if r.status == "failed")
    assert completed.input_tokens == 900
    assert completed.output_tokens == 100
    assert failed.error_type == "RuntimeError"


async def test_result_error_without_raise_reaches_ledger(
    monkeypatch, brief, _patch_worktree_base, run_registry, ledger
):
    """An is_error ResultMessage the SDK doesn't raise on must still fail
    the ledger record, not just the dispatch."""
    err_result = _ResultMessage(is_error=True)
    err_result.num_turns = None  # nothing harvestable -> no extra AfterClientCallEvent

    disp = ClaudeCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")
    monkeypatch.setattr(disp, "_ensure_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.claude.LLMFactory.create",
        lambda *a, **kw: _FakeClient([err_result]),
    )
    disp.set_event_registry_resolver({"run-1": run_registry}.get)

    from parrot.flows.dev_loop import DispatchExecutionError

    with pytest.raises(DispatchExecutionError):
        await disp.dispatch(
            brief=brief,
            profile=ClaudeCodeDispatchProfile(),
            output_model=ResearchOutput,
            run_id="run-1",
            node_id="qa",
            cwd=str(_patch_worktree_base),
        )

    (rec,) = ledger.records
    assert rec.status == "failed"
    assert rec.error_type == "ResultError"


async def test_output_validation_failure_reaches_ledger(monkeypatch, brief, _patch_worktree_base, run_registry, ledger):
    """A successful stream whose final payload fails JSON/schema
    validation must still reach the ledger as a failure."""
    messages = [_AssistantMessage(content=[_TextBlock("not valid json")])]

    disp = ClaudeCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")
    monkeypatch.setattr(disp, "_ensure_redis", AsyncMock(return_value=fake_redis))
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.claude.LLMFactory.create",
        lambda *a, **kw: _FakeClient(messages),
    )
    disp.set_event_registry_resolver({"run-1": run_registry}.get)

    from parrot.flows.dev_loop import DispatchOutputValidationError

    with pytest.raises(DispatchOutputValidationError):
        await disp.dispatch(
            brief=brief,
            profile=ClaudeCodeDispatchProfile(),
            output_model=ResearchOutput,
            run_id="run-1",
            node_id="qa",
            cwd=str(_patch_worktree_base),
        )

    (rec,) = ledger.records
    assert rec.status == "failed"
    assert rec.error_type == "DispatchOutputValidationError"


async def test_after_call_forwards_to_global_registry(monkeypatch, brief, _patch_worktree_base):
    """A successful dispatch's usage event must reach the GLOBAL registry
    too (explicit forward_to_global), not only the per-run one — the
    per-run registry is forward_to_global=False by design."""
    import asyncio

    from navigator_eventbus.lifecycle.global_registry import get_global_registry
    from parrot.core.events.lifecycle.events.client import AfterClientCallEvent

    messages = [
        _AssistantMessage(content=[_TextBlock(_make_research_payload())]),
        _ResultMessage(usage={"input_tokens": 5, "output_tokens": 2}),
    ]
    global_seen: list[Any] = []

    async def _capture(event):
        global_seen.append(event)

    sub_id = get_global_registry().subscribe(AfterClientCallEvent, _capture)
    try:
        ledger = RunLedgerRecorder(run_id="run-1")
        registry = EventRegistry(forward_to_global=False)
        registry.add_provider(UsageRecordingSubscriber(recorders=[ledger], cost_calculator=None))
        dispatcher = _dispatcher(monkeypatch, messages, registry=registry)

        await dispatcher.dispatch(
            brief=brief,
            profile=ClaudeCodeDispatchProfile(),
            output_model=ResearchOutput,
            run_id="run-1",
            node_id="qa",
            cwd=str(_patch_worktree_base),
        )
        for _ in range(3):
            await asyncio.sleep(0)  # let the forward_to_global task run
    finally:
        get_global_registry().unsubscribe(sub_id)

    assert global_seen, "the global registry never saw the forwarded event"
