"""FEAT-555 TASK-3210 — Slack-level e2e through webhook routes and Socket Mode handlers."""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.parse
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.flows.dev_loop.session_state import ApprovalGate, GateOpened, RunClosed, SessionHost
from parrot.integrations.devloop import service as svc
from parrot.integrations.devloop.models import Requester
from parrot.integrations.slack.devloop import register_devloop
from parrot.integrations.slack.models import SlackAgentConfig
from parrot.integrations.slack.wrapper import SlackAgentWrapper

pytestmark = pytest.mark.integration

_REQ = Requester(transport="slack", tenant_id="T1", user_id="U1")


@pytest.fixture(autouse=True)
def _skip_signature_verification(monkeypatch):
    """These tests exercise authorization/routing, not HMAC signing — bypass it like
    packages/ai-parrot-integrations/tests/integrations/slack/test_slack_whitelist_integration.py does."""
    monkeypatch.setattr("parrot.integrations.slack.wrapper.verify_slack_signature_raw", lambda *a, **k: True)


async def _wait_until(predicate, timeout: float = 10.0, interval: float = 0.02) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(interval)


def _build_wrapper(name: str = "t") -> SlackAgentWrapper:
    """A real SlackAgentWrapper (real routes, real command router/interactive handler)."""
    config = SlackAgentConfig(
        name=name,
        chatbot_id="bot1",
        bot_token="xoxb-fake",
        signing_secret="fake-secret",
        allowed_channel_ids=["C1"],
        allowed_user_ids=["U1"],
    )
    app = web.Application()
    return SlackAgentWrapper(agent=MagicMock(), config=config, app=app)


def _command_request(*, command: str = "/devloop", text: str, user: str = "U1", channel: str = "C1") -> MagicMock:
    form = {
        "team_id": "T1",
        "user_id": user,
        "channel_id": channel,
        "text": text,
        "command": command,
        "response_url": "https://hooks.slack.test/r",
    }
    raw_body = urllib.parse.urlencode(form).encode("utf-8")
    request = MagicMock(spec=web.Request)
    request.read = AsyncMock(return_value=raw_body)
    request.headers = MagicMock()
    request.headers.get = lambda *_a, **_k: None
    return request


def _interactive_request(payload: dict) -> MagicMock:
    raw_body = urllib.parse.urlencode({"payload": json.dumps(payload)}).encode("utf-8")
    request = MagicMock(spec=web.Request)
    request.read = AsyncMock(return_value=raw_body)
    request.headers = MagicMock()
    request.headers.get = lambda *_a, **_k: None
    return request


def _block_action_payload(action_id: str, *, user: str = "U1", channel: str = "C1") -> dict:
    return {
        "type": "block_actions",
        "team": {"id": "T1"},
        "user": {"id": user},
        "channel": {"id": channel},
        "trigger_id": "trigger-1",
        "response_url": "https://hooks.slack.test/r",
        "actions": [{"action_id": action_id}],
    }


def _view_submission_payload(callback_id: str, private_metadata: dict, values: dict, *, user: str = "U1") -> dict:
    return {
        "type": "view_submission",
        "team": {"id": "T1"},
        "user": {"id": user},
        "view": {
            "callback_id": callback_id,
            "private_metadata": json.dumps(private_metadata),
            "state": {"values": values},
        },
    }


def _single_text_field(block_id: str, action_id: str, value: str) -> dict:
    return {block_id: {action_id: {"type": "plain_text_input", "value": value}}}


@pytest.mark.asyncio
async def test_slack_feature_run_thread_flow(slack_api, devloop_config, fake_redis, fake_child):
    """/devloop --type feature ⇒ confirm card ⇒ Confirm ⇒ real child ⇒ gate ⇒ answer ⇒ terminal, all via webhook routes."""
    devloop_config.command = [sys.executable, fake_child]
    wrapper = _build_wrapper("feat1")
    service = svc.DevLoopDispatchService(config=devloop_config, transport=MagicMock(), redis=fake_redis)
    transport = register_devloop(wrapper, service)
    # register_devloop built its own SlackDevLoopTransport bound to `wrapper` (whose
    # _slack_api is patched by the slack_api fixture) — swap it in as the service's
    # real transport so post_confirm/post_gate/post_terminal all render for real.
    service.transport = transport

    resp = await wrapper._handle_command(_command_request(text="--type feature Build the thing. Now"))
    body = json.loads(resp.body)
    assert "Validating" in body["text"]
    await asyncio.gather(*wrapper._background_tasks)
    assert any(m == "chat.postMessage" for m, _ in slack_api.calls)  # confirm card posted

    (pending_id,) = list(service._pending.keys())

    confirm_resp = await wrapper._handle_interactive(
        _interactive_request(_block_action_payload(f"devloop_confirm:{pending_id}"))
    )
    assert confirm_resp.status == 200
    await _wait_until(lambda: service._pending == {})

    run_id = next(iter(service.registry.all_records())).run_id
    await _wait_until(lambda: service.record(run_id) is not None and service.record(run_id).phase == "running")
    # Let the background _tail task run its state_replay() against the still-empty
    # stream and settle into its live state_tail() xread before we add the gate —
    # otherwise the gate could land in the same connect-time snapshot the tail's
    # first read folds (a real race the service's own snapshot handling does not
    # surface as `pending_gate`; out of scope here, see the task's Completion Note).
    await asyncio.sleep(0.2)

    host = SessionHost(run_id=run_id)
    gate = ApprovalGate(
        gate_id="oq-1", kind="open_questions", node_id="ideation", title="Open questions", questions=["What store?"]
    )
    env = host.apply(GateOpened(gate=gate))
    await fake_redis.xadd(f"flow:{run_id}:actions", {"envelope": env.model_dump_json()})
    await _wait_until(lambda: service.pending_gate(run_id) is not None)

    answers_payload = _view_submission_payload(
        "devloop_answers", {"run_id": run_id, "gate_id": "oq-1"}, _single_text_field("q1", "answer", "pgvector")
    )
    answers_resp = await wrapper._handle_interactive(_interactive_request(answers_payload))
    result = json.loads(answers_resp.body)
    assert result == {"ok": True}  # None from handle_answers_submission ⇒ default {"ok": True}

    env2 = host.apply(RunClosed(outcome="succeeded", pr_url="http://pr/1"))
    await fake_redis.xadd(f"flow:{run_id}:actions", {"envelope": env2.model_dump_json()})
    await _wait_until(lambda: service.record(run_id).phase == "completed")
    await service.stop()


