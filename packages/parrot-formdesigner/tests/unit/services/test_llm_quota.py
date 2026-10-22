"""Unit tests for the LLM quota (FEAT-728, TASK-4626)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from parrot_formdesigner.services.llm_quota import InProcessSlidingWindow, LLMQuota, QuotaDecision


class FakeClock:
    """Monotonic clock the tests advance by hand — no sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _request(*, session: dict | None = None, remote: str = "203.0.113.7", headers: dict | None = None) -> MagicMock:
    """MagicMock request shaped like the public-form path (no session by default)."""
    req = MagicMock(spec="aiohttp.web.Request")
    req.match_info = {"form_uid": "test-form"}
    req.query = MagicMock()
    req.query.get = MagicMock(return_value="")
    req.json = MagicMock(return_value={})
    # Production shape: navigator-auth always sets request["session"]; it is None for anonymous callers.
    req.session = session
    req.get = MagicMock(
        side_effect=lambda key, default=None: (
            "test-tenant" if key == "tenant" else (req.session if key == "session" else default)
        )
    )
    req.remote = remote
    req.headers = headers or {}

    # Make __contains__ and __getitem__ work for "session" key
    def __contains__(self, key):
        return key == "session"

    def __getitem__(self, key):
        if key == "session":
            return self.session
        raise KeyError(key)

    req.__contains__ = __contains__
    req.__getitem__ = __getitem__
    return req


class TestSlidingWindow:
    async def test_allows_under_limit(self) -> None:
        """limit consecutive acquires allowed — bounded by AC12"""
        clock = FakeClock()
        limiter = InProcessSlidingWindow(max_keys=100, clock=clock)
        key = "test-key"

        # First 10 should be allowed
        for i in range(10):
            decision = await limiter.acquire(key, limit=10, window_s=60.0)
            assert decision.allowed is True, f"Acquire {i} should be allowed"

    async def test_denies_over_limit_with_retry_after(self) -> None:
        """the limit+1-th is denied with retry_after_s >= 1 — bounded by AC12"""
        clock = FakeClock()
        limiter = InProcessSlidingWindow(max_keys=100, clock=clock)
        key = "test-key"

        # First 10 should be allowed
        for i in range(10):
            decision = await limiter.acquire(key, limit=10, window_s=60.0)
            assert decision.allowed is True, f"Acquire {i} should be allowed"

        # 11th should be denied with retry_after_s >= 1
        decision = await limiter.acquire(key, limit=10, window_s=60.0)
        assert decision.allowed is False
        assert decision.retry_after_s >= 1, f"retry_after_s should be >= 1, got {decision.retry_after_s}"
        # All hits landed at t=0, so the oldest expires a full window later.
        assert decision.retry_after_s == 60

    async def test_window_slides(self) -> None:
        """advance past window_s -> allowed again — bounded by AC13 (monotonic clock)"""
        clock = FakeClock()
        limiter = InProcessSlidingWindow(max_keys=100, clock=clock)
        key = "test-key"

        # First 10 should be allowed
        for i in range(10):
            decision = await limiter.acquire(key, limit=10, window_s=60.0)
            assert decision.allowed is True, f"Acquire {i} should be allowed"

        # 11th should be denied
        decision = await limiter.acquire(key, limit=10, window_s=60.0)
        assert decision.allowed is False

        # Advance past the window (more than window_s to ensure oldest hit is pruned)
        clock.advance(120.0)

        # Now should be allowed again
        decision = await limiter.acquire(key, limit=10, window_s=60.0)
        assert decision.allowed is True

    async def test_keys_are_independent(self) -> None:
        """two keys do not share a budget — bounded by AC12"""
        clock = FakeClock()
        limiter = InProcessSlidingWindow(max_keys=100, clock=clock)

        key1 = "key1"
        key2 = "key2"

        # Fill key1 to limit
        for i in range(10):
            decision = await limiter.acquire(key1, limit=10, window_s=60.0)
            assert decision.allowed is True, f"Acquire {i} for key1 should be allowed"

        # key1 should be denied
        decision = await limiter.acquire(key1, limit=10, window_s=60.0)
        assert decision.allowed is False

        # key2 should still be allowed (independent)
        decision = await limiter.acquire(key2, limit=10, window_s=60.0)
        assert decision.allowed is True

    async def test_evicts_lru_at_max_keys(self) -> None:
        """max_keys=2, three keys -> map never exceeds 2 — bounded by AC13"""
        clock = FakeClock()
        limiter = InProcessSlidingWindow(max_keys=2, clock=clock)

        key1 = "key1"
        key2 = "key2"
        key3 = "key3"

        # Add key1 and key2
        await limiter.acquire(key1, limit=10, window_s=60.0)
        await limiter.acquire(key2, limit=10, window_s=60.0)

        # Map should have 2 keys
        assert len(limiter._hits) == 2

        # Add key3 (should evict LRU, which is key1)
        await limiter.acquire(key3, limit=10, window_s=60.0)

        # Map should still have 2 keys (key2 and key3)
        assert len(limiter._hits) == 2
        assert key1 not in limiter._hits
        assert key2 in limiter._hits
        assert key3 in limiter._hits


