"""TASK-2855: end-to-end proof every documented `parrot.clients.<provider>`
import path resolves and every class in its `__all__` is importable.

Requires all 15 satellites installed (`uv sync --all-packages` or
`pip install ai-parrot[llms]`) — this is an *integration* test, not a
core-independence test (see `packages/ai-parrot/tests/unit/clients/
test_core_independence.py` for the "core imports without any provider"
guarantee).
"""
import importlib

import pytest

# Codebase Contract (TASK-2855) — the 15 providers this feature extracted.
PROVIDERS = [
    "openai", "anthropic", "google", "amazon", "groq", "grok", "zai",
    "nvidia", "moonshot", "openrouter", "local", "vllm", "gemma4", "hf",
    "meta",
]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_package_imports(provider: str) -> None:
    """`import parrot.clients.<provider>` resolves for every provider."""
    importlib.import_module(f"parrot.clients.{provider}")


@pytest.mark.parametrize("provider", PROVIDERS)
def test_every_all_entry_imports(provider: str) -> None:
    """Every name in the provider package's `__all__` is importable and
    resolves to a real attribute (not a stale re-export)."""
    pkg = importlib.import_module(f"parrot.clients.{provider}")
    all_names = getattr(pkg, "__all__", None)
    assert all_names, f"parrot.clients.{provider} declares no __all__"
    for name in all_names:
        assert hasattr(pkg, name), f"parrot.clients.{provider}.__all__ names missing attr '{name}'"
