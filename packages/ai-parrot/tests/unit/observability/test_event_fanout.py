"""FEAT-710 TASK-4553 — event fan-out wiring."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    BeforeInvokeEvent,
    ClientCallFailedEvent,
)
from parrot.observability import bootstrap, fanout
from parrot.observability.fanout import redact_usage_event


class _FakeRegistry:
    """Record fan-out registry operations without global-state leakage."""

    def __init__(self) -> None:
        self.attach_calls: list[tuple[Any, Any]] = []
        self.subscriptions: dict[str, tuple[type, Any, bool]] = {}
        self.unsubscribed: list[str] = []
        self.detached = 0

    def attach_bus(self, bus: Any, *, serializer: Any = None) -> None:
        """Record the attached bus and serializer."""
        self.attach_calls.append((bus, serializer))

    def subscribe(self, event_type: type, callback: Any, *, forward_to_bus: bool = False) -> str:
        """Record and return a synthetic subscription identifier."""
        subscription_id = f"sub-{len(self.subscriptions)}"
        self.subscriptions[subscription_id] = (event_type, callback, forward_to_bus)
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Record removal of a subscription."""
        self.unsubscribed.append(subscription_id)
        return self.subscriptions.pop(subscription_id, None) is not None

    def detach_bus(self) -> None:
        """Record detachment of the bus."""
        self.detached += 1


class _FakeBus:
    """Minimal injected Streams/publish-only bus."""

    def __init__(self, *, transport: str = "streams", publish_only: bool = True) -> None:
        self.transport = transport
        self.publish_only = publish_only
        self.closed = 0

    async def close(self) -> None:
        """Record asynchronous bus closure."""
        self.closed += 1


@pytest.fixture(autouse=True)
def _reset_fanout_state() -> Iterator[None]:
    """Keep fan-out module globals isolated between tests."""
    fanout._BUS = None
    fanout._SUB_IDS.clear()
    yield
    fanout._BUS = None
    fanout._SUB_IDS.clear()


def test_redaction_drops_error_message() -> None:
    """Sensitive failure text is never included in bus payloads."""
    payload = redact_usage_event(
        ClientCallFailedEvent(trace_context=None, error_message="secret prompt", tenant="t1")
    )
    assert payload is not None and "error_message" not in payload and payload["tenant"] == "t1"


def test_other_events_are_skipped() -> None:
    """Only the four declared usage events receive serialized payloads."""
    assert redact_usage_event(BeforeInvokeEvent(trace_context=None)) is None
    assert redact_usage_event(AfterClientCallEvent(trace_context=None)) is not None


@pytest.mark.asyncio
async def test_setup_idempotent_and_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated setup creates four subscriptions and teardown releases all resources."""
    registry = _FakeRegistry()
    bus = _FakeBus()
    calculator_calls: list[None] = []
    monkeypatch.setattr(fanout, "get_global_registry", lambda: registry)
    monkeypatch.setattr(fanout, "ensure_shared_cost_calculator", lambda: calculator_calls.append(None))

    fanout.setup_event_fanout(bus)
    fanout.setup_event_fanout(bus)

    assert len(registry.attach_calls) == 1
    assert len(registry.subscriptions) == 4
    assert all(forward for _, _, forward in registry.subscriptions.values())
    assert len(calculator_calls) == 1

    await fanout.shutdown_event_fanout()

    assert len(registry.unsubscribed) == 4
    assert registry.detached == 1
    assert bus.closed == 1


def test_flag_off_does_not_setup_fanout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default bootstrap path does not import or attach fan-out."""
    monkeypatch.delenv("PARROT_EVENT_FANOUT_ENABLED", raising=False)
    monkeypatch.setattr(bootstrap, "_do_bootstrap", lambda: None)
    monkeypatch.setattr(bootstrap, "_BOOTSTRAPPED", False)

    bootstrap.ensure_observability_bootstrapped()

    assert fanout._BUS is None


@pytest.mark.parametrize(
    ("transport", "publish_only"),
    (("memory", True), ("streams", False)),
)
def test_bad_injected_bus_fails_fast(transport: str, publish_only: bool) -> None:
    """Injected buses must preserve the durable publisher-only contract."""
    with pytest.raises(RuntimeError, match="transport='streams'.*publish_only=True"):
        fanout.setup_event_fanout(_FakeBus(transport=transport, publish_only=publish_only))


def test_missing_or_unwritable_outbox_dir_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bus construction refuses missing and non-writable outbox locations."""
    monkeypatch.delenv("PARROT_EVENT_FANOUT_OUTBOX_DIR", raising=False)
    monkeypatch.setattr(fanout, "_config_value", lambda name, fallback=None: fallback)
    with pytest.raises(RuntimeError, match="OUTBOX_DIR is required"):
        fanout.setup_event_fanout()

    not_a_directory = tmp_path / "outbox-file"
    not_a_directory.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(
        fanout,
        "_config_value",
        lambda name, fallback=None: str(not_a_directory) if name == "PARROT_EVENT_FANOUT_OUTBOX_DIR" else fallback,
    )
    with pytest.raises(RuntimeError, match="not a writable directory"):
        fanout.setup_event_fanout()


def test_constructed_bus_uses_required_durable_options(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Environment-backed construction selects Streams, publish-only, and a process outbox."""
    captured: dict[str, Any] = {}
    registry = _FakeRegistry()

    class _ConstructedBus(_FakeBus):
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            super().__init__()

    values = {
        "PARROT_EVENT_FANOUT_REDIS_URL": "redis://example/0",
        "PARROT_EVENT_FANOUT_CHANNEL_PREFIX": "custom:events:",
        "PARROT_EVENT_FANOUT_OUTBOX_DIR": str(tmp_path),
    }
    monkeypatch.setattr(fanout, "EventBus", _ConstructedBus)
    monkeypatch.setattr(fanout, "_config_value", lambda name, fallback=None: values.get(name, fallback))
    monkeypatch.setattr(fanout, "get_global_registry", lambda: registry)
    monkeypatch.setattr(fanout, "ensure_shared_cost_calculator", lambda: SimpleNamespace())

    fanout.setup_event_fanout()

    assert captured["redis_url"] == "redis://example/0"
    assert captured["transport"] == "streams"
    assert captured["publish_only"] is True
    assert captured["channel_prefix"] == "custom:events:"
    assert Path(captured["outbox"]).parent == tmp_path
