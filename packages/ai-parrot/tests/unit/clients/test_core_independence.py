"""Core independence tests (FEAT-523, TASK-2846).

Spec §4 M2 row ``test_core_has_no_module_scope_provider_import``: with
every ``parrot.clients.<provider>`` satellite blocked in ``sys.modules``,
``parrot.conf``, ``parrot.loaders.abstract`` and ``parrot.bots.agent`` must
still import cleanly — proving core no longer imports a provider client or
enum at module scope (AC-3). This is the structural backstop for every
lazy-import fix TASK-2846 made across core call sites.
"""

from __future__ import annotations

import importlib
import sys

import pytest

#: All 15 providers per spec §2's provider → distribution map.
PROVIDERS = [
    "openai",
    "anthropic",
    "google",
    "amazon",
    "groq",
    "grok",
    "zai",
    "nvidia",
    "moonshot",
    "openrouter",
    "local",
    "vllm",
    "gemma4",
    "hf",
    "meta",
]


@pytest.fixture
def block_satellites(monkeypatch):
    """Block every provider's top-level package (and any already-imported
    submodule) so re-importing a core module can't silently succeed via a
    module that was cached in sys.modules by an earlier test."""
    for name in PROVIDERS:
        monkeypatch.setitem(sys.modules, f"parrot.clients.{name}", None)
        for mod_name in list(sys.modules):
            if mod_name.startswith(f"parrot.clients.{name}."):
                monkeypatch.delitem(sys.modules, mod_name, raising=False)


@pytest.mark.parametrize("mod", ["parrot.conf", "parrot.loaders.abstract", "parrot.bots.agent"])
def test_core_imports_without_providers(block_satellites, mod, monkeypatch):
    """Re-importing each core module must succeed with all 15 providers
    blocked — proving no module-scope `from parrot.clients.<provider> import
    ...` survived TASK-2846's hard cut."""
    monkeypatch.delitem(sys.modules, mod, raising=False)
    importlib.import_module(mod)
