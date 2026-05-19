"""Unit tests for setup_telemetry() and shutdown_telemetry().

FEAT-177 TASK-1235.
"""

from __future__ import annotations

import os
import socket
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from parrot.observability import (
    ObservabilityConfig,
    setup_telemetry,
    shutdown_telemetry,
)
from parrot.observability.errors import ConfigurationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _isolated():
    """Reset setup module state before and after each test."""
    import parrot.observability.setup as setup_mod  # noqa: PLC0415

    # Clear state before
    setup_mod._STATE.clear()
    setup_mod._TRACER_PROVIDER = None
    setup_mod._METER_PROVIDER = None
    setup_mod._SUBSCRIPTION_IDS.clear()

    # Also reset OpenLIT sentinel to avoid cross-test pollution
    try:
        from parrot.observability.openlit_integration import _reset_for_tests  # noqa: PLC0415
        _reset_for_tests()
    except Exception:  # noqa: BLE001
        pass

    try:
        yield
    finally:
        # Cleanup
        try:
            shutdown_telemetry()
        except Exception:  # noqa: BLE001
            pass
        setup_mod._STATE.clear()
        setup_mod._TRACER_PROVIDER = None
        setup_mod._METER_PROVIDER = None
        setup_mod._SUBSCRIPTION_IDS.clear()
        try:
            from parrot.observability.openlit_integration import _reset_for_tests  # noqa: PLC0415
            _reset_for_tests()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_disabled_returns_none() -> None:
    """setup_telemetry(enabled=False) returns None immediately."""
    with _isolated():
        before_modules = set(sys.modules)
        result = setup_telemetry(ObservabilityConfig(enabled=False))
        assert result is None
        new_mods = set(sys.modules) - before_modules
        # No opentelemetry.sdk modules should have been imported
        sdk_mods = [m for m in new_mods if m.startswith("opentelemetry.sdk")]
        assert not sdk_mods, f"Unexpected SDK imports: {sdk_mods}"


def test_disabled_no_global_registry_interaction() -> None:
    """setup_telemetry(enabled=False) does not register any subscribers."""
    with _isolated():
        from parrot.core.events.lifecycle.global_registry import get_global_registry  # noqa: PLC0415

        registry = get_global_registry()
        before_count = len(registry._subscriptions)
        setup_telemetry(ObservabilityConfig(enabled=False))
        after_count = len(registry._subscriptions)
        assert before_count == after_count


def test_idempotent_same_config() -> None:
    """Two calls with identical config return the same provider object."""
    with _isolated():
        cfg = ObservabilityConfig(
            enabled=True,
            enable_openlit=False,
            enable_cost_tracking=False,
        )
        p1 = setup_telemetry(cfg)
        p2 = setup_telemetry(cfg)
        assert p1 is p2
        assert p1 is not None


def test_conflicting_config_raises() -> None:
    """Second call with different config raises ConfigurationError."""
    with _isolated():
        setup_telemetry(
            ObservabilityConfig(enabled=True, service_name="a", enable_cost_tracking=False)
        )
        with pytest.raises(ConfigurationError, match="already been configured"):
            setup_telemetry(
                ObservabilityConfig(enabled=True, service_name="b", enable_cost_tracking=False)
            )


def test_service_instance_id_default() -> None:
    """Resource has service.instance.id == '{hostname}-{pid}' when not overridden."""
    with _isolated():
        cfg = ObservabilityConfig(
            enabled=True,
            service_instance_id=None,
            enable_cost_tracking=False,
            enable_openlit=False,
        )
        setup_telemetry(cfg)
        from opentelemetry import trace  # noqa: PLC0415

        resource = trace.get_tracer_provider().resource  # type: ignore[union-attr]
        expected = f"{socket.gethostname()}-{os.getpid()}"
        assert resource.attributes.get("service.instance.id") == expected


