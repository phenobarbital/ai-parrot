"""Shared test isolation for the observability suite.

These tests configure *process-global* state on two layers:

1. **AI-Parrot's own module globals** in ``parrot.observability.setup``
   (``_TRACER_PROVIDER`` / ``_METER_PROVIDER`` / ``_STATE`` /
   ``_SUBSCRIPTION_IDS``) and the ``openlit_integration._INITIALIZED``
   sentinel.
2. **The OpenTelemetry API globals.** ``setup_telemetry()`` calls
   ``otel_trace.set_tracer_provider()`` / ``otel_metrics.set_meter_provider()``,
   each guarded by a one-shot ``Once`` latch
   (``trace._TRACER_PROVIDER_SET_ONCE`` /
   ``metrics._internal._METER_PROVIDER_SET_ONCE``). Once set in a process,
   every later ``set_*_provider()`` is silently ignored — so without a reset
   the FIRST setup test "wins" the global provider and later tests read a
   stale ``Resource`` (e.g. ``test_service_instance_id_override`` would assert
   against the previous test's provider).

``shutdown_telemetry()`` clears layer 1 but cannot un-arm the ``Once`` latches
in layer 2. This autouse fixture resets BOTH layers before and after every
test in the package, so the suite is order-independent.

The layer-2 reset pokes at private OpenTelemetry attributes. We assert their
presence up front so a future OTel rename fails loudly here (one obvious
location) instead of silently re-polluting global state.
"""
from __future__ import annotations

import pytest


def _reset_otel_api_globals() -> None:
    """Re-arm the OpenTelemetry API provider latches.

    Uses private OTel symbols by necessity (``opentelemetry-test-utils``, which
    ships an official ``reset_*_globals()``, is not a dependency). Each access
    is asserted so an OTel upgrade that renames these surfaces immediately.
    """
    from opentelemetry import trace  # noqa: PLC0415
    from opentelemetry.metrics import _internal as metrics_internal  # noqa: PLC0415
    from opentelemetry.util._once import Once  # noqa: PLC0415

    for mod, attr in (
        (trace, "_TRACER_PROVIDER"),
        (trace, "_TRACER_PROVIDER_SET_ONCE"),
        (metrics_internal, "_METER_PROVIDER"),
        (metrics_internal, "_METER_PROVIDER_SET_ONCE"),
    ):
        assert hasattr(mod, attr), (
            f"OpenTelemetry global {mod.__name__}.{attr} is missing; the "
            "observability test-isolation reset needs updating for this "
            "OTel version."
        )

    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    metrics_internal._METER_PROVIDER = None
    metrics_internal._METER_PROVIDER_SET_ONCE = Once()


def _reset_parrot_globals() -> None:
    """Tear down AI-Parrot's own telemetry module state."""
    import parrot.observability.setup as setup_mod  # noqa: PLC0415

    try:
        setup_mod.shutdown_telemetry()
    except Exception:  # noqa: BLE001 — best-effort teardown
        pass
    setup_mod._STATE.clear()
    setup_mod._TRACER_PROVIDER = None
    setup_mod._METER_PROVIDER = None
    setup_mod._SUBSCRIPTION_IDS.clear()

    try:
        from parrot.observability.openlit_integration import (  # noqa: PLC0415
            _reset_for_tests,
        )

        _reset_for_tests()
    except Exception:  # noqa: BLE001 — openlit is an optional extra
        pass


@pytest.fixture(autouse=True)
def _isolate_observability_globals():
    """Reset all telemetry globals around every observability test."""
    _reset_parrot_globals()
    _reset_otel_api_globals()
    yield
    _reset_parrot_globals()
    _reset_otel_api_globals()


# Observability env keys the config/bootstrap tests assume are unset unless a
# test explicitly sets them. Cleared from ``os.environ`` by the hermetic
# fixture below.
_OBSERVABILITY_ENV_EXTRA = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "PARROT_PRICING_PATH",
)


@pytest.fixture(autouse=True)
def _hermetic_observability_env(monkeypatch):
    """Make ``ObservabilityConfig.from_env()`` honour only test-set env vars.

    On import, ``navconfig`` loads the repo's ``env/.env`` BOTH into
    ``os.environ`` AND into its own cache — and that file sets
    ``OBSERVABILITY_ENABLED=true`` / ``OBSERVABILITY_BACKEND=otel`` for local
    development. So env-driven tests (``test_bootstrap``, ``test_config_from_env``)
    silently pick up the local ``.env`` and behave non-deterministically
    depending on the developer's machine. Neutralising it needs two moves,
    because the pollution lives in two places:

    1. Pin ``_env_getter`` to the navconfig-free ``os.environ.get`` fallback so
       reads bypass navconfig's *cache* (which ``monkeypatch.delenv`` can't
       touch). This is the same fallback ``_env_getter`` uses when navconfig is
       absent (e.g. in CI), so production behaviour is unchanged.
    2. Delete the observability keys from ``os.environ`` so that fallback sees a
       clean environment.

    A test that wants a value sets it via ``monkeypatch.setenv`` after this
    fixture has run; that lands in ``os.environ`` and is read back by the
    pinned getter.
    """
    import os  # noqa: PLC0415

    import parrot.observability.config as config_mod  # noqa: PLC0415

    monkeypatch.setattr(config_mod, "_env_getter", lambda: os.environ.get)
    for key in [k for k in os.environ if k.startswith("OBSERVABILITY")]:
        monkeypatch.delenv(key, raising=False)
    for key in _OBSERVABILITY_ENV_EXTRA:
        monkeypatch.delenv(key, raising=False)
    yield
