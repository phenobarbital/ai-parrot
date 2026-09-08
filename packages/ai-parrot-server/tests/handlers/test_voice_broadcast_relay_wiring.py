"""The cross-worker relay must actually be reachable (FEAT-537 review fix).

`WorkerRelayServer` and `WorkerAddressRegistry.register()` existed but were
never called by any production wiring, so `attach_speaker_input` always failed
with `owner_lost` for a speaker admitted on a worker that did not own the
producer. Every unit test passed regardless, because they all constructed the
relay by hand. These tests exercise the wiring itself.
"""

from __future__ import annotations

from typing import Any, List

import pytest
from aiohttp import web


def _ensure_server_handler(monkeypatch: Any) -> None:
    """Make `parrot.manager` importable in the namespace-package layout."""
    import parrot

    for entry in list(getattr(parrot, "__path__", [])):
        candidate = entry.replace("ai-parrot/src/parrot", "ai-parrot-server/src/parrot")
        if candidate not in parrot.__path__:
            parrot.__path__.append(candidate)


@pytest.fixture
def manager(monkeypatch):
    _ensure_server_handler(monkeypatch)
    import logging

    from parrot.manager.manager import BotManager

    instance = BotManager.__new__(BotManager)
    instance.logger = logging.getLogger("test.manager")
    return instance


class _Service:
    worker_id = "worker-a"


class _Registry:
    def __init__(self) -> None:
        self.registered: List[tuple] = []
        self.unregistered: List[str] = []

    async def register(self, worker_id: str, url: str) -> None:
        from parrot.integrations.liveavatar.broadcast.worker_transport import (
            WorkerAddressRegistry,
        )

        WorkerAddressRegistry.validate_url(url)
        self.registered.append((worker_id, url))

    async def unregister(self, worker_id: str) -> None:
        self.unregistered.append(worker_id)


def test_relay_is_off_unless_an_address_is_configured(manager, monkeypatch) -> None:
    """Single-worker deployments must not grow an extra listening port."""
    monkeypatch.delenv("PARROT_BROADCAST_WORKER_URL", raising=False)
    app = web.Application()
    before = len(app.on_startup)
    assert manager._register_worker_relay(app, _Service(), _Registry()) is False
    assert len(app.on_startup) == before


def test_relay_refuses_to_serve_without_a_token(manager, monkeypatch) -> None:
    """An unauthenticated relay would let anything reaching the port speak."""
    monkeypatch.setenv("PARROT_BROADCAST_WORKER_URL", "ws://127.0.0.1:9401")
    monkeypatch.delenv("PARROT_BROADCAST_WORKER_TOKEN", raising=False)
    app = web.Application()
    before = len(app.on_startup)
    assert manager._register_worker_relay(app, _Service(), _Registry()) is False
    assert len(app.on_startup) == before


def test_relay_refuses_a_non_websocket_address(manager, monkeypatch) -> None:
    monkeypatch.setenv("PARROT_BROADCAST_WORKER_URL", "http://evil.example/relay")
    monkeypatch.setenv("PARROT_BROADCAST_WORKER_TOKEN", "shared")
    app = web.Application()
    assert manager._register_worker_relay(app, _Service(), _Registry()) is False


def test_bind_target_defaults_to_the_advertised_address(manager, monkeypatch) -> None:
    monkeypatch.delenv("PARROT_BROADCAST_WORKER_BIND", raising=False)
    assert manager._relay_bind_target("ws://10.0.0.4:9401") == ("10.0.0.4", 9401)
    # A proxied deployment binds somewhere other than it advertises.
    monkeypatch.setenv("PARROT_BROADCAST_WORKER_BIND", "0.0.0.0:9999")
    assert manager._relay_bind_target("wss://worker-a.internal") == ("0.0.0.0", 9999)


async def test_relay_starts_listens_and_registers_then_cleans_up(manager, monkeypatch, unused_tcp_port) -> None:
    """The end-to-end wiring: a port is served and the address advertised."""
    url = f"ws://127.0.0.1:{unused_tcp_port}"
    monkeypatch.setenv("PARROT_BROADCAST_WORKER_URL", url)
    monkeypatch.setenv("PARROT_BROADCAST_WORKER_TOKEN", "shared")
    registry = _Registry()
    app = web.Application()
    before = len(app.on_startup)

    assert manager._register_worker_relay(app, _Service(), registry) is True
    assert len(app.on_startup) == before + 1
    start, stop = app.on_startup[-1], app.on_cleanup[-1]

    await start(app)
    try:
        # Advertised to peers, so attach_speaker_input can resolve this owner.
        assert registry.registered == [("worker-a", url)]

        # And the port genuinely answers: an unauthenticated peer is refused
        # rather than the connection being refused outright.
        import aiohttp

        async with aiohttp.ClientSession() as session:
            from parrot.integrations.liveavatar.broadcast.worker_transport import (
                RELAY_ROUTE,
            )

            async with session.get(f"http://127.0.0.1:{unused_tcp_port}{RELAY_ROUTE}") as resp:
                assert resp.status in (401, 403)
    finally:
        await stop(app)
    assert registry.unregistered == ["worker-a"]
