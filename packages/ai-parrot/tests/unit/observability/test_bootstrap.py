"""Unit tests for the env-driven observability auto-boot."""

from __future__ import annotations

import pytest

from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope
from parrot.observability import bootstrap as boot

@pytest.fixture(autouse=True)
def _clean():
    """Reset the bootstrap module's own globals (``_SUBSCRIBER`` /
    ``_ATEXIT_REGISTERED``) around each test.

    Environment hermeticity and telemetry-provider resets are handled by the
    package-level autouse fixtures in ``conftest.py``; this only covers the
    bootstrap-specific state the shared fixtures don't touch.
    """
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


def test_openlit_escalates_to_otel(monkeypatch) -> None:
    """OBSERVABILITY_OPENLIT=true forces the otel path even with backend unset."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_OPENLIT", "true")
    # Backend deliberately left unset (resolves to "none"/"logging" normally).

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
    assert called["config"].enable_openlit is True
    assert boot._SUBSCRIBER is None  # otel path, not the lightweight subscriber


def test_traceloop_backend_activates(monkeypatch) -> None:
    """OBSERVABILITY_TRACELOOP=true forces the traceloop backend (not otel/logging)."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_TRACELOOP", "true")

    called = {}
    import parrot.observability.traceloop_integration as tl_mod
    monkeypatch.setattr(tl_mod, "setup_traceloop", lambda cfg: called.__setitem__("cfg", cfg))

    with scope():
        boot.ensure_observability_bootstrapped()

    assert "cfg" in called
    assert called["cfg"].usage_backend == "traceloop"
    assert boot._SUBSCRIBER is None  # not the lightweight path


def test_traceloop_and_openlit_are_mutually_exclusive(monkeypatch) -> None:
    """When both are set, Traceloop wins and OpenLIT is disabled."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_TRACELOOP", "true")
    monkeypatch.setenv("OBSERVABILITY_OPENLIT", "true")

    called = {}
    import parrot.observability.traceloop_integration as tl_mod
    monkeypatch.setattr(tl_mod, "setup_traceloop", lambda cfg: called.__setitem__("cfg", cfg))

    with scope():
        boot.ensure_observability_bootstrapped()

    assert called["cfg"].usage_backend == "traceloop"
    assert called["cfg"].enable_openlit is False


def test_atexit_flush_registered_once(monkeypatch) -> None:
    """A successful boot registers the atexit flush hook exactly once."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")

    registered = []
    import parrot.observability.bootstrap as boot_mod
    monkeypatch.setattr(boot_mod.atexit, "register", registered.append)

    with scope():
        boot.ensure_observability_bootstrapped()
        boot.ensure_observability_bootstrapped()  # idempotent

    assert registered == [boot.shutdown_observability]
    assert boot._ATEXIT_REGISTERED is True


def test_atexit_not_registered_when_disabled(monkeypatch) -> None:
    """No flush hook is registered when observability is disabled."""
    registered = []
    import parrot.observability.bootstrap as boot_mod
    monkeypatch.setattr(boot_mod.atexit, "register", registered.append)

    with scope():
        boot.ensure_observability_bootstrapped()

    assert registered == []
    assert boot._ATEXIT_REGISTERED is False


def test_shutdown_observability_aggregates_and_is_idempotent(monkeypatch) -> None:
    """shutdown_observability() calls both teardown paths and never raises."""
    calls = {"otel": 0, "usage": 0}

    import parrot.observability.setup as setup_mod
    monkeypatch.setattr(
        setup_mod, "shutdown_telemetry",
        lambda: calls.__setitem__("otel", calls["otel"] + 1),
    )
    import parrot.observability.bootstrap as boot_mod
    monkeypatch.setattr(
        boot_mod, "shutdown_usage_recording",
        lambda: calls.__setitem__("usage", calls["usage"] + 1),
    )

    boot.shutdown_observability()
    boot.shutdown_observability()

    assert calls == {"otel": 2, "usage": 2}


def test_shutdown_observability_swallows_errors(monkeypatch) -> None:
    """A failure in one teardown path must not block the other or raise."""
    import parrot.observability.setup as setup_mod

    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(setup_mod, "shutdown_telemetry", _boom)
    usage_called = {"n": 0}
    import parrot.observability.bootstrap as boot_mod
    monkeypatch.setattr(
        boot_mod, "shutdown_usage_recording",
        lambda: usage_called.__setitem__("n", usage_called["n"] + 1),
    )

    boot.shutdown_observability()  # must not raise

    assert usage_called["n"] == 1
