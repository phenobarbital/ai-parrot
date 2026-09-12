"""Tests for DevLoopDispatchService (TASK-3204) with fakes for process/channel/tail and a NullTransport."""

from __future__ import annotations

import asyncio
import time

import pytest

from parrot.integrations.devloop import service as svc
from parrot.integrations.devloop.models import (
    BridgeResult,
    DevLoopCommand,
    DevLoopError,
    DevLoopIntegrationConfig,
    NotRunOwnerError,
    Requester,
    RunEvent,
    RunNotFoundError,
    RunRecord,
)
from parrot.integrations.devloop.transport import NullTransport

_REQ = Requester(transport="slack", tenant_id="T", user_id="U1")
_OTHER = Requester(transport="slack", tenant_id="T", user_id="U2")


class _FakeHandshake:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.command_endpoint = "unix:///tmp/x.sock"
        self.kind = "bug"
        self.pid = 4242


class _FakeProc:
    """Fake HeadlessRunProcess. Uses an asyncio.Event (lazily loop-bound, safe to
    construct in a sync fixture) rather than a Future built via get_event_loop(),
    which can bind to the wrong loop when constructed outside a running one."""

    pid = 4242

    def __init__(self) -> None:
        self.terminated = False
        self.cleaned_up = False
        self._exit_code: int = 0
        self._exited = asyncio.Event()

    async def wait_ready(self, timeout: float):
        return _FakeHandshake("run-x")

    async def wait(self) -> int:
        await self._exited.wait()
        return self._exit_code

    def stderr_tail(self) -> str:
        return "tail"

    async def terminate(self, grace: float = 10.0) -> None:
        self.terminated = True
        if not self._exited.is_set():
            self._exit_code = -15
            self._exited.set()

    def cleanup(self) -> None:
        self.cleaned_up = True

    def set_exit_code(self, code: int) -> None:
        """Test helper: simulate the child exiting on its own with ``code``."""
        self._exit_code = code
        self._exited.set()


class _FakeTail:
    """Fake RunStateTail — tests feed events via a per-run_id asyncio.Queue."""

    queues: dict = {}

    def __init__(self, redis, run_id) -> None:
        self.run_id = run_id
        self._queue = _FakeTail.queues.setdefault(run_id, asyncio.Queue())
        self.closed = False

    async def events(self, *, last_seen=None):
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        self.closed = True
        await self._queue.put(None)


class _FakeChannel:
    def __init__(self, endpoint: str, *, token: str, timeout: float = 10.0) -> None:
        self.endpoint = endpoint
        self.token = token
        self.resolved: list = []
        self.cancelled: list = []
        self.probe_result = True

    async def resolve_gate(self, run_id, gate_id, *, resolution, resolved_by, comment="", answers=None):
        self.resolved.append((run_id, gate_id, resolution, resolved_by, answers))
        return BridgeResult(ok=True, status=200)

    async def cancel(self, run_id, *, requested_by):
        self.cancelled.append((run_id, requested_by))
        return BridgeResult(ok=True, status=200)

    async def probe(self) -> bool:
        return self.probe_result


async def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(interval)


async def _tail_queue(run_id: str, timeout: float = 2.0) -> "asyncio.Queue":
    """Wait for the background _tail() task to construct its _FakeTail (and queue)."""
    await _wait_until(lambda: run_id in _FakeTail.queues, timeout=timeout)
    return _FakeTail.queues[run_id]


@pytest.fixture(autouse=True)
def _reset_fake_tail_queues():
    _FakeTail.queues.clear()
    yield
    _FakeTail.queues.clear()


