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
    # Save originals so we can restore them after the test — purging
    # without restoring replaces module objects and breaks isinstance /
    # patch() for every later test that imported names at collection time.
    saved = {
        k: v
        for k, v in sys.modules.items()
        if k.startswith("parrot.flows.dev_loop")
        or k.startswith("claude_agent_sdk")
    }

    for mod in saved:
        del sys.modules[mod]

    try:
        pre_existing = set(sys.modules)

        importlib.import_module("parrot.flows.dev_loop")

        assert "claude_agent_sdk" not in sys.modules, (
            "Importing parrot.flows.dev_loop must not trigger "
            "claude_agent_sdk import (spec §7 R1)."
        )

        new_mods = set(sys.modules) - pre_existing
        sdk_consumers = [m for m in new_mods if "claude_agent_sdk" in m]
        assert not sdk_consumers, (
            f"Unexpected SDK module(s) loaded during "
            f"parrot.flows.dev_loop import: {sdk_consumers}"
        )
    finally:
        # Remove the freshly-created modules and put the originals back.
        for mod in list(sys.modules):
            if mod.startswith("parrot.flows.dev_loop") or mod.startswith(
                "claude_agent_sdk"
            ):
                del sys.modules[mod]
        sys.modules.update(saved)


def test_models_module_is_pure():
    """The models module must not even reference parrot.* clients."""
    saved = {
        k: v
        for k, v in sys.modules.items()
        if k.startswith("parrot.flows.dev_loop.models")
    }

    for mod in saved:
        del sys.modules[mod]

    try:
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
    finally:
        for mod in list(sys.modules):
            if mod.startswith("parrot.flows.dev_loop.models"):
                del sys.modules[mod]
        sys.modules.update(saved)
