"""E2E: deep-link web resume route (TASK-1735, spec §4)."""

import json

import pytest

from parrot.handlers.deeplink import DeepLinkResumeHandler, build_structured_message
from parrot.outputs.a2ui.deeplink import DeepLinkService

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


class TestDeepLinkResumeWeb:
    async def test_e2e_deeplink_resume_web(self):
        service = DeepLinkService(FakeRedis(), base_url="https://app.example")
        injected = {}

        async def fake_invoker(*, agent_name, query, session_id, user_id):
            injected.update(
                agent_name=agent_name, query=query, session_id=session_id, user_id=user_id
            )
            return {"echo": "ok"}

        handler = DeepLinkResumeHandler(service, fake_invoker)

        dl = await service.mint(
            session_id="sess-1",
            user_id="user-1",
            agent_id="assistant",
            channel="web",
            action_payload={"action": "approve", "row": 7, "label": "Approve"},
        )

        body, status = await handler.handle(dl.token_id)

        assert status == 200
        assert body["status"] == "resumed"
        assert body["session_id"] == "sess-1"
        # Action injected as a structured user message into the SAME session.
        assert injected["session_id"] == "sess-1"
        assert injected["user_id"] == "user-1"
        assert injected["agent_name"] == "assistant"
        decoded = json.loads(injected["query"])
        assert decoded["type"] == "a2ui_action_resume"
        assert decoded["action"]["action"] == "approve"

    async def test_expired_or_replayed_click_friendly_landing(self):
        service = DeepLinkService(FakeRedis(), base_url="https://app.example")

        async def fake_invoker(**kwargs):
            raise AssertionError("invoker must not run for an expired token")

        handler = DeepLinkResumeHandler(service, fake_invoker)

        dl = await service.mint(
            session_id="s", user_id="u", agent_id="a", channel="web",
            action_payload={"action": "x"},
        )
        # First consume succeeds via a permissive invoker.
        ok_handler = DeepLinkResumeHandler(service, lambda **k: _ok())
        body, status = await ok_handler.handle(dl.token_id)
        assert status == 200

        # Replay → friendly 410, invoker not called, no payload echo.
        body2, status2 = await handler.handle(dl.token_id)
        assert status2 == 410
        assert body2["status"] == "expired"
        # Friendly landing echoes no session/action payload details.
        assert "action" not in json.dumps(body2)
        assert "sess" not in json.dumps(body2)

    async def test_landing_does_not_consume_token(self):
        # GET landing (rendered for link prescanners) must NOT burn the single-use token.
        service = DeepLinkService(FakeRedis(), base_url="https://app.example")
        handler = DeepLinkResumeHandler(service, lambda **k: _ok())
        dl = await service.mint(
            session_id="s", user_id="u", agent_id="a", channel="web",
            action_payload={"action": "x", "label": "Approve"},
        )
        landing = handler.render_landing(dl.token_id)
        assert "<form method='post'" in landing
        assert dl.token_id in landing
        # Token still consumable after the landing render (not burned by GET/prefetch).
        body, status = await handler.handle(dl.token_id)
        assert status == 200 and body["status"] == "resumed"

    async def test_landing_escapes_token(self):
        service = DeepLinkService(FakeRedis(), base_url="https://app.example")
        handler = DeepLinkResumeHandler(service, lambda **k: _ok())
        landing = handler.render_landing('"><script>alert(1)</script>')
        assert "<script>alert(1)</script>" not in landing
        assert "&lt;script&gt;" in landing

    async def test_build_structured_message_shape(self):
        from parrot.outputs.a2ui.deeplink import ResumePayload

        msg = build_structured_message(
            ResumePayload(
                session_id="s", user_id="u", agent_id="a", channel="web",
                action_payload={"action": "go"},
            )
        )
        assert json.loads(msg)["type"] == "a2ui_action_resume"


async def _ok():
    return {"ok": True}
