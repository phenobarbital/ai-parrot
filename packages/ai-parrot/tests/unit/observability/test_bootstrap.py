"""Unit tests for the env-driven observability auto-boot."""

from __future__ import annotations

import logging

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
    """OBSERVABILITY_ENABLED=true alone registers a logging usage subscriber.

    FEAT-479: ``UsageRecordingSubscriber.register()`` now subscribes to
    both ``AfterClientCallEvent`` and ``ClientCallFailedEvent`` (Module 4a),
    so one provider now adds 2 subscriptions, not 1.
    """
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    with scope():
        before = _sub_count()
        boot.ensure_observability_bootstrapped()
        assert _sub_count() == before + 2
        sub = boot._SUBSCRIBER
        assert sub is not None
        assert [r.name for r in sub.recorders] == ["logging"]


def test_bootstrap_is_idempotent(monkeypatch) -> None:
    """Calling the bootstrap twice registers exactly one provider's worth of
    subscriptions (2, per FEAT-479 — see test_enabled_defaults_to_logging)."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    with scope():
        before = _sub_count()
        boot.ensure_observability_bootstrapped()
        boot.ensure_observability_bootstrapped()
        assert _sub_count() == before + 2


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


def test_otel_backend_passes_env_switches_to_setup_telemetry(monkeypatch) -> None:
    """FEAT-705 AC6: env switches reach setup_telemetry through auto-boot."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_BACKEND", "otel")
    monkeypatch.setenv("OBSERVABILITY_TRACES", "false")
    monkeypatch.setenv("OBSERVABILITY_METRICS", "true")
    monkeypatch.setenv("OBSERVABILITY_METRIC_EXPORT_INTERVAL_MS", "5000")

    called = {}

    def _fake_setup(config):
        called["config"] = config
        return None

    import parrot.observability.setup as setup_mod

    monkeypatch.setattr(setup_mod, "setup_telemetry", _fake_setup)

    with scope():
        boot.ensure_observability_bootstrapped()

    config = called["config"]
    assert config.enable_traces is False
    assert config.enable_metrics is True
    assert config.metric_export_interval_ms == 5000


def test_openlit_flag_no_longer_escalates_to_otel(monkeypatch) -> None:
    """FEAT-462: OBSERVABILITY_OPENLIT=true is a deprecated no-op — it no
    longer escalates the backend to otel. With backend otherwise unset, the
    lightweight 'logging' path activates instead, exactly as if the flag
    were never set."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_OPENLIT", "true")

    called = {}

    def _fake_setup(config):
        called["config"] = config

    import parrot.observability.setup as setup_mod

    monkeypatch.setattr(setup_mod, "setup_telemetry", _fake_setup)

    with scope():
        boot.ensure_observability_bootstrapped()

    assert "config" not in called  # setup_telemetry (otel path) never called
    assert boot._SUBSCRIBER is not None  # lightweight 'logging' path used
    assert [r.name for r in boot._SUBSCRIBER.recorders] == ["logging"]


def test_traceloop_flag_no_longer_activates_traceloop_backend(monkeypatch) -> None:
    """FEAT-462: OBSERVABILITY_TRACELOOP=true is a deprecated no-op —
    _do_bootstrap() no longer imports or references traceloop_integration
    at all (the module itself is deleted — TASK-2476). The lightweight
    'logging' path activates instead, exactly as if the flag were unset."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_TRACELOOP", "true")

    with scope():
        boot.ensure_observability_bootstrapped()

    assert boot._SUBSCRIBER is not None  # lightweight 'logging' path used instead
    assert [r.name for r in boot._SUBSCRIBER.recorders] == ["logging"]


