"""Lazy-import guarantee for parrot.flows.dev_loop (TASK-888).

Spec §7 R1 requires that ``import parrot.flows.dev_loop`` does NOT
pull in ``claude_agent_sdk``. The SDK is only used inside dispatcher
methods that are invoked at run-time, behind a try/except ImportError
guard. This test asserts the invariant — and asserts the *transitive*
invariant too: no module that itself imports the SDK at module scope
sneaks into the dependency graph.
"""

from __future__ import annotations

import importlib
import sys


def test_import_does_not_pull_in_claude_agent_sdk():
    """``import parrot.flows.dev_loop`` MUST NOT load claude_agent_sdk."""
    # Drop any cached state for the dev-loop package and the SDK so we
    # measure a fresh import cycle.
    for mod in list(sys.modules):
        if mod.startswith("parrot.flows.dev_loop") or mod.startswith(
            "claude_agent_sdk"
        ):
            del sys.modules[mod]

    # Capture the snapshot AFTER purging dev-loop state so we can detect
    # any *new* module that is loaded by the import.
    pre_existing = set(sys.modules)

    importlib.import_module("parrot.flows.dev_loop")

    assert "claude_agent_sdk" not in sys.modules, (
        "Importing parrot.flows.dev_loop must not trigger "
        "claude_agent_sdk import (spec §7 R1)."
    )

    # Defence-in-depth: list any newly-loaded module whose name contains
    # 'claude_agent_sdk'. Importing the dispatcher is fine because it
    # does not eagerly import the SDK; but if a new file ever does
    # ``from claude_agent_sdk import ...`` at module scope this
    # assertion catches it before review.
    new_mods = set(sys.modules) - pre_existing
    sdk_consumers = [m for m in new_mods if "claude_agent_sdk" in m]
    assert not sdk_consumers, (
        f"Unexpected SDK module(s) loaded during "
        f"parrot.flows.dev_loop import: {sdk_consumers}"
    )


def test_models_module_is_pure():
    """The models module must not even reference parrot.* clients."""
    for mod in list(sys.modules):
        if mod.startswith("parrot.flows.dev_loop.models"):
            del sys.modules[mod]
    pre_existing = set(sys.modules)
    importlib.import_module("parrot.flows.dev_loop.models")
    # No SDK side-effects.
    assert "claude_agent_sdk" not in sys.modules
    # And no NEW heavy parrot subpackage either — models.py must depend
    # only on pydantic + typing. We check newly-loaded modules to avoid
    # false positives from the test session's broader history.
    new_mods = set(sys.modules) - pre_existing
    heavy = [
        m
        for m in new_mods
        if m.startswith("parrot.clients")
        or m.startswith("parrot.bots")
        or m.startswith("parrot.autonomous")
    ]
    assert not heavy, (
        f"parrot.flows.dev_loop.models pulled in heavy parrot subpackages: "
        f"{heavy}"
    )
