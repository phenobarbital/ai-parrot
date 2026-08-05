"""Tests for the `open_questions` gate extension (FEAT-412, TASK-2122).

The dev-flow's ideation phase needs ONE gate per round carrying ALL of that
round's Open Questions (structured), resolved with a structured
``question -> answer`` mapping. The extension touches SHARED ``dev_loop``
infrastructure, so these tests focus as much on **backward compatibility**
(pre-FEAT-412 persisted envelopes must still validate and reduce) as on the
new behavior.

Covers:

* ``open_gate(kind="open_questions", questions=[...])`` and snapshot round-trip.
* ``resolve_gate(..., answers={...})`` folding, with audit fields intact.
* Host-side validation: approving with empty answers → ``ValueError`` (400 at
  the REST layer); rejection needs no answers.
* Old envelopes (no ``questions``/``answers`` keys) still validate + reduce.
* Fail-closed expiry for an ``open_questions`` gate.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from parrot.flows.dev_loop import DevLoopRunner
from parrot.flows.dev_loop.commands import register_command_routes
from parrot.flows.dev_loop.session_state import (
    ActionEnvelope,
    ApprovalGate,
    GateExpired,
    GateOpened,
    GateResolved,
    SessionHost,
    reduce,
    session_channel,
)

RUN_ID = "run-oq00001"

QUESTIONS = [
    "Which store backs the telemetry?",
    "Sync or async flush?",
]


@pytest.fixture
def host() -> SessionHost:
    return SessionHost(RUN_ID)


# ---------------------------------------------------------------------------
# open_gate — the new kind + structured questions
# ---------------------------------------------------------------------------


def test_gate_open_questions_kind(host: SessionHost):
    """The new kind is accepted and carries the round's questions."""
    gate_id, envelope = host.open_gate(
        kind="open_questions",
        node_id="ideation",
        title="Open Questions — sdd/proposals/foo.brainstorm.md",
        questions=QUESTIONS,
        on_expiry="fail",
    )

    gate = host.state.gates[gate_id]
    assert gate.kind == "open_questions"
    assert gate.status == "pending"
    assert gate.questions == QUESTIONS
    assert gate.answers == {}
    assert gate.on_expiry == "fail"
    assert envelope.action.type == "gate/opened"
    # Opening a gate parks the run (park/resume applies to the new kind too).
    assert host.state.phase == "awaiting_gate"


def test_gate_questions_round_trip_through_snapshot(host: SessionHost):
    gate_id, _ = host.open_gate(
        kind="open_questions", node_id="ideation", title="q",
        questions=QUESTIONS,
    )
    snap = host.snapshot()

    # Serialize + re-validate the way a Redis-backed subscriber would.
    raw = snap.model_dump(mode="json")
    revived = type(snap).model_validate(raw)
    assert revived.state.gates[gate_id].questions == QUESTIONS
    assert revived.channel == session_channel(RUN_ID)


def test_open_gate_without_questions_defaults_empty(host: SessionHost):
    """Every pre-existing open_gate() call site keeps working unchanged."""
    gate_id, _ = host.open_gate(
        kind="manual_criterion", node_id="qa", title="Check the UI"
    )
    assert host.state.gates[gate_id].questions == []
    assert host.state.gates[gate_id].answers == {}


# ---------------------------------------------------------------------------
# resolve_gate — structured answers
# ---------------------------------------------------------------------------


def test_gate_resolve_with_answers(host: SessionHost):
    """Answers fold into gate state; the audit fields stay intact."""
    gate_id, _ = host.open_gate(
        kind="open_questions", node_id="ideation", title="q",
        questions=QUESTIONS,
    )
    answers = {QUESTIONS[0]: "pgvector", QUESTIONS[1]: "async"}

    envelope = host.resolve_gate(
        gate_id, "approved", resolved_by="alice", comment="answered",
        answers=answers,
    )

    gate = host.state.gates[gate_id]
    assert gate.status == "approved"
    assert gate.answers == answers
    assert gate.questions == QUESTIONS  # questions preserved
    assert gate.resolved_by == "alice"
    assert gate.comment == "answered"
    assert gate.resolved_at is not None
    assert envelope.action.answers == answers
    assert host.state.phase == "running"  # gate cleared → run resumes


def test_gate_resolve_partial_answers_allowed(host: SessionHost):
    """Partial answers are valid — unanswered questions stay open in the doc."""
    gate_id, _ = host.open_gate(
        kind="open_questions", node_id="ideation", title="q",
        questions=QUESTIONS,
    )
    host.resolve_gate(
        gate_id, "approved", resolved_by="alice",
        answers={QUESTIONS[0]: "pgvector"},
    )
    gate = host.state.gates[gate_id]
    assert gate.answers == {QUESTIONS[0]: "pgvector"}
    assert len(gate.questions) == 2


