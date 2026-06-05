"""Unit tests for the env-driven observability auto-boot."""

from __future__ import annotations

import pytest

from parrot.core.events.lifecycle.global_registry import get_global_registry, scope
from parrot.observability import bootstrap as boot

_ENV_KEYS = [
    "OBSERVABILITY_ENABLED", "OBSERVABILITY_BACKEND", "OBSERVABILITY_COST",
]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    boot.reset_bootstrap_for_tests()
    yield
    boot.reset_bootstrap_for_tests()


def _sub_count() -> int:
    return len(get_global_registry()._subscriptions)


def test_disabled_is_noop(monkeypatch) -> None:
    """With OBSERVABILITY_ENABLED unset, no global subscription is added."""
    with scope():
        before = _sub_count()
        boot.ensure_observability_bootstrapped()
        assert _sub_count() == before


def test_enabled_defaults_to_logging(monkeypatch) -> None:
    """OBSERVABILITY_ENABLED=true alone registers a logging usage subscriber."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    with scope():
        before = _sub_count()
        boot.ensure_observability_bootstrapped()
        assert _sub_count() == before + 1
        sub = boot._SUBSCRIBER
        assert sub is not None
        assert [r.name for r in sub.recorders] == ["logging"]


def test_bootstrap_is_idempotent(monkeypatch) -> None:
    """Calling the bootstrap twice registers exactly one subscription."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    with scope():
        before = _sub_count()
        boot.ensure_observability_bootstrapped()
        boot.ensure_observability_bootstrapped()
        assert _sub_count() == before + 1


def test_otel_backend_delegates_to_setup_telemetry(monkeypatch) -> None:
    """usage_backend=otel routes to setup_telemetry without the new subscriber."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_BACKEND", "otel")

    called = {}

    def _fake_setup(config):
        called["config"] = config
        return None

    import parrot.observability.setup as setup_mod
    monkeypatch.setattr(setup_mod, "setup_telemetry", _fake_setup)

    with scope():
        boot.ensure_observability_bootstrapped()

    assert "config" in called
    assert called["config"].usage_backend == "otel"
    assert boot._SUBSCRIBER is None  # lightweight path not used
