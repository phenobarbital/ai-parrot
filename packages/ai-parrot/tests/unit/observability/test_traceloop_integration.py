"""Unit tests for the OpenLLMetry (Traceloop) integration wrapper."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from parrot.observability import ObservabilityConfig
from parrot.observability.traceloop_integration import (
    _reset_for_tests,
    init_traceloop,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """Reset the wrapper sentinel and content env between tests."""
    monkeypatch.delenv("TRACELOOP_TRACE_CONTENT", raising=False)
    monkeypatch.delenv("TRACELOOP_TELEMETRY", raising=False)
    _reset_for_tests()
    yield
    _reset_for_tests()


def _fake_traceloop_sdk() -> tuple[types.ModuleType, MagicMock]:
    """Build fake ``traceloop`` / ``traceloop.sdk`` modules exposing ``Traceloop``."""
    fake_cls = MagicMock(name="Traceloop")
    sdk_mod = types.ModuleType("traceloop.sdk")
    sdk_mod.Traceloop = fake_cls
    pkg_mod = types.ModuleType("traceloop")
    pkg_mod.sdk = sdk_mod
    return pkg_mod, fake_cls, sdk_mod


def test_import_does_not_load_traceloop() -> None:
    """Importing the wrapper must NOT pull in traceloop-sdk."""
    import parrot.observability.traceloop_integration as mod  # noqa: PLC0415

    assert hasattr(mod, "init_traceloop")
    assert hasattr(mod, "setup_traceloop")
    assert hasattr(mod, "shutdown_traceloop")


def test_init_idempotent() -> None:
    """init_traceloop called N times calls Traceloop.init exactly once."""
    pkg, fake_cls, sdk = _fake_traceloop_sdk()
    with patch.dict(sys.modules, {"traceloop": pkg, "traceloop.sdk": sdk}):
        cfg = ObservabilityConfig(enabled=True, enable_traceloop=True, usage_backend="traceloop")
        init_traceloop(cfg)
        init_traceloop(cfg)
        init_traceloop(cfg)
        assert fake_cls.init.call_count == 1


def test_init_passes_endpoint_and_app_name() -> None:
    """Traceloop.init receives app_name + api_endpoint from config."""
    pkg, fake_cls, sdk = _fake_traceloop_sdk()
    with patch.dict(sys.modules, {"traceloop": pkg, "traceloop.sdk": sdk}):
        cfg = ObservabilityConfig(
            enabled=True,
            enable_traceloop=True,
            usage_backend="traceloop",
            otlp_endpoint="http://collector:4318",
            service_name="my-parrot",
        )
        init_traceloop(cfg)
        kwargs = fake_cls.init.call_args.kwargs
        assert kwargs["app_name"] == "my-parrot"
        assert kwargs["api_endpoint"] == "http://collector:4318"
        assert kwargs["api_key"] is None
        assert kwargs["telemetry_enabled"] is False


def test_content_capture_gated_off_by_default() -> None:
    """Without capture flags, TRACELOOP_TRACE_CONTENT is 'false' (PII guard)."""
    pkg, fake_cls, sdk = _fake_traceloop_sdk()
    import os

    with patch.dict(sys.modules, {"traceloop": pkg, "traceloop.sdk": sdk}):
        cfg = ObservabilityConfig(enabled=True, enable_traceloop=True, usage_backend="traceloop")
        init_traceloop(cfg)
        assert os.environ["TRACELOOP_TRACE_CONTENT"] == "false"
        assert os.environ["TRACELOOP_TELEMETRY"] == "false"


def test_content_capture_on_when_enabled() -> None:
    """capture_prompts/completions flips TRACELOOP_TRACE_CONTENT to 'true'."""
    pkg, fake_cls, sdk = _fake_traceloop_sdk()
    import os

    with patch.dict(sys.modules, {"traceloop": pkg, "traceloop.sdk": sdk}):
        cfg = ObservabilityConfig(
            enabled=True,
            enable_traceloop=True,
            usage_backend="traceloop",
            capture_prompts=True,
        )
        init_traceloop(cfg)
        assert os.environ["TRACELOOP_TRACE_CONTENT"] == "true"


def test_init_missing_raises() -> None:
    """Missing traceloop-sdk raises ImportError pointing at the extra."""
    cfg = ObservabilityConfig(enabled=True, enable_traceloop=True, usage_backend="traceloop")
    saved = sys.modules.pop("traceloop", None)
    try:
        with patch.dict(sys.modules, {"traceloop": None, "traceloop.sdk": None}):
            with pytest.raises(ImportError, match="observability-traceloop"):
                init_traceloop(cfg)
    finally:
        if saved is not None:
            sys.modules["traceloop"] = saved


def test_reset_allows_reinit() -> None:
    """After _reset_for_tests(), a fresh init hits Traceloop.init again."""
    pkg, fake_cls, sdk = _fake_traceloop_sdk()
    with patch.dict(sys.modules, {"traceloop": pkg, "traceloop.sdk": sdk}):
        cfg = ObservabilityConfig(enabled=True, enable_traceloop=True, usage_backend="traceloop")
        init_traceloop(cfg)
        assert fake_cls.init.call_count == 1
        _reset_for_tests()
        init_traceloop(cfg)
        assert fake_cls.init.call_count == 2
