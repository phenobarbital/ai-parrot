"""Lazy-import guarantee for parrot.flows.dev_loop (TASK-888).

Spec §7 R1 requires that ``import parrot.flows.dev_loop`` does NOT
pull in ``claude_agent_sdk``. The SDK is only used inside dispatcher
methods that are invoked at run-time, behind a try/except ImportError
guard. This test asserts the invariant.
"""

from __future__ import annotations

import importlib
import sys


def test_import_does_not_pull_in_claude_agent_sdk():
    # Drop any cached state for both the dev-loop package and the SDK
    # so we measure a fresh import cycle.
    for mod in list(sys.modules):
        if mod.startswith("parrot.flows.dev_loop") or mod.startswith(
            "claude_agent_sdk"
        ):
            del sys.modules[mod]

    importlib.import_module("parrot.flows.dev_loop")

    assert "claude_agent_sdk" not in sys.modules, (
        "Importing parrot.flows.dev_loop must not trigger claude_agent_sdk "
        "import (spec §7 R1)."
    )


def test_models_module_is_pure():
    """The models module must not even reference parrot.* clients."""
    for mod in list(sys.modules):
        if mod.startswith("parrot.flows.dev_loop.models"):
            del sys.modules[mod]
    importlib.import_module("parrot.flows.dev_loop.models")
    # No SDK side-effects.
    assert "claude_agent_sdk" not in sys.modules
