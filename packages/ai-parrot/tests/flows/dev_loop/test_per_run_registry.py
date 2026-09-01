"""Unit tests for FEAT-479 Module 5 — per-run EventRegistry ownership.

This is the feature's single most important correctness constraint
(spec §2 Exactness): a sink subscribed on the registry an emitter awaits
``emit()`` on is guaranteed complete when that ``await`` returns. A sink
reachable only via ``forward_to_global()``/``emit_nowait()`` races the
report — this module's first test is the regression guard for that.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from navigator_eventbus.lifecycle.global_registry import get_global_registry
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.clients.base import AbstractClient
from parrot.core.events.lifecycle.events import AfterClientCallEvent
from parrot.flows.dev_loop import (
    BugBrief,
    DevelopmentOutput,
    DevLoopRunner,
    LLMCodeDispatcher,
    LLMCodeDispatchProfile,
    ResearchOutput,
    ShellCriterion,
    build_dev_loop_flow,
)
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.observability.recorders.run_ledger import RunLedgerRecorder
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber


def _after_call_event(*, input_tokens: int, output_tokens: int) -> AfterClientCallEvent:
    return AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o",
        duration_ms=100.0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


async def test_recorder_receives_before_call_returns():
    """THE exactness constraint. emit() awaits subscribers sequentially, so
    the ledger must be populated the instant the emitting call returns —
    no sleep, no drain. If this test needed either, the ledger would be on
    the wrong registry and accounting would race the report."""
    ledger = RunLedgerRecorder(run_id="run-1")
    registry = EventRegistry(forward_to_global=False)
    registry.add_provider(UsageRecordingSubscriber(recorders=[ledger], cost_calculator=None))

    await registry.emit(_after_call_event(input_tokens=10, output_tokens=5))

    assert len(ledger.records) == 1  # NO await asyncio.sleep(0) here


# ---------------------------------------------------------------------------
# End-to-end: DevLoopRunner owns one registry per run, never global.
# ---------------------------------------------------------------------------


@pytest.fixture
def brief() -> BugBrief:
    return BugBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[
            ShellCriterion(name="lint", command="ruff check ."),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


def _research_output(tmp_path):
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(tmp_path / "feat-130-fix"),
        log_excerpts=[],
    )


@pytest.fixture
def mock_jira():
    j = MagicMock()
    j.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    j.jira_get_issue = AsyncMock(return_value={"status": "error"})
    j.jira_search_issues = AsyncMock(return_value={"status": "empty"})
    j.jira_transition_issue = AsyncMock(return_value={"ok": True})
    j.jira_transition_to = AsyncMock(return_value={"ok": True})
    j.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    j.jira_assign_issue = AsyncMock(return_value={"ok": True})
    return j


@pytest.fixture
def patch_handoff(monkeypatch):
    monkeypatch.setattr(DeploymentHandoffNode, "_push_branch", AsyncMock(return_value=None))
    monkeypatch.setattr(
        DeploymentHandoffNode,
        "_create_pr",
        AsyncMock(return_value="https://github.com/x/y/pull/1"),
    )


@pytest.fixture
def patch_worktree_base(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    return tmp_path


def _dispatcher_returning(research_out, qa_passed: bool = True):
    from parrot import conf
    from parrot.flows.dev_loop import QAReport

    async def dispatch(*, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        if output_model is type(research_out):
            return research_out
        if output_model is DevelopmentOutput:
            return DevelopmentOutput(
                files_changed=["x.py"],
                commit_shas=["abc123"],
                summary="fixed",
            )
        if output_model is QAReport:
            return QAReport(
                passed=qa_passed,
                criterion_results=[],
                lint_passed=qa_passed,
                attempt=1 if qa_passed else int(conf.DEV_LOOP_QA_MAX_RETRIES),
            )
        raise AssertionError(f"unexpected output_model {output_model}")

    d = MagicMock()
    d.dispatch = AsyncMock(side_effect=dispatch)
    return d


@pytest.fixture
def dev_loop_runner(mock_jira, patch_handoff, patch_worktree_base):
    dispatcher = _dispatcher_returning(_research_output(patch_worktree_base))
    flow = build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=mock_jira,
        log_toolkits={},
        redis_url="redis://localhost:6399/9",  # never connected in tests
        publish_flow_events=False,
    )
    return DevLoopRunner(flow, max_concurrent_runs=2)


async def test_subscriber_not_registered_globally(dev_loop_runner, brief):
    """Spec §8 Q2: per-run scope only, and the global pipeline untouched."""
    before = len(get_global_registry()._subscriptions)

    await dev_loop_runner.run(brief, run_id="run-registry-scope")

    after = get_global_registry()._subscriptions
    assert len(after) == before, "a per-run subscription leaked to the global registry"
    for sub in after:
        target = getattr(sub.callback, "__self__", None)
        recorders = getattr(target, "recorders", []) or []
        assert not any(
            isinstance(r, RunLedgerRecorder) for r in recorders
        ), "a RunLedgerRecorder is reachable from the global registry"


async def test_run_registry_created_and_discarded(dev_loop_runner, brief):
    """The per-run registry+ledger exist while the run is tracked and are
    released (no leak) once it closes."""
    rid = "run-registry-lifecycle"
    assert dev_loop_runner.get_run_ledger(rid) is None

    await dev_loop_runner.run(brief, run_id=rid)

    # Cleaned up after close — get_run_ledger reflects "not tracked" the
    # same way it does before the run ever started (no special-cased leak).
    assert dev_loop_runner.get_run_ledger(rid) is None
    assert rid not in dev_loop_runner._run_registries
    assert rid not in dev_loop_runner._run_ledgers


async def test_per_run_registries_are_distinct_instances(dev_loop_runner, brief):
    """Each run gets its OWN EventRegistry — never a shared singleton."""
    captured: dict[str, object] = {}
    orig = dev_loop_runner._discard_run_registry

    def _spy(run_id: str) -> None:
        captured[run_id] = dev_loop_runner._run_registries.get(run_id)
        orig(run_id)

    dev_loop_runner._discard_run_registry = _spy

    await dev_loop_runner.run(brief, run_id="run-a")
    await dev_loop_runner.run(brief, run_id="run-b")

    assert captured["run-a"] is not None
    assert captured["run-b"] is not None
    assert captured["run-a"] is not captured["run-b"]


# ---------------------------------------------------------------------------
# LLMCodeDispatcher._create_client injection (spec §8 open question).
# ---------------------------------------------------------------------------


class _Message:
    def __init__(self, *, content: str = "", tool_calls=()) -> None:
        self.content = content
        self.tool_calls = list(tool_calls)


class _Choice:
    def __init__(self, message: _Message) -> None:
        self.message = message


class _Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = prompt_tokens + completion_tokens

    def model_dump(self):
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


class _Response:
    def __init__(self, message: _Message, usage: _Usage | None = None) -> None:
        self.choices = [_Choice(message)]
        self.usage = usage


class _FinalOutputCall:
    """A single tool_call invoking ``final_output`` immediately."""

    id = "call_final"

    class function:  # mirrors the OpenAI SDK's tool_call.function shape
        name = "final_output"
        arguments = json.dumps({"files_changed": [], "commit_shas": [], "summary": "done"})


class _EmittingFakeClient(AbstractClient):
    """A real AbstractClient (genuine _emit_* trio, no I/O)."""

    client_name = "fake-emitting"

    def __init__(self, responses) -> None:
        super().__init__(debug=False)
        self.responses = list(responses)

    async def ask(self, prompt: str, model: str = "stub-model", **kw):  # type: ignore[override]
        raise NotImplementedError

    async def ask_stream(self, prompt: str, **kw):  # type: ignore[override]
        raise NotImplementedError
        yield  # pragma: no cover

    async def get_client(self):
        return None

    async def _ensure_client(self):
        pass

    async def invoke(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        raise NotImplementedError

    async def resume(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        raise NotImplementedError

    async def _chat_completion(self, **kwargs: Any) -> _Response:
        return self.responses.pop(0)


@pytest.fixture
def llm_worktree(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.dispatchers.llm.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    return tmp_path


async def test_create_client_injects_the_resolved_run_registry(monkeypatch, llm_worktree):
    """§8 resolved: LLMFactory.create/_client_factory does NOT propagate a
    registry (verified by reading factory.py + AbstractClient.__init__,
    clients/base.py:372 — it always self-creates a fresh, isolated one).
    LLMCodeDispatcher._create_client must therefore thread it explicitly.
    This proves the injected client's AWAITED emit() lands on the exact
    per-run ledger, with correct run_id/seat/node_id attribution from
    usage_attribution() — no sleep, no drain.
    """
    client = _EmittingFakeClient(
        [_Response(_Message(content="t1", tool_calls=[_FinalOutputCall()]), usage=_Usage(10, 5))]
    )
    ledger = RunLedgerRecorder(run_id="run-inject")
    registry = EventRegistry(forward_to_global=False)
    registry.add_provider(UsageRecordingSubscriber(recorders=[ledger], cost_calculator=None))

    def _client_factory(*args: Any, **kwargs: Any) -> Any:
        return client

    dispatcher = LLMCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
        client_factory=_client_factory,
    )
    dispatcher.set_event_registry_resolver({"run-inject": registry}.get)
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")
    monkeypatch.setattr(dispatcher, "_ensure_redis", AsyncMock(return_value=fake_redis))

    brief = ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(llm_worktree),
        log_excerpts=[],
    )

    result = await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(llm="fake:fake-model", max_turns=4),
        output_model=DevelopmentOutput,
        run_id="run-inject",
        node_id="development.w1",
        cwd=str(llm_worktree),
    )

    assert result is not None
    # The injected registry's client saw the SAME registry object — the
    # documented injection point (`_events_registry`), not a lazily
    # self-created isolated one.
    assert client._events_registry is registry

    (record,) = ledger.records  # exactness: no drain, no sleep needed
    assert record.run_id == "run-inject"
    assert record.seat == "development.w1"
    assert record.node_id == "development"  # rolled up
    assert record.input_tokens == 10
    assert record.output_tokens == 5


async def test_create_client_without_resolver_does_not_break(monkeypatch, llm_worktree):
    """No resolver wired (a dispatcher not owned by a DevLoopRunner, or
    used before wiring) must not raise — it degrades gracefully to the
    client's own isolated registry."""
    client = _EmittingFakeClient([_Response(_Message(content="t1", tool_calls=[_FinalOutputCall()]))])

    def _client_factory(*args: Any, **kwargs: Any) -> Any:
        return client

    dispatcher = LLMCodeDispatcher(
        max_concurrent=2,
        redis_url="redis://localhost:6379/0",
        stream_ttl_seconds=300,
        client_factory=_client_factory,
    )
    fake_redis = AsyncMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")
    monkeypatch.setattr(dispatcher, "_ensure_redis", AsyncMock(return_value=fake_redis))

    brief = ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(llm_worktree),
        log_excerpts=[],
    )

    result = await dispatcher.dispatch(
        brief=brief,
        profile=LLMCodeDispatchProfile(llm="fake:fake-model", max_turns=4),
        output_model=DevelopmentOutput,
        run_id="run-no-resolver",
        node_id="development",
        cwd=str(llm_worktree),
    )
    assert result is not None