@pytest.mark.asyncio
async def test_slack_bug_confirm_then_run(slack_api, devloop_config, fake_redis, fake_child):
    """/devloop --type bug ⇒ confirm card with WorkBrief defaults; Edit modal overrides the summary; Confirm ⇒ started."""
    devloop_config.command = [sys.executable, fake_child]
    wrapper = _build_wrapper("bug1")
    service = svc.DevLoopDispatchService(config=devloop_config, transport=MagicMock(), redis=fake_redis)
    transport = register_devloop(wrapper, service)
    service.transport = transport

    resp = await wrapper._handle_command(_command_request(text="--type bug A long enough bug summary"))
    assert "Validating" in json.loads(resp.body)["text"]
    await asyncio.gather(*wrapper._background_tasks)
    (pending_id,) = list(service._pending.keys())
    original_summary = service._pending[pending_id].fields.get("summary", "")
    assert original_summary

    edit_payload = _view_submission_payload(
        "devloop_edit",
        {"pending_id": pending_id, "kind": "bug"},
        _single_text_field("summary", "summary_input", "An edited, overridden bug summary"),
    )
    edit_resp = await wrapper._handle_interactive(_interactive_request(edit_payload))
    assert json.loads(edit_resp.body) == {"ok": True}

    await _wait_until(lambda: service._pending == {})
    record = next(iter(service.registry.all_records()))
    assert record.kind == "bug"
    await _wait_until(lambda: service.record(record.run_id).phase == "running")
    await service.stop()


@pytest.mark.asyncio
async def test_slack_auth_parity_webhook_vs_socket(slack_api, devloop_config):
    """Webhook and Socket Mode reject the same unauthorized inputs identically, never touching the service."""
    from parrot.integrations.slack.socket_handler import SlackSocketHandler

    wrapper_web = _build_wrapper("parity-web")
    wrapper_socket = _build_wrapper("parity-socket")
    socket_config = SlackAgentConfig(
        name="parity-socket2",
        chatbot_id="bot2",
        bot_token="xoxb-fake",
        signing_secret="fake-secret",
        app_token="xapp-fake",
        connection_mode="socket",
        allowed_channel_ids=["C1"],
        allowed_user_ids=["U1"],
    )
    wrapper_socket.config = socket_config  # swap in socket-mode config, same routes/router
    socket_handler = SlackSocketHandler(wrapper_socket)

    service_web = MagicMock()
    service_web.dispatch = AsyncMock()
    service_socket = MagicMock()
    service_socket.dispatch = AsyncMock()
    register_devloop(wrapper_web, service_web)
    register_devloop(wrapper_socket, service_socket)

    # (1) non-whitelisted user on the slash command ⇒ "Unauthorized." on both, service never called.
    web_resp = await wrapper_web._handle_command(_command_request(text="--type feature x", user="U-evil"))
    assert json.loads(web_resp.body) == {"response_type": "ephemeral", "text": "Unauthorized."}

    sent: list = []

    async def _capture(_url, body):
        sent.append(body)

    socket_handler._send_response = _capture  # type: ignore[method-assign]
    await socket_handler._handle_slash_command(
        {
            "team_id": "T1",
            "user_id": "U-evil",
            "channel_id": "C1",
            "text": "--type feature x",
            "command": "/devloop",
            "response_url": "https://hooks.slack.test/r",
        }
    )
    assert sent == [{"response_type": "ephemeral", "text": "Unauthorized channel."}]
    service_web.dispatch.assert_not_called()
    service_socket.dispatch.assert_not_called()

    # (2) non-whitelisted user on a block_action ⇒ silently dropped by both, service untouched.
    web_interactive_resp = await wrapper_web._handle_interactive(
        _interactive_request(_block_action_payload("devloop_confirm:p1", user="U-evil"))
    )
    assert json.loads(web_interactive_resp.body) == {"ok": True}
    await socket_handler._handle_interactive(_block_action_payload("devloop_confirm:p1", user="U-evil"))
    service_web.dispatch.assert_not_called()
    service_socket.dispatch.assert_not_called()
