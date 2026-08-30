"""E2E: deep-link web resume route (TASK-1735, spec §4)."""

import json

import pytest
from parrot.handlers.deeplink import DeepLinkResumeHandler, build_structured_message
from parrot.outputs.a2ui.deeplink import DeepLinkService

pytestmark = pytest.mark.asyncio


def _action_envelope(name: str = "approve", **context) -> dict:
    """Build a valid v1.0 ``A2UIRendererMessage`` 'action' envelope."""
    return {
        "version": "v1.0",
        "action": {
            "name": name,
            "surfaceId": "main",
            "sourceComponentId": "btn1",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "context": context,
        },
    }


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
            injected.update(agent_name=agent_name, query=query, session_id=session_id, user_id=user_id)
            return {"echo": "ok"}

        handler = DeepLinkResumeHandler(service, fake_invoker)

        dl = await service.mint(
            session_id="sess-1",
            user_id="user-1",
            agent_id="assistant",
            channel="web",
            action_payload=_action_envelope("approve", row=7),
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
        assert decoded["type"] == "a2ui_action"
        assert decoded["action"]["action"]["name"] == "approve"

    async def test_expired_or_replayed_click_friendly_landing(self):
        service = DeepLinkService(FakeRedis(), base_url="https://app.example")

        async def fake_invoker(**kwargs):
            raise AssertionError("invoker must not run for an expired token")

        handler = DeepLinkResumeHandler(service, fake_invoker)

        dl = await service.mint(
            session_id="s",
            user_id="u",
            agent_id="a",
            channel="web",
            action_payload=_action_envelope("x"),
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
            session_id="s",
            user_id="u",
            agent_id="a",
            channel="web",
            action_payload=_action_envelope("Approve"),
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
                session_id="s",
                user_id="u",
                agent_id="a",
                channel="web",
                action_payload=_action_envelope("go"),
            )
        )
        assert json.loads(msg)["type"] == "a2ui_action"


async def _ok():
    return {"ok": True}


class _SpyRuntime:
    """Records every ``dispatch`` call — the shape ``A2UIRuntime.dispatch`` exposes."""

    def __init__(self):
        self.calls = []

    async def dispatch(self, envelope, ctx):
        self.calls.append((envelope, ctx))
        from parrot.outputs.a2ui.runtime.models import DispatchResult

        return DispatchResult()


class TestDispatchPath:
    """FEAT-469 TASK-2574 — resume dispatches through A2UIRuntime, transport='deeplink'."""

    async def test_resume_dispatches_action_v1(self):
        service = DeepLinkService(FakeRedis(), base_url="https://app.example")
        spy_runtime = _SpyRuntime()

        async def runtime_factory(agent_id, user_id):
            return spy_runtime

        handler = DeepLinkResumeHandler(service, lambda **k: _ok(), runtime_factory=runtime_factory)
        dl = await service.mint(
            session_id="sess-1",
            user_id="user-1",
            agent_id="assistant",
            channel="web",
            action_payload=_action_envelope("approve", row=7),
        )

        _body, status = await handler.handle(dl.token_id)

        assert status == 200
        assert len(spy_runtime.calls) == 1
        env, ctx = spy_runtime.calls[0]
        assert "action" in env
        assert ctx.transport == "deeplink"
        assert ctx.session_id == "sess-1"
        assert ctx.user_id == "user-1"
        assert ctx.agent_id == "assistant"

    async def test_resume_persists_surface_state(self):
        """A `dataModel`-carrying action dispatched through a real runtime persists state."""

        from parrot.memory.file import FileConversationMemory
        from parrot.outputs.a2ui.runtime.adapters import (
            ConversationMemorySurfaceStore,
            ToolManagerExecutor,
        )
        from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime
        from parrot.tools.manager import ToolManager

        memory = FileConversationMemory(base_path="/tmp/a2ui-deeplink-test-surfaces")
        store = ConversationMemorySurfaceStore(memory, user_id="user-1")
        runtime = A2UIRuntime(executor=ToolManagerExecutor(ToolManager()), surfaces=store, pending=store)

        async def runtime_factory(agent_id, user_id):
            return runtime

        service = DeepLinkService(FakeRedis(), base_url="https://app.example")
        handler = DeepLinkResumeHandler(service, lambda **k: _ok(), runtime_factory=runtime_factory)
        dl = await service.mint(
            session_id="sess-surface",
            user_id="user-1",
            agent_id="assistant",
            channel="web",
            action_payload={
                "version": "v1.0",
                "action": {
                    "name": "approve",
                    "surfaceId": "main",
                    "sourceComponentId": "btn1",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "context": {},
                    "dataModel": {"count": 3},
                },
            },
        )

        _body, status = await handler.handle(dl.token_id)
        assert status == 200

        state = await store.get("sess-surface", "main")
        assert state is not None
        assert state.data_model == {"count": 3}

    async def test_structured_message_shape_unchanged(self):
        """Teams + Telegram depend on this exact string."""
        from parrot.outputs.a2ui.deeplink import ResumePayload

        payload = ResumePayload(
            session_id="s", user_id="u", agent_id="a", channel="web", action_payload=_action_envelope("go")
        )
        assert json.loads(build_structured_message(payload))["type"] == "a2ui_action"

    async def test_expired_token_still_410(self):
        service = DeepLinkService(FakeRedis(), base_url="https://app.example")
        spy_runtime = _SpyRuntime()

        async def runtime_factory(agent_id, user_id):
            return spy_runtime

        handler = DeepLinkResumeHandler(service, lambda **k: _ok(), runtime_factory=runtime_factory)
        body, status = await handler.handle("does-not-exist")
        assert status == 410
        assert "expired" in body["detail"].lower()
        assert spy_runtime.calls == []

    async def test_get_landing_does_not_consume(self):
        service = DeepLinkService(FakeRedis(), base_url="https://app.example")
        spy_runtime = _SpyRuntime()

        async def runtime_factory(agent_id, user_id):
            return spy_runtime

        handler = DeepLinkResumeHandler(service, lambda **k: _ok(), runtime_factory=runtime_factory)
        dl = await service.mint(
            session_id="s", user_id="u", agent_id="a", channel="web", action_payload=_action_envelope("go")
        )
        handler.render_landing(dl.token_id)
        assert spy_runtime.calls == []
        _body, status = await handler.handle(dl.token_id)
        assert status == 200
        assert len(spy_runtime.calls) == 1

    async def test_no_runtime_factory_skips_dispatch_without_error(self):
        """runtime_factory=None (default) — resume still works, just no dispatch."""
        service = DeepLinkService(FakeRedis(), base_url="https://app.example")
        handler = DeepLinkResumeHandler(service, lambda **k: _ok())
        dl = await service.mint(
            session_id="s", user_id="u", agent_id="a", channel="web", action_payload=_action_envelope("go")
        )
        _body, status = await handler.handle(dl.token_id)
        assert status == 200
