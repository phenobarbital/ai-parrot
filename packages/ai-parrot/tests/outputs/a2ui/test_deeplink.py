"""Unit tests for the deep-link token service (TASK-1735)."""

import pytest

from parrot.outputs.a2ui.deeplink import (
    DeepLinkExpiredError,
    DeepLinkService,
    ResumePayload,
)

pytestmark = pytest.mark.asyncio


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
            action_payload={"label": "Approve", "action": "approve"},
        )
        assert dl.token_id in dl.url
        # Opaque token only — no payload in the URL.
        assert "approve" not in dl.url and "s1" not in dl.url
        assert dl.action_label == "Approve"
        assert dl.expires_at is not None

    async def test_deeplink_single_use(self):
        svc = _service()
        dl = await svc.mint(
            session_id="s1", user_id="u1", agent_id="a1", channel="web",
            action_payload={"action": "x"},
        )
        first = await svc.consume(dl.token_id)
        assert isinstance(first, ResumePayload)
        with pytest.raises(DeepLinkExpiredError):
            await svc.consume(dl.token_id)  # replay rejected

    async def test_expired_token_fails(self):
        svc = _service()
        dl = await svc.mint(
            session_id="s1", user_id="u1", agent_id="a1", channel="web",
            action_payload={"action": "x"},
        )
        svc.redis.expire_now(svc._key(dl.token_id))  # simulate TTL expiry
        with pytest.raises(DeepLinkExpiredError):
            await svc.consume(dl.token_id)

    async def test_consume_uses_atomic_getdel_when_available(self):
        svc = _service()
        dl = await svc.mint(
            session_id="s", user_id="u", agent_id="a", channel="web",
            action_payload={"action": "x"},
        )
        await svc.consume(dl.token_id)
        # The atomic GETDEL path was used (no TOCTOU get-then-delete window).
        assert svc.redis.getdel_calls == 1

    async def test_consume_fallback_without_getdel(self):
        svc = DeepLinkService(LegacyFakeRedis(), base_url="https://app.example")
        dl = await svc.mint(
            session_id="s", user_id="u", agent_id="a", channel="web",
            action_payload={"action": "x"},
        )
        payload = await svc.consume(dl.token_id)
        assert payload.session_id == "s"
        with pytest.raises(DeepLinkExpiredError):
            await svc.consume(dl.token_id)  # single-use still holds via fallback

    async def test_consume_returns_server_side_payload(self):
        svc = _service()
        dl = await svc.mint(
            session_id="s9", user_id="u9", agent_id="a9", channel="web",
            action_payload={"action": "approve", "row": 3},
        )
        payload = await svc.consume(dl.token_id)
        assert payload.session_id == "s9"
        assert payload.user_id == "u9"
        assert payload.agent_id == "a9"
        assert payload.channel == "web"
        assert payload.action_payload == {"action": "approve", "row": 3}