def test_gate_resolve_answers_required(host: SessionHost):
    """Approving an open_questions gate with no answers is rejected."""
    gate_id, _ = host.open_gate(
        kind="open_questions", node_id="ideation", title="q",
        questions=QUESTIONS,
    )

    with pytest.raises(ValueError, match="open_questions"):
        host.resolve_gate(gate_id, "approved", resolved_by="alice")
    with pytest.raises(ValueError, match="open_questions"):
        host.resolve_gate(gate_id, "approved", resolved_by="alice", answers={})

    # Validation happens BEFORE sequencing: no action was emitted, the gate
    # is still pending and can be resolved properly afterwards.
    assert host.state.gates[gate_id].status == "pending"
    assert [
        e for e in host.replay_since(0) if e.action.type == "gate/resolved"
    ] == []
    host.resolve_gate(
        gate_id, "approved", resolved_by="alice", answers={QUESTIONS[0]: "a"}
    )
    assert host.state.gates[gate_id].status == "approved"


def test_gate_reject_needs_no_answers(host: SessionHost):
    """Rejection aborts the ideation — no answers required."""
    gate_id, _ = host.open_gate(
        kind="open_questions", node_id="ideation", title="q",
        questions=QUESTIONS,
    )
    host.resolve_gate(
        gate_id, "rejected", resolved_by="alice", comment="wrong document",
    )
    gate = host.state.gates[gate_id]
    assert gate.status == "rejected"
    assert gate.answers == {}
    assert gate.comment == "wrong document"


def test_answers_ignored_for_other_kinds(host: SessionHost):
    """Non-open_questions gates need no answers and are unaffected."""
    gate_id, _ = host.open_gate(
        kind="plan_approval", node_id="development", title="Approve plan"
    )
    host.resolve_gate(gate_id, "approved", resolved_by="alice")
    assert host.state.gates[gate_id].status == "approved"
    assert host.state.gates[gate_id].answers == {}


@pytest.mark.asyncio
async def test_wait_gate_returns_answers(host: SessionHost):
    """IdeationNode's await path sees the answers on the resolved gate."""
    gate_id, _ = host.open_gate(
        kind="open_questions", node_id="ideation", title="q",
        questions=QUESTIONS,
    )

    async def _resolve():
        await asyncio.sleep(0)
        host.resolve_gate(
            gate_id, "approved", resolved_by="alice",
            answers={QUESTIONS[0]: "pgvector"},
        )

    task = asyncio.create_task(_resolve())
    gate = await host.wait_gate(gate_id)
    await task

    assert gate.status == "approved"
    assert gate.answers == {QUESTIONS[0]: "pgvector"}


# ---------------------------------------------------------------------------
# Backward compatibility — pre-FEAT-412 envelopes
# ---------------------------------------------------------------------------


def test_gate_backward_compat():
    """Envelopes persisted before FEAT-412 still validate and reduce."""
    # An ApprovalGate dict as it was persisted pre-FEAT-412: no questions,
    # no answers keys at all.
    legacy_gate = {
        "gate_id": "g-legacy",
        "kind": "deployment_approval",
        "node_id": "deployment_handoff",
        "status": "pending",
        "on_expiry": "fail",
        "title": "Approve deploy",
        "instructions": "",
        "payload_ref": "",
        "opened_at": 1.0,
        "expires_at": None,
        "resolved_by": "",
        "resolved_at": None,
        "comment": "",
    }
    gate = ApprovalGate.model_validate(legacy_gate)
    assert gate.questions == []
    assert gate.answers == {}

    legacy_opened = {
        "channel": session_channel(RUN_ID),
        "server_seq": 1,
        "action": {"type": "gate/opened", "ts": 1.0, "gate": legacy_gate},
        "origin": None,
    }
    opened = ActionEnvelope.model_validate(legacy_opened)
    assert isinstance(opened.action, GateOpened)

    legacy_resolved = {
        "channel": session_channel(RUN_ID),
        "server_seq": 2,
        "action": {
            "type": "gate/resolved",
            "ts": 2.0,
            "gate_id": "g-legacy",
            "resolution": "approved",
            "resolved_by": "alice",
            "comment": "ship it",
        },
        "origin": None,
    }
    resolved = ActionEnvelope.model_validate(legacy_resolved)
    assert isinstance(resolved.action, GateResolved)
    assert resolved.action.answers == {}

    # ... and the pair still reduces exactly as before.
    from parrot.flows.dev_loop.session_state import DevLoopSessionState

    state = DevLoopSessionState(run_id=RUN_ID, channel=session_channel(RUN_ID))
    state = reduce(state, opened.action)
    assert state.phase == "awaiting_gate"
    state = reduce(state, resolved.action)
    assert state.gates["g-legacy"].status == "approved"
    assert state.gates["g-legacy"].comment == "ship it"
    assert state.gates["g-legacy"].answers == {}


