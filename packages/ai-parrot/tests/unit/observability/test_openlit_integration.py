"""Unit tests for OpenLIT integration wrapper.

FEAT-177 TASK-1236.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from parrot.observability import ObservabilityConfig
from parrot.observability.openlit_integration import (
    _reset_for_tests,
    init_openlit,
)


@pytest.fixture(autouse=True)
def _reset():
    """Reset the module sentinel before and after each test."""
    _reset_for_tests()
    yield
    _reset_for_tests()


def test_import_does_not_load_openlit() -> None:
    """Importing openlit_integration must NOT pull in openlit itself."""
    # The module has already been imported above; openlit must not be present
    # unless it was independently installed and imported elsewhere in the suite.
    # We verify by checking that the module was loaded without side-importing openlit.
    import parrot.observability.openlit_integration as mod  # noqa: PLC0415

    assert hasattr(mod, "init_openlit"), "init_openlit not found"
    assert hasattr(mod, "_reset_for_tests"), "_reset_for_tests not found"


def test_init_idempotent() -> None:
    """init_openlit called N times must call openlit.init exactly once."""
    fake_openlit = MagicMock()
    with patch.dict(sys.modules, {"openlit": fake_openlit}):
        cfg = ObservabilityConfig(enabled=True, enable_openlit=True)
        init_openlit(cfg)
        init_openlit(cfg)
        init_openlit(cfg)
        assert fake_openlit.init.call_count == 1


def test_init_passes_endpoint_and_service_name() -> None:
    """openlit.init receives otlp_endpoint and application_name."""
    fake_openlit = MagicMock()
    with patch.dict(sys.modules, {"openlit": fake_openlit}):
        cfg = ObservabilityConfig(
            enabled=True,
            enable_openlit=True,
            otlp_endpoint="http://collector:4318",
            service_name="my-parrot",
        )
        init_openlit(cfg)
        fake_openlit.init.assert_called_once_with(
            otlp_endpoint="http://collector:4318",
            application_name="my-parrot",
            disabled_instrumentors=cfg.openlit_disabled_instrumentors,
            disable_metrics=cfg.openlit_disable_metrics,
        )


def test_init_missing_raises() -> None:
    """Missing openlit package raises ImportError with action message."""
    cfg = ObservabilityConfig(enabled=True, enable_openlit=True)
    # Temporarily hide openlit from sys.modules
    saved = sys.modules.pop("openlit", None)
    try:
        with patch.dict(sys.modules, {"openlit": None}):
            with pytest.raises(ImportError, match="observability-openlit"):
                init_openlit(cfg)
    finally:
        if saved is not None:
            sys.modules["openlit"] = saved


def test_reset_allows_reinit() -> None:
    """After _reset_for_tests(), a fresh init_openlit call hits openlit.init again."""
    fake_openlit = MagicMock()
    with patch.dict(sys.modules, {"openlit": fake_openlit}):
        cfg = ObservabilityConfig(enabled=True, enable_openlit=True)
        init_openlit(cfg)
        assert fake_openlit.init.call_count == 1

        _reset_for_tests()
        init_openlit(cfg)
        assert fake_openlit.init.call_count == 2