@pytest.fixture
def service(fake_redis, monkeypatch, tmp_path):
    cfg = DevLoopIntegrationConfig(
        name="t",
        enabled=True,
        repo_path=str(tmp_path),
        socket_dir=str(tmp_path),
        cancel_grace_seconds=0.05,
        tail_drain_seconds=0.05,
        default_acceptance_criteria=[{"kind": "shell", "name": "u", "command": "pytest -q"}],
    )
    proc = _FakeProc()

    async def _spawn(**kw):
        return proc

    monkeypatch.setattr(svc.HeadlessRunProcess, "spawn", _spawn)
    monkeypatch.setattr(svc, "RunStateTail", _FakeTail)
    monkeypatch.setattr(svc, "LoopbackRestChannel", _FakeChannel)

    async def _resolver(requester):
        return "rep@x", "esc@x"

    s = svc.DevLoopDispatchService(config=cfg, transport=NullTransport(), redis=fake_redis, identity_resolver=_resolver)
    return s, proc


async def _dispatch_and_confirm(s, *, kind="feature", prompt="Build the thing. Now", requester=_REQ) -> RunRecord:
    pid = await s.dispatch(DevLoopCommand(action="dispatch", type=kind, prompt=prompt), requester, "C1")
    return await s.confirm(pid, requester)


@pytest.mark.asyncio
async def test_dispatch_confirms_before_spawn(service):
    s, proc = service
    pid = await s.dispatch(DevLoopCommand(action="dispatch", type="feature", prompt="Build the thing. Now"), _REQ, "C1")
    assert s.transport.calls[-1][0] == "post_confirm"
    assert s._processes == {}
    with pytest.raises(NotRunOwnerError):
        await s.confirm(pid, _OTHER)
    record = await s.confirm(pid, _REQ)
    assert record.phase in ("starting", "running")
    assert record.thread_ts == f"thread-{record.run_id}"


@pytest.mark.asyncio
async def test_bug_dispatch_uses_identity_resolver(service):
    s, proc = service
    record = await _dispatch_and_confirm(s, kind="bug", prompt="A long enough bug summary")
    assert record.kind == "bug"
    # WorkBrief.reporter/escalation_assignee came from the resolver, never a raw Slack id.
    pending_calls = [c for c in s.transport.calls if c[0] == "post_confirm"]
    assert pending_calls


@pytest.mark.asyncio
async def test_non_owner_cannot_answer_or_cancel(service):
    s, proc = service
    record = await _dispatch_and_confirm(s)
    with pytest.raises(NotRunOwnerError):
        await s.answer_gate(record.run_id, "oq-1", _OTHER, {"q": "a"})
    with pytest.raises(NotRunOwnerError):
        await s.cancel(record.run_id, _OTHER)


@pytest.mark.asyncio
async def test_owner_can_answer_gate(service):
    s, proc = service
    record = await _dispatch_and_confirm(s)
    result = await s.answer_gate(record.run_id, "oq-1", _REQ, {"q": "a"})
    assert result.ok


@pytest.mark.asyncio
async def test_cancel_escalates_to_terminate_without_terminal_event(service):
    s, proc = service
    record = await _dispatch_and_confirm(s)
    result = await s.cancel(record.run_id, _REQ)
    assert result.ok
    await _wait_until(lambda: proc.terminated, timeout=2.0)


@pytest.mark.asyncio
async def test_gate_opened_posts_gate_and_sets_pending(service):
    s, proc = service
    record = await _dispatch_and_confirm(s)
    event = RunEvent(
        run_id=record.run_id,
        kind="gate_opened",
        seq=1,
        gate={"gate_id": "oq-1", "kind": "open_questions", "title": "Open questions — x", "questions": ["Q?"]},
    )
    queue = await _tail_queue(record.run_id)
    await queue.put(event)
    await _wait_until(lambda: s.pending_gate(record.run_id) is not None)
    assert s.record(record.run_id).pending_gate_id == "oq-1"
    assert any(c[0] == "post_gate" for c in s.transport.calls)


