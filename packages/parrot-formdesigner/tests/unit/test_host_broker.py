"""Unit tests for HostBroker — FEAT-459 / TASK-3171."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.snippets import (
    BrokerAllowlist,
    CapabilityDenied,
    CapabilityManifest,
    CapabilityTier,
)
from parrot_formdesigner.services.sandbox.broker import HostBroker
from parrot_formdesigner.services.sandbox.protocol import BrokerRequest


def _manifest(**allowlist_kwargs) -> CapabilityManifest:
    return CapabilityManifest(
        tier=CapabilityTier.BROKERED, allowlist=BrokerAllowlist(**allowlist_kwargs)
    )


class _FakeResponse:
    def __init__(self, status: int = 200, body: str = "ok") -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeClientSession:
    """Drop-in stand-in for aiohttp.ClientSession — no real network I/O."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "_FakeClientSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def request(self, method: str, url: str, **kwargs: object) -> _FakeResponse:
        return _FakeResponse()


async def test_broker_denies_undeclared_host() -> None:
    broker = HostBroker()
    manifest = _manifest(http_hosts=("allowed.example.com",))
    request = BrokerRequest(kind="http_hosts", target="evil.example.com")
    with pytest.raises(CapabilityDenied):
        await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")


async def test_broker_denies_undeclared_table() -> None:
    broker = HostBroker()
    manifest = _manifest(query_tables=("orders",))
    request = BrokerRequest(kind="query_tables", target="users")
    with pytest.raises(CapabilityDenied):
        await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")


async def test_broker_denies_wildcard_style_host_match() -> None:
    """Exact match only — a declared 'example.com' does not cover 'sub.example.com'."""
    broker = HostBroker()
    manifest = _manifest(http_hosts=("example.com",))
    request = BrokerRequest(kind="http_hosts", target="sub.example.com")
    with pytest.raises(CapabilityDenied):
        await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")


async def test_broker_enforces_call_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "parrot_formdesigner.services.sandbox.broker.aiohttp.ClientSession",
        _FakeClientSession,
    )
    broker = HostBroker(max_calls_per_invocation=1)
    manifest = _manifest(http_hosts=("allowed.example.com",))
    request = BrokerRequest(
        kind="http_hosts",
        target="allowed.example.com",
        args={"method": "GET", "path": "/"},
    )
    # First call succeeds (mocked, no real network I/O).
    first = await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")
    assert first.denied is False

    # Second call must raise due to the call cap, not a network error.
    with pytest.raises(CapabilityDenied):
        await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")


async def test_broker_logs_denial_with_tenant_and_handler_ref(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broker = HostBroker()
    manifest = _manifest(http_hosts=())
    request = BrokerRequest(kind="http_hosts", target="evil.example.com")
    with pytest.raises(CapabilityDenied):
        await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")
    assert "acme" in caplog.text
    assert "x.onBeforeSubmit" in caplog.text


async def test_broker_allows_declared_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "parrot_formdesigner.services.sandbox.broker.aiohttp.ClientSession",
        _FakeClientSession,
    )
    broker = HostBroker()
    manifest = _manifest(http_hosts=("allowed.example.com",))
    request = BrokerRequest(
        kind="http_hosts",
        target="allowed.example.com",
        args={"method": "GET", "path": "/"},
    )
    response = await broker.handle(
        request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit"
    )
    assert response.denied is False
    assert response.result["status"] == 200