def test_service_instance_id_override() -> None:
    """Explicit service_instance_id is forwarded to the Resource."""
    with _isolated():
        cfg = ObservabilityConfig(
            enabled=True,
            service_instance_id="custom-instance-001",
            enable_cost_tracking=False,
            enable_openlit=False,
        )
        setup_telemetry(cfg)
        from opentelemetry import trace  # noqa: PLC0415

        resource = trace.get_tracer_provider().resource  # type: ignore[union-attr]
        assert resource.attributes.get("service.instance.id") == "custom-instance-001"


def test_openlit_not_imported_when_disabled() -> None:
    """When enable_openlit=False, openlit is never imported."""
    saved = sys.modules.pop("openlit", None)
    try:
        with _isolated():
            cfg = ObservabilityConfig(
                enabled=True,
                enable_openlit=False,
                enable_cost_tracking=False,
            )
            setup_telemetry(cfg)
            assert "openlit" not in sys.modules
    finally:
        if saved is not None:
            sys.modules["openlit"] = saved


def test_openlit_called_when_enabled() -> None:
    """When enable_openlit=True, openlit.init is invoked exactly once."""
    fake_openlit = MagicMock()
    with _isolated():
        with patch.dict(sys.modules, {"openlit": fake_openlit}):
            cfg = ObservabilityConfig(
                enabled=True,
                enable_openlit=True,
                enable_cost_tracking=False,
            )
            setup_telemetry(cfg)
            assert fake_openlit.init.call_count == 1


def test_shutdown_clears_state() -> None:
    """shutdown_telemetry() empties _STATE and resets provider references."""
    import parrot.observability.setup as setup_mod  # noqa: PLC0415

    with _isolated():
        cfg = ObservabilityConfig(
            enabled=True,
            enable_cost_tracking=False,
            enable_openlit=False,
        )
        setup_telemetry(cfg)
        assert len(setup_mod._STATE) == 1

        shutdown_telemetry()
        assert len(setup_mod._STATE) == 0
        assert setup_mod._TRACER_PROVIDER is None
        assert setup_mod._METER_PROVIDER is None


def test_shutdown_idempotent() -> None:
    """Calling shutdown_telemetry() twice does not raise."""
    with _isolated():
        cfg = ObservabilityConfig(
            enabled=True,
            enable_cost_tracking=False,
            enable_openlit=False,
        )
        setup_telemetry(cfg)
        shutdown_telemetry()
        shutdown_telemetry()  # must not raise


def test_shutdown_before_setup_is_no_op() -> None:
    """shutdown_telemetry() when nothing was set up is a no-op."""
    with _isolated():
        shutdown_telemetry()  # must not raise


def test_setup_forbids_simple_span_processor() -> None:
    """setup_telemetry raises ConfigurationError when a SimpleSpanProcessor
    is found in the TracerProvider's active span processor chain.

    The guard accesses the private OTel SDK attribute
    ``SynchronousMultiSpanProcessor._span_processors`` (intentional, version-pinned
    to opentelemetry-sdk<2.0). This test exercises that exact path by monkey-patching
    the real TracerProvider so that _active_span_processor._span_processors is a
    list containing a SimpleSpanProcessor after construction.
    """
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: PLC0415
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: PLC0415
        InMemorySpanExporter,
    )

    with _isolated():
        cfg = ObservabilityConfig(
            enabled=True,
            enable_cost_tracking=False,
            enable_openlit=False,
        )

        fake_simple = SimpleSpanProcessor(InMemorySpanExporter())
        original_init = TracerProvider.__init__

        def _patched_init(self, *args, **kwargs):
            """Wrap real __init__, then replace _span_processors with a list
            that includes a SimpleSpanProcessor so the guard fires."""
            original_init(self, *args, **kwargs)
            # _span_processors is a tuple on the SynchronousMultiSpanProcessor;
            # reassign it as a list that contains the fake SimpleSpanProcessor.
            self._active_span_processor._span_processors = [fake_simple]

        with patch.object(TracerProvider, "__init__", _patched_init):
            with pytest.raises(ConfigurationError, match="SimpleSpanProcessor"):
                setup_telemetry(cfg)