@pytest.mark.asyncio
async def test_run_closed_posts_terminal_and_marks_terminal(service):
    s, proc = service
    record = await _dispatch_and_confirm(s)
    event = RunEvent(
        run_id=record.run_id, kind="run_closed", seq=2, state={"outcome": "succeeded", "pr_url": "http://pr"}
    )
    queue = await _tail_queue(record.run_id)
    await queue.put(event)
    await _wait_until(lambda: s.record(record.run_id).phase == "completed")
    assert s.record(record.run_id).pr_url == "http://pr"
    assert await s.registry.live() == []
    assert any(c[0] == "post_terminal" for c in s.transport.calls)


@pytest.mark.asyncio
async def test_process_exit_without_terminal_becomes_process_exited(service):
    s, proc = service
    record = await _dispatch_and_confirm(s)
    proc.set_exit_code(1)  # child exits without ever publishing a terminal action
    await _wait_until(lambda: s.record(record.run_id).phase == "failed", timeout=2.0)
    assert s.record(record.run_id).exit_code == 1
    assert proc.cleaned_up


@pytest.mark.asyncio
async def test_start_reattaches_live_record_with_reachable_channel(fake_redis, monkeypatch, tmp_path):
    cfg = DevLoopIntegrationConfig(name="t", enabled=True, repo_path=str(tmp_path), socket_dir=str(tmp_path))
    monkeypatch.setattr(svc, "RunStateTail", _FakeTail)
    monkeypatch.setattr(svc, "LoopbackRestChannel", _FakeChannel)
    s = svc.DevLoopDispatchService(config=cfg, transport=NullTransport(), redis=fake_redis)

    live_record = RunRecord(
        run_id="run-live1",
        kind="bug",
        title="t",
        requester=_REQ,
        channel_id="C1",
        command_endpoint="unix:///tmp/live.sock",
        command_token="tok",
        phase="running",
        started_at=time.time(),
    )
    await s.registry.save(live_record)

    await s.start()
    assert any(t.get_name() == "devloop-tail-run-live1" for t in s._tasks)
    await s.stop()


@pytest.mark.asyncio
async def test_start_marks_unreachable_record_failed(fake_redis, monkeypatch, tmp_path):
    cfg = DevLoopIntegrationConfig(name="t", enabled=True, repo_path=str(tmp_path), socket_dir=str(tmp_path))

    class _UnreachableChannel(_FakeChannel):
        async def probe(self) -> bool:
            return False

    monkeypatch.setattr(svc, "LoopbackRestChannel", _UnreachableChannel)
    s = svc.DevLoopDispatchService(config=cfg, transport=NullTransport(), redis=fake_redis)

    live_record = RunRecord(
        run_id="run-dead1",
        kind="bug",
        title="t",
        requester=_REQ,
        channel_id="C1",
        command_endpoint="unix:///tmp/dead.sock",
        command_token="tok",
        phase="running",
        started_at=time.time(),
    )
    await s.registry.save(live_record)

    await s.start()
    assert (await s.registry.get("run-dead1")).phase == "failed"
    assert await s.registry.live() == []


@pytest.mark.asyncio
async def test_pending_confirmation_expires_after_ttl(service, monkeypatch):
    s, proc = service
    pid = await s.dispatch(DevLoopCommand(action="dispatch", type="feature", prompt="Build the thing. Now"), _REQ, "C1")
    s._pending[pid].expires_at = time.time() - 1  # force expiry
    with pytest.raises(RunNotFoundError):
        await s.confirm(pid, _REQ)


@pytest.mark.asyncio
async def test_max_concurrent_runs_none_never_blocks(service):
    s, proc = service
    assert s.config.max_concurrent_runs is None
    s._check_capacity()  # must not raise


@pytest.mark.asyncio
async def test_max_concurrent_runs_enforced(service):
    s, proc = service
    s.config.max_concurrent_runs = 0
    with pytest.raises(DevLoopError):
        await s.dispatch(DevLoopCommand(action="dispatch", type="feature", prompt="x"), _REQ, "C1")


@pytest.mark.asyncio
async def test_stop_never_terminates_children(service):
    s, proc = service
    await _dispatch_and_confirm(s)
    await s.stop()
    assert proc.terminated is False
