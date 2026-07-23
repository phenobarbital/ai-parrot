"""End-to-end integration tests — gated run, WS reconnect, crash rebuild.

FEAT-322 TASK-1856 (spec §4 Integration Tests). Drives a full initial-graph
dev-loop run (stub dispatcher, fake Jira/git toolkits, in-process Redis
Streams stub — no live services needed, following
``test_websocket_replay.py``'s / ``test_concurrency.py``'s precedent for
this ``integration/`` directory) through:

1. A blocking QA ``manual_criterion`` gate AND a ``deployment_approval``
   gate, both resolved via the REST command layer (TASK-1855).
2. The ``view="state"`` WS reconnect semantics (TASK-1854) against the
   SAME run's real actions stream.
3. Crash-rebuild — folding ``flow:{run_id}:actions`` from seq 0 reproduces
   the host's state, including a mid-run rebuild landing on
   ``awaiting_gate`` for a still-pending gate.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    DevLoopRunner,
    ManualCriterion,
    QAReport,
    ResearchOutput,
    ShellCriterion,
    build_dev_loop_flow,
)
from parrot.flows.dev_loop.commands import register_command_routes
from parrot.flows.dev_loop.models import CodeReviewVerdict, DevelopmentOutput
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.research import ResearchNode
from parrot.flows.dev_loop.session_state import (
    ActionEnvelope,
    DevLoopSessionState,
    reduce,
    session_channel,
)
from parrot.flows.dev_loop.streaming import FlowStreamMultiplexer

pytestmark = pytest.mark.live

RUN_ID = "run-e2e0001"


# ---------------------------------------------------------------------------
# wait_until — poll instead of sleeping-as-synchronization
# ---------------------------------------------------------------------------


async def wait_until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"condition not met within {timeout}s")


async def wait_until_stream(
    fake_redis: "_FakeStreamsRedis",
    run_id: str,
    predicate,
    timeout: float = 5.0,
) -> List[Tuple[str, Dict[str, str]]]:
    """Poll ``flow:{run_id}:actions`` until ``predicate(entries)`` is true.

    Code-review finding (flaky ``test_crash_rebuild_from_actions_stream``):
    ``SessionHost.apply()`` updates ``host.state`` SYNCHRONOUSLY, but the
    runner's envelope sink (``DevLoopRunner._make_envelope_sink``) fires the
    actual actions-stream XADD via a fire-and-forget
    ``asyncio.get_running_loop().create_task(...)`` — the write lands on a
    LATER event-loop iteration, not before the current await point returns.
    A test that polls ``host.state`` and then immediately reads
    ``fake_redis.xrange(...)`` can observe a state ahead of what's actually
    on the stream, especially under full-suite CPU contention (this is what
    made the crash-rebuild test intermittently fail 2/5 runs). Polling the
    STREAM itself for the expected condition (rather than trusting one
    ``host.state``-gated read) removes the race.
    """
    deadline = time.monotonic() + timeout
    entries: List[Tuple[str, Dict[str, str]]] = []
    while time.monotonic() < deadline:
        entries = await fake_redis.xrange(_actions_key(run_id))
        if predicate(entries):
            return entries
        await asyncio.sleep(0.01)
    pytest.fail(
        f"actions-stream condition not met within {timeout}s "
        f"(last saw {len(entries)} entries)"
    )


# ---------------------------------------------------------------------------
# In-process fake Redis Streams (actions stream) — no live Redis needed
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
            collected = [(eid, f) for eid, f in entries if eid > cursor]
            if collected:
                result.append((key, collected))
        if not result and block:
            await asyncio.sleep(min(block / 1000.0, 0.05))
        return result

    async def delete(self, *_keys: str) -> int:
        return 0

    async def aclose(self) -> None:
        return None


def _actions_key(run_id: str) -> str:
    return f"flow:{run_id}:actions"


# ---------------------------------------------------------------------------
# Stub dispatcher (canned outputs per node's output_model)
# ---------------------------------------------------------------------------


def _research_output(tmp_path) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-322",
        branch_name="feat-322-e2e",
        worktree_path=str(tmp_path / "feat-322-e2e"),
        log_excerpts=[],
    )


def _stub_dispatcher(research_out: ResearchOutput):
    async def dispatch(*, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        if output_model is ResearchOutput:
            return research_out
        if output_model is DevelopmentOutput:
            return DevelopmentOutput(
                files_changed=["x.py"], commit_shas=["abc123"],
                summary="implemented the fix",
            )
        if output_model is QAReport:
            return QAReport(passed=True, criterion_results=[], lint_passed=True)
        if output_model is CodeReviewVerdict:
            return CodeReviewVerdict(passed=True)
        raise AssertionError(f"unexpected output_model {output_model}")

    d = MagicMock()
    d.dispatch = AsyncMock(side_effect=dispatch)
    return d


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def brief() -> BugBrief:
    return BugBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[
            ShellCriterion(name="lint", command="ruff check ."),
            ManualCriterion(name="ux-check", text="dashboard renders cleanly", blocking=True),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def mock_jira() -> MagicMock:
    j = MagicMock()
    j.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    j.jira_get_issue = AsyncMock(return_value={"status": "error"})
    j.jira_search_issues = AsyncMock(return_value={"status": "empty"})
    j.jira_transition_issue = AsyncMock(return_value={"ok": True})
    j.jira_transition_to = AsyncMock(return_value={"ok": True})
    j.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    j.jira_assign_issue = AsyncMock(return_value={"ok": True})
    j.jira_find_user = AsyncMock(return_value=None)
    return j


@pytest.fixture(autouse=True)
def _patch_handoff(monkeypatch):
    """Neutralize git push / PR creation at class level (frozen models)."""
    monkeypatch.setattr(
        DeploymentHandoffNode, "_push_branch", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        DeploymentHandoffNode, "_create_pr",
        AsyncMock(return_value="https://github.com/x/y/pull/1"),
    )


@pytest.fixture(autouse=True)
def _patch_research_llm_calls(monkeypatch):
    """Neutralize ResearchNode's OWN direct LLM calls (code-review finding).

    ``ResearchNode._build_plan_summary`` (called unconditionally whenever a
    NEW Jira ticket is created — the path every test in this module takes,
    since ``mock_jira`` never returns an existing issue) constructs a REAL
    ``LLMFactory``-backed client and calls ``client.ask(...)`` — completely
    independent of the stub ``dispatcher`` fixture, which only covers
    ``dispatcher.dispatch(...)``. Left unpatched, this makes a genuine
    network call on every run; when it's slow (no ``ANTHROPIC_API_KEY``,
    network hiccup, rate limit) it can stall well past this suite's 5s
    ``wait_until``/``wait_until_stream`` timeouts, surfacing as an
    intermittent ``pytest.fail("condition not met within 5s")`` — this is
    what actually caused the flakiness the code review flagged (a separate,
    more direct cause than the actions-stream background-task race also
    fixed in this file). ``_build_description``'s log-excerpt summarizer
    (``_summarize_excerpts``) is NOT patched here — it only triggers when
    the rendered Jira description exceeds 32 767 chars, never true for this
    module's short fixtures.
    """
    monkeypatch.setattr(
        ResearchNode, "_build_plan_summary",
        AsyncMock(return_value="1. Investigate. 2. Fix. 3. Verify."),
    )


@pytest.fixture
def fake_redis() -> _FakeStreamsRedis:
    return _FakeStreamsRedis()


async def _build_gated_runner(
    tmp_path, mock_jira: MagicMock, fake_redis: _FakeStreamsRedis,
) -> DevLoopRunner:
    """Build a real 8-node flow with BOTH HITL gates reachable.

    Code-review follow-up: ``require_deployment_approval`` is now threaded
    through ``build_dev_loop_flow`` -> ``build_dev_loop_node_factories`` ->
    ``DeploymentHandoffNode`` (a real, production-reachable activation path
    — earlier this test flipped the flag via ``object.__setattr__`` on the
    already-constructed node because no such wiring existed yet).
    """
    research_out = _research_output(tmp_path)
    dispatcher = _stub_dispatcher(research_out)
    flow = build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=mock_jira,
        log_toolkits={},
        redis_url="redis://localhost:6399/9",  # legacy XADD target; swallowed on failure
        publish_flow_events=True,
        require_deployment_approval=True,
    )

    runner = DevLoopRunner(
        flow, max_concurrent_runs=2, redis_url="redis://localhost:6399/9",
    )
    runner._ensure_actions_redis = AsyncMock(return_value=fake_redis)  # type: ignore[method-assign]
    return runner


# ---------------------------------------------------------------------------
# Scenario 1 — full gated run resolved via the REST command layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_run_with_blocking_gates(
    tmp_path, brief, mock_jira, fake_redis, monkeypatch, aiohttp_client
):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    runner = await _build_gated_runner(tmp_path, mock_jira, fake_redis)

    from aiohttp import web
    app = web.Application()
    register_command_routes(app, runner)
    client = await aiohttp_client(app)

    task = asyncio.create_task(runner.run(brief, run_id=RUN_ID))
    await wait_until(lambda: runner.get_host(RUN_ID) is not None, timeout=5)
    host = runner.get_host(RUN_ID)

    # 1. QA's blocking manual_criterion gate opens first.
    await wait_until(
        lambda: any(g.kind == "manual_criterion" for g in host.state.gates.values()),
        timeout=5,
    )
    qa_gate_id = next(
        gid for gid, g in host.state.gates.items() if g.kind == "manual_criterion"
    )
    assert host.state.phase == "awaiting_gate"
    # Jira must not have transitioned to "Ready to Deploy" yet.
    assert mock_jira.jira_transition_to.await_count == 0

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{qa_gate_id}/resolve",
        json={"resolution": "approved", "resolved_by": "alice"},
    )
    assert resp.status == 200

    # 2. deployment_approval gate opens next.
    await wait_until(
        lambda: any(
            g.kind == "deployment_approval" for g in host.state.gates.values()
        ),
        timeout=5,
    )
    deploy_gate_id = next(
        gid for gid, g in host.state.gates.items() if g.kind == "deployment_approval"
    )
    assert mock_jira.jira_transition_to.await_count == 0  # still not called

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{deploy_gate_id}/resolve",
        json={"resolution": "approved", "resolved_by": "bob", "comment": "ship it"},
    )
    assert resp.status == 200

    result = await asyncio.wait_for(task, timeout=10)

    # Jira transitioned to "Ready to Deploy" only AFTER both approvals.
    mock_jira.jira_transition_to.assert_awaited()
    assert result.responses["deployment_handoff"]["status"] == "ready_to_deploy"

    assert host.state.phase == "succeeded"
    assert host.state.gates[qa_gate_id].status == "approved"
    assert host.state.gates[qa_gate_id].resolved_by == "alice"
    assert host.state.gates[deploy_gate_id].status == "approved"
    assert host.state.gates[deploy_gate_id].resolved_by == "bob"

    # Legacy streams also populated (dual-publish, TASK-1852): at minimum the
    # actions stream captured the full lifecycle. The final envelope's XADD
    # is scheduled as a background task by the runner's envelope sink and
    # may not have landed the instant `task` completes — poll the stream
    # itself (not just `host.state`) until it's caught up, avoiding a race
    # under full-suite CPU contention.
    entries = await wait_until_stream(
        fake_redis, RUN_ID,
        lambda es: _fold_actions(es, RUN_ID) == host.state,
        timeout=5,
    )
    assert len(entries) > 0

    # Fold-equals-snapshot: replaying flow:{run_id}:actions from seq 0
    # reproduces the host's final state exactly.
    folded = _fold_actions(entries, RUN_ID)
    assert folded == host.state


def _fold_actions(
    entries: List[Tuple[str, Dict[str, str]]], run_id: str
) -> DevLoopSessionState:
    state = DevLoopSessionState(run_id=run_id, channel=session_channel(run_id))
    for _entry_id, fields in entries:
        raw = fields.get("envelope")
        if raw is None:
            continue
        envelope = ActionEnvelope.model_validate_json(raw)
        state = reduce(state, envelope.action)
    return state


def _max_seq(entries: List[Tuple[str, Dict[str, str]]]) -> int:
    seq = 0
    for _entry_id, fields in entries:
        raw = fields.get("envelope")
        if raw is None:
            continue
        seq = max(seq, ActionEnvelope.model_validate_json(raw).server_seq)
    return seq


# ---------------------------------------------------------------------------
# Scenario 2 — view="state" WS reconnect (no gaps/dupes) mid-run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_state_view_reconnect(
    tmp_path, brief, mock_jira, fake_redis, monkeypatch
):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    runner = await _build_gated_runner(tmp_path, mock_jira, fake_redis)

    task = asyncio.create_task(runner.run(brief, run_id=RUN_ID))
    await wait_until(lambda: runner.get_host(RUN_ID) is not None, timeout=5)
    host = runner.get_host(RUN_ID)
    await wait_until(lambda: len(host.state.gates) >= 1, timeout=5)

    # "Connect" mid-run: snapshot via view="state".
    mux1 = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state")
    first_frames = [f async for f in mux1.state_replay(last_seen=None)]
    assert len(first_frames) == 1
    assert first_frames[0]["event_kind"] == "snapshot"
    last_seen = first_frames[0]["payload"]["from_seq"]

    # Resolve the pending gate(s) so the run makes further progress.
    for gate_id, gate in list(host.state.gates.items()):
        if gate.status == "pending":
            host.resolve_gate(gate_id, "approved", resolved_by="alice")
            await wait_until(
                lambda gid=gate_id: any(
                    g.kind == "deployment_approval" for g in host.state.gates.values()
                ) or host.state.phase in ("succeeded", "failed"),
                timeout=5,
            )
            for gid, g in list(host.state.gates.items()):
                if g.status == "pending":
                    host.resolve_gate(gid, "approved", resolved_by="bob")

    result = await asyncio.wait_for(task, timeout=10)
    assert result.responses["deployment_handoff"]["status"] == "ready_to_deploy"

    # "Disconnect + reconnect" with ?last_seen=<seq from the first snapshot>.
    # Poll the stream until it's caught up with the finished host (the last
    # envelope's XADD is a background task — see wait_until_stream's
    # docstring) rather than reading it once right after `task` resolves.
    entries = await wait_until_stream(
        fake_redis, RUN_ID,
        lambda es: _fold_actions(es, RUN_ID) == host.state,
        timeout=5,
    )
    mux2 = FlowStreamMultiplexer(fake_redis, run_id=RUN_ID, view="state")
    reconnect_frames = [
        f async for f in mux2.state_replay(last_seen=last_seen)
    ]

    # No snapshot frame on reconnect; strictly-increasing seqs > last_seen.
    assert all(f["event_kind"] == "action" for f in reconnect_frames)
    seqs = [f["payload"]["server_seq"] for f in reconnect_frames]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))  # no duplicates
    assert all(s > last_seen for s in seqs)  # no gap (nothing skipped below)
    assert seqs[-1] == _max_seq(entries)  # reaches the final sequenced action

    # Eventual consistency: folding everything reproduces the run's final
    # terminal state exactly.
    folded = _fold_actions(entries, RUN_ID)
    assert folded.phase == "succeeded"
    assert folded == host.state


# ---------------------------------------------------------------------------
# Scenario 3 — crash rebuild from the actions stream (incl. mid-run)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crash_rebuild_from_actions_stream(
    tmp_path, brief, mock_jira, fake_redis, monkeypatch
):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    runner = await _build_gated_runner(tmp_path, mock_jira, fake_redis)

    task = asyncio.create_task(runner.run(brief, run_id=RUN_ID))
    await wait_until(lambda: runner.get_host(RUN_ID) is not None, timeout=5)
    host = runner.get_host(RUN_ID)
    await wait_until(lambda: len(host.state.gates) >= 1, timeout=5)

    # --- Mid-run rebuild: cut the stream while a gate is still pending. ---
    # `host.state.gates` updates synchronously ahead of the actions-stream
    # XADD (a background task fired by the runner's envelope sink) — poll
    # the STREAM itself for `awaiting_gate`, not a single read gated only
    # by `host.state`, to avoid the race that made this test intermittently
    # fail under full-suite load (see wait_until_stream's docstring).
    mid_run_entries = await wait_until_stream(
        fake_redis, RUN_ID,
        lambda es: _fold_actions(es, RUN_ID).phase == "awaiting_gate",
        timeout=5,
    )
    mid_run_state = _fold_actions(mid_run_entries, RUN_ID)
    assert mid_run_state.phase == "awaiting_gate"
    assert any(g.status == "pending" for g in mid_run_state.gates.values())

    # Resolve both gates to let the run finish.
    for gate_id in list(host.state.gates):
        host.resolve_gate(gate_id, "approved", resolved_by="alice")
    await wait_until(
        lambda: any(
            g.kind == "deployment_approval" for g in host.state.gates.values()
        ),
        timeout=5,
    )
    for gate_id, gate in list(host.state.gates.items()):
        if gate.status == "pending":
            host.resolve_gate(gate_id, "approved", resolved_by="bob")

    await asyncio.wait_for(task, timeout=10)
    assert host.state.phase == "succeeded"

    # --- Full rebuild after "crash" (host discarded — runner already did
    # this in _close_host; simulate total memory loss by building state
    # from nothing but the stream). ---
    assert runner.get_host(RUN_ID) is None  # confirms the host really is gone
    # Poll until the stream has caught up with the finished host's final
    # state — the last envelope's XADD is a background task, not guaranteed
    # to have landed the instant `task` resolved (see wait_until_stream).
    final_entries = await wait_until_stream(
        fake_redis, RUN_ID,
        lambda es: _fold_actions(es, RUN_ID).phase == "succeeded",
        timeout=5,
    )
    rebuilt = _fold_actions(final_entries, RUN_ID)

    assert rebuilt.phase == "succeeded"
    assert rebuilt.jira_issue_key or rebuilt.pr_url  # RunClosed carried data through
    assert all(g.status == "approved" for g in rebuilt.gates.values())

    # And it matches the persisted terminal snapshot artifact exactly.
    from parrot import conf
    import json as _json
    snapshot_path = tmp_path.joinpath("dev_loop_runs", f"{RUN_ID}.snapshot.json")
    if not snapshot_path.exists():
        # conftest.py's autouse fixture points conf.OUTPUT_DIR at tmp_path;
        # confirm that's really where _persist_terminal_snapshot wrote it.
        snapshot_path = (
            __import__("pathlib").Path(conf.OUTPUT_DIR)
            / "dev_loop_runs" / f"{RUN_ID}.snapshot.json"
        )
    persisted = _json.loads(snapshot_path.read_text())
    assert persisted["state"]["phase"] == "succeeded"
    assert persisted["state"] == rebuilt.model_dump(mode="json")
