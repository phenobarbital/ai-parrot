"""Tests for gate cards, answers modal, thread fallback and the Slack transport (TASK-3207)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.devloop.models import GateView, Requester, RunRecord
from parrot.integrations.slack.devloop import actions, blocks
from parrot.integrations.slack.devloop.transport import SlackDevLoopTransport

_REQ = Requester(transport="slack", tenant_id="T1", user_id="U1")


def _record(**overrides) -> RunRecord:
    payload = dict(
        run_id="run-abcd1234",
        kind="feature",
        title="Token budget",
        requester=_REQ,
        channel_id="C1",
        thread_ts="1234.5678",
        started_at=time.time(),
    )
    payload.update(overrides)
    return RunRecord(**payload)


def _gate(**overrides) -> GateView:
    payload = dict(gate_id="oq-1", kind="open_questions", title="Open questions — x", questions=["a", "b"])
    payload.update(overrides)
    return GateView(**payload)


def test_gate_blocks_and_answers_modal():
    """open_questions ⇒ Answer/Abort actions with <run>:<gate> suffix; modal has one optional input per question."""
    record, gate = _record(), _gate()
    card = blocks.gate_blocks(record, gate)
    actions_block = card[-1]
    ids = [e["action_id"] for e in actions_block["elements"]]
    assert ids == ["devloop_answer:run-abcd1234:oq-1", "devloop_reject:run-abcd1234:oq-1"]

    modal = blocks.answers_modal(record, gate)
    assert modal["id"] == "devloop_answers"
    assert modal["metadata"] == {"run_id": "run-abcd1234", "gate_id": "oq-1"}
    assert [f["id"] for f in modal["fields"]] == ["q1", "q2"]
    assert all(f["optional"] for f in modal["fields"])


def test_gate_blocks_other_kind_has_approve_reject():
    record = _record()
    gate = _gate(gate_id="pa-1", kind="plan_approval", title="Approve the plan", payload_ref="sdd/plan.md")
    card = blocks.gate_blocks(record, gate)
    actions_block = card[-1]
    ids = [e["action_id"] for e in actions_block["elements"]]
    assert ids == ["devloop_approve:run-abcd1234:pa-1", "devloop_reject:run-abcd1234:pa-1"]


@pytest.mark.asyncio
async def test_answers_submission_partial_and_empty():
    """One answered question resolves the gate; zero answers returns a Slack errors response."""
    service = MagicMock()
    service.pending_gate = MagicMock(return_value=_gate())
    service.answer_gate = AsyncMock(return_value=MagicMock(ok=True, reason=""))
    transport = MagicMock()
    transport.wrapper = MagicMock()
    transport.wrapper._interactive_handler.extract_form_values = MagicMock(return_value={"q1": "answer one", "q2": ""})

    payload = {
        "view": {"private_metadata": '{"run_id": "run-abcd1234", "gate_id": "oq-1"}'},
        "team": {"id": "T1"},
        "user": {"id": "U1"},
    }
    result = await actions.handle_answers_submission(payload, service=service, transport=transport)
    assert result is None
    service.answer_gate.assert_awaited_once()
    call_args = service.answer_gate.call_args
    assert call_args.args[0] == "run-abcd1234" and call_args.args[1] == "oq-1"
    assert call_args.args[3] == {"a": "answer one"}

    transport.wrapper._interactive_handler.extract_form_values = MagicMock(return_value={"q1": "", "q2": ""})
    empty_result = await actions.handle_answers_submission(payload, service=service, transport=transport)
    assert empty_result == {"response_action": "errors", "errors": {"q1": "Answer at least one question"}}


@pytest.mark.asyncio
async def test_thread_answer_interceptor():
    """`1: x` / `2) y` parsed and sent; non-owner and non-run-thread events are not answers; run-thread events are always consumed."""
    record = _record()
    service = MagicMock()
    service.record_by_thread = MagicMock(return_value=record)
    service.pending_gate = MagicMock(return_value=_gate())
    service.answer_gate = AsyncMock(return_value=MagicMock(ok=True, reason=""))
    transport = MagicMock()
    transport.wrapper = MagicMock()
    transport.wrapper._slack_api = AsyncMock(return_value={"ok": True})

    # No thread_ts: never intercepted.
    assert await actions.thread_answer_interceptor({"text": "1: x"}, service=service, transport=transport) is False

    # Non-run-thread: record_by_thread returns None.
    service.record_by_thread.return_value = None
    assert (
        await actions.thread_answer_interceptor(
            {"thread_ts": "9.9", "channel": "C9", "user": "U1", "text": "1: x"}, service=service, transport=transport
        )
        is False
    )
    service.record_by_thread.return_value = record

    # Non-owner: consumed, but not answered.
    consumed = await actions.thread_answer_interceptor(
        {"thread_ts": "1234.5678", "channel": "C1", "user": "U2", "text": "1: x"}, service=service, transport=transport
    )
    assert consumed is True
    service.answer_gate.assert_not_called()

    # Owner with valid answer lines: consumed and answered.
    consumed = await actions.thread_answer_interceptor(
        {"thread_ts": "1234.5678", "channel": "C1", "user": "U1", "text": "1: pgvector\n2) async flush"},
        service=service,
        transport=transport,
    )
    assert consumed is True
    service.answer_gate.assert_awaited_once_with(
        record.run_id, "oq-1", record.requester, {"a": "pgvector", "b": "async flush"}
    )


@pytest.mark.asyncio
async def test_transport_posts_in_thread_with_the_run_thread_ts():
    """post_run_started (and every _post_in_thread caller) posts into record.thread_ts.

    The transport methods themselves do not catch exceptions — that
    "never raises" guarantee is provided end-to-end by the service's
    ``_safe_call`` wrapper (TASK-3204), which every transport call goes
    through in production.
    """
    wrapper = MagicMock()
    wrapper.post_message = AsyncMock(return_value="1234.9999")
    transport = SlackDevLoopTransport(wrapper)
    record = _record()

    await transport.post_run_started(record)

    wrapper.post_message.assert_awaited_once()
    args, kwargs = wrapper.post_message.call_args
    assert kwargs["thread_ts"] == record.thread_ts


@pytest.mark.asyncio
async def test_transport_wrapper_failure_propagates_uncaught():
    """A raw wrapper failure propagates out of the transport (caught by the service's _safe_call in production)."""
    wrapper = MagicMock()
    wrapper.post_message = AsyncMock(side_effect=RuntimeError("boom"))
    transport = SlackDevLoopTransport(wrapper)

    with pytest.raises(RuntimeError):
        await transport.post_run_started(_record())


def test_thread_answer_regex():
    assert actions.THREAD_ANSWER_RE.findall("1: pgvector\n2) async flush\nno number") == [
        ("1", "pgvector"),
        ("2", "async flush"),
    ]
