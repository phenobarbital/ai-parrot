"""Regression guard for the observability bootstrap hook (FEAT-725).

Commit ``b1388892f`` (TASK-1828) silently disarmed ai-parrot's env-driven
observability auto-boot by deleting the ``EventEmitterMixin`` that called it,
and nothing noticed for three months. These tests fail if the hook is ever
uninstalled again.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from navigator_eventbus.lifecycle import mixin as nav_mixin

from parrot.core.events import lifecycle


@pytest.fixture(autouse=True)
def _restore_hook():
    """Save and restore the process-wide hook around each test.

    A leaked stub would make every later-constructed bot/client/tool in this
    session boot against a fake, so restoration is mandatory, not tidiness.
    """
    previous = nav_mixin._bootstrap_hook
    yield
    nav_mixin.set_bootstrap_hook(previous)


def test_bootstrap_hook_is_installed() -> None:
    """Importing parrot.core.events.lifecycle arms the navigator-eventbus hook."""
    assert nav_mixin._bootstrap_hook is not None
    assert nav_mixin._bootstrap_hook is lifecycle._observability_bootstrap_hook


def test_hook_calls_ensure_observability_bootstrapped(monkeypatch) -> None:
    """The hook delegates to the bootstrap, once per invocation."""
    from parrot.observability import bootstrap as boot

    calls: list[int] = []
    # The hook does `from parrot.observability.bootstrap import ...` at CALL
    # time, so patching the attribute on the module object is what it sees.
    monkeypatch.setattr(
        boot, "ensure_observability_bootstrapped", lambda: calls.append(1)
    )

    lifecycle._observability_bootstrap_hook()

    assert len(calls) == 1


def test_init_events_triggers_bootstrap(monkeypatch) -> None:
    """EventEmitterMixin._init_events() reaches the bootstrap end to end.

    This is the exact chain that regressed; assert the wiring, not a mock of it.
    """
    from parrot.observability import bootstrap as boot

    calls: list[int] = []
    monkeypatch.setattr(
        boot, "ensure_observability_bootstrapped", lambda: calls.append(1)
    )

    class _Host(lifecycle.EventEmitterMixin):
        """Throwaway host standing in for a bot/client/tool."""

    host = _Host()
    host._init_events(forward_to_global=False)

    assert calls, "EventEmitterMixin._init_events() did not reach the bootstrap"


def test_hook_import_is_deferred() -> None:
    """parrot.core.events.lifecycle imports without dragging in parrot.observability.

    Guards the circular-import deferral (AC7) in a FRESH interpreter — an
    in-process check is worthless because the test session has already
    imported both packages.
    """
    code = (
        "import sys; import parrot.core.events.lifecycle; "
        "sys.exit(1 if 'parrot.observability' in sys.modules else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
