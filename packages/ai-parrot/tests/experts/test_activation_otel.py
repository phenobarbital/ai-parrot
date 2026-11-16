"""OpenTelemetry attribution tests for expert activation."""

from __future__ import annotations

import builtins
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from parrot.experts.activation import activate_expert
from parrot.experts.models import ExpertTier


def _expert() -> SimpleNamespace:
    """Build the manifest shape required by ``activate_expert``."""
    manifest = SimpleNamespace(name="sample-expert", tier=ExpertTier.JUDGMENT)
    return SimpleNamespace(bundle=SimpleNamespace(manifest=manifest))


def _install_trace(monkeypatch: pytest.MonkeyPatch, span: MagicMock) -> None:
    """Install a minimal fake OpenTelemetry module returning ``span``."""
    module = ModuleType("opentelemetry")
    module.trace = SimpleNamespace(get_current_span=MagicMock(return_value=span))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "opentelemetry", module)


@pytest.mark.asyncio
async def test_activate_expert_sets_span_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A recording span receives every expert attribution attribute."""
    span = MagicMock()
    span.is_recording.return_value = True
    _install_trace(monkeypatch, span)

    expert = _expert()
    async with activate_expert(expert, run_id="run-1", stage="review", mode="pipeline") as active:
        assert active is expert

    assert span.set_attribute.call_args_list == [
        call("expert.slug", "sample-expert"),
        call("expert.tier", "judgment"),
        call("expert.stage", "review"),
        call("expert.mode", "pipeline"),
    ]


@pytest.mark.asyncio
async def test_activate_expert_skips_none_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown stage and mode values are not attached to the span."""
    span = MagicMock()
    span.is_recording.return_value = True
    _install_trace(monkeypatch, span)

    async with activate_expert(_expert(), run_id=None, stage=None):
        pass

    assert span.set_attribute.call_args_list == [
        call("expert.slug", "sample-expert"),
        call("expert.tier", "judgment"),
    ]


@pytest.mark.asyncio
async def test_activate_expert_without_opentelemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Activation remains usable when the optional OpenTelemetry API is absent."""
    original_import = builtins.__import__

    def _import_without_opentelemetry(name: str, *args: object, **kwargs: object) -> object:
        if name == "opentelemetry":
            raise ImportError("opentelemetry is not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_without_opentelemetry)

    expert = _expert()
    async with activate_expert(expert, run_id="run-1", stage="review", mode="inline") as active:
        assert active is expert


@pytest.mark.asyncio
async def test_activate_expert_ignores_non_recording_span(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-recording current span remains untouched."""
    span = MagicMock()
    span.is_recording.return_value = False
    _install_trace(monkeypatch, span)

    async with activate_expert(_expert(), run_id="run-1", stage="review", mode="inline"):
        pass

    span.set_attribute.assert_not_called()