def test_both_deprecated_flags_set_falls_back_to_logging(monkeypatch) -> None:
    """FEAT-462: with both deprecated flags set, neither triggers special
    handling — the lightweight 'logging' path activates, same as if neither
    flag were set."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_TRACELOOP", "true")
    monkeypatch.setenv("OBSERVABILITY_OPENLIT", "true")

    with scope():
        boot.ensure_observability_bootstrapped()

    assert boot._SUBSCRIBER is not None
    assert [r.name for r in boot._SUBSCRIBER.recorders] == ["logging"]


def test_traceloop_backend_value_maps_to_otel(monkeypatch) -> None:
    """usage_backend='traceloop' (e.g. from a stale OBSERVABILITY_BACKEND env
    var) is remapped to 'otel' by ObservabilityConfig's model_validator
    before _do_bootstrap ever sees it — so the otel path activates."""
    monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY_BACKEND", "traceloop")

    called = {}

    def _fake_setup(config):
        called["config"] = config

    import parrot.observability.setup as setup_mod

    monkeypatch.setattr(setup_mod, "setup_telemetry", _fake_setup)

    with scope():
        boot.ensure_observability_bootstrapped()

    assert called["config"].usage_backend == "otel"
    assert boot._SUBSCRIBER is None


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
        setup_mod,
        "shutdown_telemetry",
        lambda: calls.__setitem__("otel", calls["otel"] + 1),
    )
    import parrot.observability.bootstrap as boot_mod

    monkeypatch.setattr(
        boot_mod,
        "shutdown_usage_recording",
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
        boot_mod,
        "shutdown_usage_recording",
        lambda: usage_called.__setitem__("n", usage_called["n"] + 1),
    )

    boot.shutdown_observability()  # must not raise

    assert usage_called["n"] == 1


def test_bootstrap_failure_logs_at_error(monkeypatch, caplog) -> None:
    """A failing _do_bootstrap() is loud (ERROR) but never breaks construction.

    FEAT-725 AC4: the navigator-eventbus hook site that calls the bootstrap
    logs at DEBUG, so this record is the only signal an operator gets.
    """

    def _boom() -> None:
        raise RuntimeError("bootstrap exploded")

    monkeypatch.delenv("PARROT_EVENT_FANOUT_ENABLED", raising=False)
    monkeypatch.setattr(boot, "_do_bootstrap", _boom)
    monkeypatch.setattr(boot, "_BOOTSTRAPPED", False)

    with caplog.at_level(logging.ERROR, logger="parrot.observability.bootstrap"):
        boot.ensure_observability_bootstrapped()  # must NOT raise

    assert any(
        record.levelno == logging.ERROR and "Observability auto-boot failed" in record.getMessage()
        for record in caplog.records
    )
    assert boot._BOOTSTRAPPED is True


def _patch_failing_fanout(monkeypatch) -> list[int]:
    """Patch setup_event_fanout to raise, returning a one-slot call counter.

    The bootstrap imports setup_event_fanout lazily, INSIDE the function, so
    the patch must land on the fanout module, not on ``boot``.
    """
    from parrot.observability import fanout

    calls = [0]

    def _boom(bus=None) -> None:
        calls[0] += 1
        raise RuntimeError("bad fan-out config")

    monkeypatch.setenv("PARROT_EVENT_FANOUT_ENABLED", "true")
    monkeypatch.setattr(fanout, "setup_event_fanout", _boom)
    monkeypatch.setattr(boot, "_BOOTSTRAPPED", False)
    monkeypatch.setattr(boot, "_FANOUT_ERROR", None)
    monkeypatch.setattr(boot, "_FANOUT_ERROR_TB", None)
    return calls


def test_fanout_setup_failure_logs_error_and_raises(monkeypatch, caplog) -> None:
    """A failing setup_event_fanout() is logged at ERROR and still propagates.

    TASK-4615 / issue:bd94e0afa8e6: the raise is deliberate — a durable fan-out
    misconfiguration stays a startup error — but it no longer leaves
    ``_BOOTSTRAPPED`` False, and ``_do_bootstrap()`` still runs so the local
    observability layer is not collateral damage.
    """
    _patch_failing_fanout(monkeypatch)
    did_bootstrap = []
    monkeypatch.setattr(boot, "_do_bootstrap", lambda: did_bootstrap.append(True))

    with caplog.at_level(logging.ERROR, logger="parrot.observability.bootstrap"):
        with pytest.raises(RuntimeError, match="bad fan-out config"):
            boot.ensure_observability_bootstrapped()

    assert any(
        record.levelno == logging.ERROR and "Durable event fan-out setup failed" in record.getMessage()
        for record in caplog.records
    )
    assert boot._BOOTSTRAPPED is True
    assert did_bootstrap == [True]


def test_fanout_failure_is_cached_and_not_retried(monkeypatch, caplog) -> None:
    """TASK-4615: the setup is attempted once; later calls re-raise the cache.

    Every construction still raises (it is a startup error), but
    ``setup_event_fanout()`` runs exactly once, ``_do_bootstrap()`` is not
    re-entered, nothing is logged again, and re-raising the same exception
    object does not grow its traceback without bound.
    """
    calls = _patch_failing_fanout(monkeypatch)
    bootstrap_calls = []
    monkeypatch.setattr(boot, "_do_bootstrap", lambda: bootstrap_calls.append(True))

    with pytest.raises(RuntimeError) as first:
        boot.ensure_observability_bootstrapped()

    def _tb_length(exc) -> int:
        length, tb = 0, exc.__traceback__
        while tb is not None:
            length += 1
            tb = tb.tb_next
        return length

    first_len = _tb_length(first.value)

    caplog.clear()  # drop the first call's ERROR; only later calls matter here
    with caplog.at_level(logging.ERROR, logger="parrot.observability.bootstrap"):
        for _ in range(5):
            with pytest.raises(RuntimeError) as again:
                boot.ensure_observability_bootstrapped()
            assert again.value is first.value

    assert calls == [1], "setup_event_fanout must not be retried"
    assert bootstrap_calls == [True], "_do_bootstrap must not be re-entered"
    assert caplog.records == [], "the failure is diagnosed exactly once"
    assert _tb_length(first.value) <= first_len + 1


def test_reset_clears_cached_fanout_error(monkeypatch) -> None:
    """TASK-4615: reset_bootstrap_for_tests() drops the cached fan-out error."""
    _patch_failing_fanout(monkeypatch)
    monkeypatch.setattr(boot, "_do_bootstrap", lambda: None)

    with pytest.raises(RuntimeError):
        boot.ensure_observability_bootstrapped()
    assert boot._FANOUT_ERROR is not None

    boot.reset_bootstrap_for_tests()

    assert boot._FANOUT_ERROR is None
    assert boot._FANOUT_ERROR_TB is None
    assert boot._BOOTSTRAPPED is False

    monkeypatch.delenv("PARROT_EVENT_FANOUT_ENABLED", raising=False)
    boot.ensure_observability_bootstrapped()  # must not raise
    assert boot._BOOTSTRAPPED is True