class TestIdentity:
    def test_prefers_session_user(self) -> None:
        """session user id is preferred — bounded by AC12"""
        quota = LLMQuota()
        req = _request(session={"id": "user-123"})
        assert quota.identity(req) == "user-123"

    def test_falls_back_to_remote(self) -> None:
        """no session -> request.remote — bounded by AC12"""
        quota = LLMQuota()
        req = _request(session=None, remote="203.0.113.7")
        assert quota.identity(req) == "203.0.113.7"

    def test_ignores_forwarded_for_by_default(self) -> None:
        """X-Forwarded-For present, trust_forwarded_for=False -> remote wins — §7"""
        quota = LLMQuota()
        headers = {"X-Forwarded-For": "10.0.0.1, 203.0.113.7"}
        req = _request(session=None, remote="203.0.113.7", headers=headers)
        assert quota.identity(req) == "203.0.113.7"

    def test_uses_forwarded_for_when_trusted(self) -> None:
        """first hop only when trusted — §7"""
        quota = LLMQuota(trust_forwarded_for=True)
        headers = {"X-Forwarded-For": "10.0.0.1, 203.0.113.7"}
        req = _request(session=None, remote="203.0.113.7", headers=headers)
        assert quota.identity(req) == "10.0.0.1"


class TestQuotaPolicy:
    async def test_disabled_always_allows(self) -> None:
        """enabled=False never touches the backend — bounded by AC12"""
        quota = LLMQuota(enabled=False)
        req = _request()
        decision = await quota.acquire(req, tenant="test-tenant", form_uid="test-form")
        assert decision.allowed is True

    async def test_key_includes_tenant_and_form(self) -> None:
        """a recording fake backend sees ``{tenant}:{form_uid}:{identity}`` — AC12"""

        class RecordingBackend:
            def __init__(self) -> None:
                self.calls: list[tuple[str, int, float]] = []

            async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision:
                self.calls.append((key, limit, window_s))
                return QuotaDecision(allowed=True)

        backend = RecordingBackend()
        quota = LLMQuota(backend=backend)
        req = _request(session={"id": "user-123"})

        await quota.acquire(req, tenant="tenant-a", form_uid="form-uid")

        assert len(backend.calls) == 1
        key, limit, window_s = backend.calls[0]
        assert key == "tenant-a:form-uid:user-123"
        assert limit == 10
        assert window_s == 60.0

    async def test_backend_failure_allows(self) -> None:
        """a backend raising -> allowed=True, warning logged — bounded by §7"""

        class FailingBackend:
            async def acquire(self, key: str, *, limit: int, window_s: float) -> QuotaDecision:
                raise RuntimeError("backend down")

        quota = LLMQuota(backend=FailingBackend())
        req = _request()

        # Should not raise, should allow
        decision = await quota.acquire(req, tenant="test-tenant", form_uid="test-form")
        assert decision.allowed is True