def test_legacy_resolve_does_not_clobber_existing_answers():
    """A GateResolved with no answers leaves the (empty) mapping empty."""
    host = SessionHost(RUN_ID)
    gate_id, _ = host.open_gate(
        kind="manual_criterion", node_id="qa", title="x"
    )
    # Simulate a replayed legacy action (no answers field on the wire).
    host.apply(
        GateResolved(
            gate_id=gate_id, resolution="approved", resolved_by="alice",
            comment="c",
        )
    )
    assert host.state.gates[gate_id].answers == {}
    assert host.state.gates[gate_id].comment == "c"


# ---------------------------------------------------------------------------
# Expiry — fail-closed for open_questions
# ---------------------------------------------------------------------------


def test_open_questions_expiry_fail_closed(host: SessionHost):
    """Silence is not consent for spec decisions: expiry emits GateExpired."""
    gate_id, _ = host.open_gate(
        kind="open_questions", node_id="ideation", title="q",
        questions=QUESTIONS, ttl_seconds=10, on_expiry="fail",
    )
    envelopes = host.expire_due_gates(now=host.state.gates[gate_id].opened_at + 11)

    assert len(envelopes) == 1
    assert isinstance(envelopes[0].action, GateExpired)
    assert host.state.gates[gate_id].status == "expired"
    assert host.state.gates[gate_id].answers == {}


def test_open_questions_not_expired_before_ttl(host: SessionHost):
    gate_id, _ = host.open_gate(
        kind="open_questions", node_id="ideation", title="q",
        questions=QUESTIONS, ttl_seconds=100,
    )
    assert host.expire_due_gates(now=host.state.gates[gate_id].opened_at + 1) == []
    assert host.state.gates[gate_id].status == "pending"


# ---------------------------------------------------------------------------
# REST layer — answers passthrough + 400 on empty-answers approval
# ---------------------------------------------------------------------------


def _build_app(runner: DevLoopRunner) -> web.Application:
    app = web.Application()
    register_command_routes(app, runner)
    return app


@pytest.fixture
def runner() -> DevLoopRunner:
    return DevLoopRunner(MagicMock(), max_concurrent_runs=2)


@pytest.fixture
def rest_host(runner: DevLoopRunner):
    return runner._register_host(RUN_ID)  # test-only: REST-layer scope


@pytest.mark.asyncio
async def test_rest_resolve_with_answers(aiohttp_client, runner, rest_host):
    gate_id, _ = rest_host.open_gate(
        kind="open_questions", node_id="ideation", title="q",
        questions=QUESTIONS,
    )
    client = await aiohttp_client(_build_app(runner))
    answers = {QUESTIONS[0]: "pgvector", QUESTIONS[1]: "async"}

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{gate_id}/resolve",
        json={
            "resolution": "approved",
            "resolved_by": "alice",
            "answers": answers,
        },
    )

    assert resp.status == 200
    data = await resp.json()
    assert data["envelope"]["action"]["answers"] == answers
    assert rest_host.state.gates[gate_id].answers == answers


@pytest.mark.asyncio
async def test_rest_resolve_empty_answers_400(aiohttp_client, runner, rest_host):
    gate_id, _ = rest_host.open_gate(
        kind="open_questions", node_id="ideation", title="q",
        questions=QUESTIONS,
    )
    client = await aiohttp_client(_build_app(runner))

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{gate_id}/resolve",
        json={"resolution": "approved", "resolved_by": "alice"},
    )

    assert resp.status == 400
    data = await resp.json()
    assert data["error"] == "answers_required"
    assert rest_host.state.gates[gate_id].status == "pending"


@pytest.mark.asyncio
async def test_rest_reject_without_answers_200(aiohttp_client, runner, rest_host):
    gate_id, _ = rest_host.open_gate(
        kind="open_questions", node_id="ideation", title="q",
        questions=QUESTIONS,
    )
    client = await aiohttp_client(_build_app(runner))

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{gate_id}/resolve",
        json={"resolution": "rejected", "resolved_by": "alice",
              "comment": "wrong doc"},
    )

    assert resp.status == 200
    assert rest_host.state.gates[gate_id].status == "rejected"


@pytest.mark.asyncio
async def test_rest_legacy_body_without_answers_still_works(
    aiohttp_client, runner, rest_host
):
    """Pre-FEAT-412 clients (no `answers` key) keep working on other kinds."""
    gate_id, _ = rest_host.open_gate(
        kind="deployment_approval", node_id="deployment_handoff", title="x"
    )
    client = await aiohttp_client(_build_app(runner))

    resp = await client.post(
        f"/runs/{RUN_ID}/gates/{gate_id}/resolve",
        json={"resolution": "approved", "resolved_by": "alice", "comment": "go"},
    )

    assert resp.status == 200
    assert rest_host.state.gates[gate_id].status == "approved"
    assert rest_host.state.gates[gate_id].answers == {}
