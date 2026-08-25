"""Unit tests for the FEAT-462 bootstrap cleanup.

Verifies that `_do_bootstrap()` no longer references traceloop/openlit
integrations, that `shutdown_observability()` no longer flushes Traceloop,
and that `OBSERVABILITY_OPENLIT_RECORDER=true` wires an `OpenLitUsageRecorder`
into the recorder list.

Spec: sdd/specs/unified-telemetry-bus.spec.md §3 Module 6.
Task: TASK-2475.
"""

from __future__ import annotations

from navigator_eventbus.lifecycle.global_registry import scope
from parrot.observability import bootstrap as boot


class TestBootstrapNoTraceloop:
    def test_no_traceloop_import(self) -> None:
        """bootstrap.py no longer imports/calls setup_traceloop or
        shutdown_traceloop — any remaining mention of "traceloop" is only in
        explanatory comments/docstrings (marked "deprecated")."""
        import parrot.observability.bootstrap as mod

        with open(mod.__file__) as f:
            source = f.read()
        assert "setup_traceloop" not in source
        assert "shutdown_traceloop" not in source
        assert "traceloop_integration" not in source
        assert "traceloop" not in source.lower() or "deprecated" in source.lower()

    def test_no_openlit_init_call(self) -> None:
        """bootstrap.py source no longer calls init_openlit."""
        import parrot.observability.bootstrap as mod

        with open(mod.__file__) as f:
            source = f.read()
        assert "init_openlit" not in source

    def test_shutdown_does_not_reference_traceloop(self) -> None:
        """shutdown_observability() no longer imports shutdown_traceloop."""
        import inspect

        source = inspect.getsource(boot.shutdown_observability)
        assert "traceloop" not in source.lower()


class TestBootstrapOpenLitRecorder:
    def test_openlit_recorder_created_via_factory(self, monkeypatch) -> None:
        """OBSERVABILITY_OPENLIT_RECORDER=true + endpoint → factory yields
        an OpenLitUsageRecorder (verifies the config wiring end to end)."""
        monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
        monkeypatch.setenv("OBSERVABILITY_OPENLIT_RECORDER", "true")
        monkeypatch.setenv("OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT", "http://openlit:4318")
        from parrot.observability.config import ObservabilityConfig
        from parrot.observability.recorders.factory import (
            build_recorders_from_config,
        )

        config = ObservabilityConfig.from_env()
        recorders = build_recorders_from_config(config)
        recorder_names = [r.name for r in recorders]
        assert "openlit" in recorder_names

    def test_openlit_recorder_wired_into_bootstrap_subscriber(self, monkeypatch) -> None:
        """The lightweight bootstrap path subscribes the openlit recorder
        alongside the default logging recorder."""
        monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
        monkeypatch.setenv("OBSERVABILITY_OPENLIT_RECORDER", "true")
        monkeypatch.setenv("OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT", "http://openlit:4318")
        boot.reset_bootstrap_for_tests()
        try:
            with scope():
                boot.ensure_observability_bootstrapped()
            assert boot._SUBSCRIBER is not None
            recorder_names = [r.name for r in boot._SUBSCRIBER.recorders]
            assert "logging" in recorder_names
            assert "openlit" in recorder_names
        finally:
            boot.reset_bootstrap_for_tests()

    def test_no_recorder_when_flag_unset(self, monkeypatch) -> None:
        monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
        boot.reset_bootstrap_for_tests()
        try:
            with scope():
                boot.ensure_observability_bootstrapped()
            assert boot._SUBSCRIBER is not None
            recorder_names = [r.name for r in boot._SUBSCRIBER.recorders]
            assert recorder_names == ["logging"]
        finally:
            boot.reset_bootstrap_for_tests()


class TestBackwardCompatOtelPath:
    def test_otel_backend_still_works(self, monkeypatch) -> None:
        """OBSERVABILITY_ENABLED=true + OBSERVABILITY_BACKEND=otel still
        delegates to setup_telemetry unchanged."""
        monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
        monkeypatch.setenv("OBSERVABILITY_BACKEND", "otel")

        called = {}

        def _fake_setup(config):
            called["config"] = config

        import parrot.observability.setup as setup_mod

        monkeypatch.setattr(setup_mod, "setup_telemetry", _fake_setup)

        boot.reset_bootstrap_for_tests()
        try:
            with scope():
                boot.ensure_observability_bootstrapped()
            assert called["config"].usage_backend == "otel"
            assert boot._SUBSCRIBER is None
        finally:
            boot.reset_bootstrap_for_tests()

    def test_otel_backend_with_openlit_recorder_logs_debug_note(
        self, monkeypatch, caplog
    ) -> None:
        """OBSERVABILITY_BACKEND=otel + an openlit_recorder_endpoint logs a
        debug note explaining the recorder does not fan out on this path
        (it never silently does nothing without any trace of why)."""
        import logging

        monkeypatch.setenv("OBSERVABILITY_ENABLED", "true")
        monkeypatch.setenv("OBSERVABILITY_BACKEND", "otel")
        monkeypatch.setenv("OBSERVABILITY_OPENLIT_RECORDER", "true")
        monkeypatch.setenv(
            "OBSERVABILITY_OPENLIT_RECORDER_ENDPOINT", "http://openlit:4318"
        )

        import parrot.observability.setup as setup_mod

        monkeypatch.setattr(setup_mod, "setup_telemetry", lambda config: None)

        boot.reset_bootstrap_for_tests()
        try:
            with (
                caplog.at_level(
                    logging.DEBUG, logger="parrot.observability.bootstrap"
                ),
                scope(),
            ):
                boot.ensure_observability_bootstrapped()
            assert any(
                "openlit_recorder_endpoint" in r.message for r in caplog.records
            )
        finally:
            boot.reset_bootstrap_for_tests()
