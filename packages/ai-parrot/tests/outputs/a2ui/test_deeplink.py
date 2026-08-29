"""Unit tests for the deep-link token service (TASK-1735; FEAT-470 TASK-2546 v1.0)."""

import pytest
from pydantic import ValidationError

from parrot.outputs.a2ui.deeplink import (
    DeepLinkExpiredError,
    DeepLinkService,
    ResumePayload,
)

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
    """Minimal async Redis stand-in with atomic GETDEL (Redis >= 6.2)."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.getdel_calls = 0

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)

    async def getdel(self, key):
        self.getdel_calls += 1
        return self.store.pop(key, None)

    def expire_now(self, key):
        """Simulate TTL expiry by dropping the key."""
        self.store.pop(key, None)


class LegacyFakeRedis:
    """Async Redis stand-in WITHOUT getdel (exercises the get+delete fallback)."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


def _service():
    return DeepLinkService(FakeRedis(), base_url="https://app.example", default_ttl=600)


class TestDeepLinkService:
    async def test_mint_returns_deeplink_with_ttl(self):
        svc = _service()
        dl = await svc.mint(
            session_id="s1",
            user_id="u1",
            agent_id="a1",
            channel="web",
            action_payload=_action_envelope("approve"),
        )
        assert dl.token_id in dl.url
        # Opaque token only — no payload in the URL.
        assert "approve" not in dl.url and "s1" not in dl.url
        assert dl.action_label == "approve"
        assert dl.expires_at is not None

    async def test_deeplink_single_use(self):
        svc = _service()
        dl = await svc.mint(
            session_id="s1",
            user_id="u1",
            agent_id="a1",
            channel="web",
            action_payload=_action_envelope("x"),
        )
        first = await svc.consume(dl.token_id)
        assert isinstance(first, ResumePayload)
        with pytest.raises(DeepLinkExpiredError):
            await svc.consume(dl.token_id)  # replay rejected

    async def test_expired_token_fails(self):
        svc = _service()
        dl = await svc.mint(
            session_id="s1",
            user_id="u1",
            agent_id="a1",
            channel="web",
            action_payload=_action_envelope("x"),
        )
        svc.redis.expire_now(svc._key(dl.token_id))  # simulate TTL expiry
        with pytest.raises(DeepLinkExpiredError):
            await svc.consume(dl.token_id)

    async def test_consume_uses_atomic_getdel_when_available(self):
        svc = _service()
        dl = await svc.mint(
            session_id="s",
            user_id="u",
            agent_id="a",
            channel="web",
            action_payload=_action_envelope("x"),
        )
        await svc.consume(dl.token_id)
        # The atomic GETDEL path was used (no TOCTOU get-then-delete window).
        assert svc.redis.getdel_calls == 1

    async def test_consume_fallback_without_getdel(self):
        svc = DeepLinkService(LegacyFakeRedis(), base_url="https://app.example")
        dl = await svc.mint(
            session_id="s",
            user_id="u",
            agent_id="a",
            channel="web",
            action_payload=_action_envelope("x"),
        )
        payload = await svc.consume(dl.token_id)
        assert payload.session_id == "s"
        with pytest.raises(DeepLinkExpiredError):
            await svc.consume(dl.token_id)  # single-use still holds via fallback

    async def test_consume_returns_server_side_payload(self):
        svc = _service()
        dl = await svc.mint(
            session_id="s9",
            user_id="u9",
            agent_id="a9",
            channel="web",
            action_payload=_action_envelope("approve", row=3),
        )
        payload = await svc.consume(dl.token_id)
        assert payload.session_id == "s9"
        assert payload.user_id == "u9"
        assert payload.agent_id == "a9"
        assert payload.channel == "web"
        assert payload.action_payload == _action_envelope("approve", row=3)


class TestResumePayloadActionEnvelope:
    # These are synchronous, but the module-level `pytestmark` (asyncio) still
    # applies to every test in the file — declare them `async def` (no awaits
    # needed) to satisfy pytest-asyncio rather than fight the module mark.
    async def test_deeplink_payload_is_action_envelope(self):
        # A valid v1.0 'action' envelope round-trips as-is.
        envelope = _action_envelope("approve")
        payload = ResumePayload(
            session_id="s",
            user_id="u",
            agent_id="a",
            channel="web",
            action_payload=envelope,
        )
        assert payload.action_payload == envelope

    async def test_non_action_payload_raises_value_error(self):
        # A well-formed A2UIRendererMessage envelope whose key is NOT 'action'.
        non_action = {
            "version": "v1.0",
            "error": {"code": "VALIDATION_FAILED", "message": "bad", "surfaceId": "m", "path": "/x"},
        }
        with pytest.raises(ValueError):
            ResumePayload(
                session_id="s",
                user_id="u",
                agent_id="a",
                channel="web",
                action_payload=non_action,
            )

    async def test_malformed_payload_raises_value_error(self):
        with pytest.raises(ValidationError):
            ResumePayload(
                session_id="s",
                user_id="u",
                agent_id="a",
                channel="web",
                action_payload={"not": "an envelope"},
            )
