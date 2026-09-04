"""TASK-2848: ``handlers/llm.py`` must resolve model catalogues via
``LLMFactory.list_models()`` — no provider enum imports, no per-provider
``if`` chain.
"""

import inspect

import parrot.handlers.llm as h


def test_no_enum_imports():
    """AC: `grep -n "Model\\b" handlers/llm.py` shows no provider enum names."""
    src = inspect.getsource(h)
    assert "parrot.models.openai" not in src
    assert "parrot.clients.claude" not in src
    assert "OpenAIModel" not in src
    assert "GroqModel" not in src
    assert "ClaudeModel" not in src
    assert "GoogleModel" not in src


def test_delegates(monkeypatch):
    """`_get_supported_models` must delegate to `LLMFactory.list_models`."""
    called = {}
    monkeypatch.setattr(
        h.LLMFactory,
        "list_models",
        staticmethod(lambda p: called.setdefault(p, {"active": ["m"], "deprecated": []})),
    )
    handler = object.__new__(h.LLMClient)
    assert handler._get_supported_models("openai")["active"] == ["m"]
    assert called == {"openai": {"active": ["m"], "deprecated": []}}


def test_azure_aliases_to_openai(monkeypatch):
    """`azure` is accepted as an alias for `openai` (pre-existing behavior)."""
    called = {}
    monkeypatch.setattr(
        h.LLMFactory,
        "list_models",
        staticmethod(lambda p: called.setdefault(p, {"active": ["m"], "deprecated": []})),
    )
    handler = object.__new__(h.LLMClient)
    handler._get_supported_models("azure")
    assert list(called) == ["openai"]


def test_missing_satellite_degrades_gracefully(monkeypatch):
    """A provider whose satellite isn't installed returns an empty list
    (via `LLMFactory.list_models`'s `ImportError`), not a raise — matches
    the pre-existing `test_llm_handler_unknown_returns_empty` shape."""

    def _boom(provider):
        raise ImportError(f"No LLM client for provider '{provider}'.")

    monkeypatch.setattr(h.LLMFactory, "list_models", staticmethod(_boom))
    # `object.__new__` bypasses `post_init` — `_get_supported_models` must
    # not depend on `self.logger` being set (uses the module-level logger).
    handler = object.__new__(h.LLMClient)
    result = handler._get_supported_models("not-a-provider")
    assert result == []


def test_models_catalogue_for_core_providers():
    """Models endpoint returns the catalogue for openai/google/anthropic/groq
    via the real (undiscovered) `LLMFactory.list_models`.

    Shape is backwards compatible (pinned by
    `test_deprecations.py::TestPartitionedListing`): openai returns the
    partitioned dict, every other provider a flat list of active models.
    """
    handler = object.__new__(h.LLMClient)

    openai_out = handler._get_supported_models("openai")
    assert set(openai_out) == {"active", "deprecated"}
    assert openai_out["active"]

    for provider in ("google", "anthropic", "groq"):
        out = handler._get_supported_models(provider)
        assert isinstance(out, list)
        assert out
