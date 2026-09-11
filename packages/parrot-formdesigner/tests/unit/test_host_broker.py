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


def _manifest(tier: CapabilityTier = CapabilityTier.BROKERED, **allowlist_kwargs) -> CapabilityManifest:
    return CapabilityManifest(tier=tier, allowlist=BrokerAllowlist(**allowlist_kwargs))


@pytest.fixture(autouse=True)
def _clear_fake_session_calls():
    _FakeClientSession.calls = []
    yield
    _FakeClientSession.calls = []


class _FakeContent:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def read(self, n: int = -1) -> bytes:
        return self._body[:n] if n >= 0 else self._body


class _FakeResponse:
    def __init__(self, status: int = 200, body: str = "ok") -> None:
        self.status = status
        self.content = _FakeContent(body.encode("utf-8"))

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeClientSession:
    """Drop-in stand-in for aiohttp.ClientSession — no real network I/O.

    Records every call's (method, url, kwargs) so tests can assert the
    actual outbound request never escapes the allowlisted host/args.
    """

    calls: list[tuple[str, object, dict]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> "_FakeClientSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def request(self, method: str, url: object, **kwargs: object) -> _FakeResponse:
        _FakeClientSession.calls.append((method, url, dict(kwargs)))
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
    response = await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")
    assert response.denied is False
    assert response.result["status"] == 200


async def test_broker_denies_non_broker_eligible_tier() -> None:
    """Defense in depth: PURE/HELPERS manifests are never honored, even
    with a populated allowlist (handle() is only meant to be reached via
    the BROKERED/TOOLKIT gVisor path)."""
    broker = HostBroker()
    manifest = _manifest(tier=CapabilityTier.PURE, http_hosts=("allowed.example.com",))
    request = BrokerRequest(kind="http_hosts", target="allowed.example.com")
    with pytest.raises(CapabilityDenied):
        await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")


async def test_broker_userinfo_path_is_denied_not_hijacked(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """SSRF regression test: a path crafted to look like '@evil.example' must
    be denied outright — never silently connect to a different host."""
    monkeypatch.setattr(
        "parrot_formdesigner.services.sandbox.broker.aiohttp.ClientSession",
        _FakeClientSession,
    )
    broker = HostBroker()
    manifest = _manifest(http_hosts=("allowed.example.com",))
    request = BrokerRequest(
        kind="http_hosts",
        target="allowed.example.com",
        args={"method": "GET", "path": "@evil.example.com/"},
    )
    with pytest.raises(CapabilityDenied):
        await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")

    # No outbound call was ever made, and the denial was logged.
    assert len(_FakeClientSession.calls) == 0
    assert "acme" in caplog.text


async def test_broker_allowed_path_targets_the_allowlisted_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A well-formed path is sent to exactly the allowlisted host, nothing else."""
    monkeypatch.setattr(
        "parrot_formdesigner.services.sandbox.broker.aiohttp.ClientSession",
        _FakeClientSession,
    )
    broker = HostBroker()
    manifest = _manifest(http_hosts=("allowed.example.com",))
    request = BrokerRequest(
        kind="http_hosts",
        target="allowed.example.com",
        args={"method": "GET", "path": "/webhook"},
    )
    await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")

    assert len(_FakeClientSession.calls) == 1
    _, url, _ = _FakeClientSession.calls[0]
    assert url.host == "allowed.example.com"
    assert url.path == "/webhook"


async def test_broker_strips_disallowed_args_and_disables_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only json/params are ever forwarded; redirects are always disabled
    regardless of what the snippet's args try to set."""
    monkeypatch.setattr(
        "parrot_formdesigner.services.sandbox.broker.aiohttp.ClientSession",
        _FakeClientSession,
    )
    broker = HostBroker()
    manifest = _manifest(http_hosts=("allowed.example.com",))
    request = BrokerRequest(
        kind="http_hosts",
        target="allowed.example.com",
        args={
            "method": "GET",
            "path": "/",
            "params": {"q": "1"},
            "proxy": "http://attacker.example.com",
            "ssl": False,
            "allow_redirects": True,
            "headers": {"X-Injected": "1"},
        },
    )
    await broker.handle(request, manifest, tenant="acme", handler_ref="x.onBeforeSubmit")

    assert len(_FakeClientSession.calls) == 1
    _, _, kwargs = _FakeClientSession.calls[0]
    assert kwargs == {"params": {"q": "1"}, "allow_redirects": False}
