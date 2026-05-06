"""Unit tests for EmbeddingRegistry Matryoshka cache key.

Tests spec §3 Module 3 — the cache key extension that ensures two bots
using the same model with different truncation dims land in separate
cache slots.  No real model weights are loaded; ``_build_model`` is
stubbed via monkeypatch.
"""
import pytest
from unittest.mock import MagicMock

from parrot.embeddings.registry import EmbeddingRegistry


@pytest.fixture(autouse=True)
def fresh_registry():
    """Ensure each test starts with a clean singleton."""
    EmbeddingRegistry._instance = None
    yield
    EmbeddingRegistry._instance = None


class TestMatryoshkaCacheKey:
    """Tests that the 3-tuple cache key correctly isolates truncation dims."""

    def test_different_dims_separate_instances(self, monkeypatch):
        """Two calls with the same model but different dims return distinct objects."""
        counter = {"n": 0}

        def stub_build(self, model_name, model_type, **kwargs):
            counter["n"] += 1
            return MagicMock(name=f"model_{counter['n']}")

        monkeypatch.setattr(EmbeddingRegistry, "_build_model", stub_build)

        reg = EmbeddingRegistry.instance()
        a = reg.get_or_create_sync("nomic-ai/nomic-embed-text-v1.5", "huggingface")
        b = reg.get_or_create_sync(
            "nomic-ai/nomic-embed-text-v1.5",
            "huggingface",
            matryoshka={"enabled": True, "dimension": 512},
        )
        assert a is not b
        assert counter["n"] == 2, "Expected _build_model to be called twice"

    def test_same_dim_returns_cached(self, monkeypatch):
        """Two calls with the same model and same dim return the same object."""
        counter = {"n": 0}

        def stub_build(self, model_name, model_type, **kwargs):
            counter["n"] += 1
            return MagicMock(name=f"model_{counter['n']}")

        monkeypatch.setattr(EmbeddingRegistry, "_build_model", stub_build)

        reg = EmbeddingRegistry.instance()
        a = reg.get_or_create_sync(
            "nomic-ai/nomic-embed-text-v1.5",
            "huggingface",
            matryoshka={"enabled": True, "dimension": 512},
        )
        b = reg.get_or_create_sync(
            "nomic-ai/nomic-embed-text-v1.5",
            "huggingface",
            matryoshka={"enabled": True, "dimension": 512},
        )
        assert a is b
        assert counter["n"] == 1, "Expected _build_model to be called only once"

    def test_disabled_matryoshka_keys_to_none(self, monkeypatch):
        """enabled=False and no matryoshka both land in the same cache slot."""
        counter = {"n": 0}

        def stub_build(self, model_name, model_type, **kwargs):
            counter["n"] += 1
            return MagicMock()

        monkeypatch.setattr(EmbeddingRegistry, "_build_model", stub_build)

        reg = EmbeddingRegistry.instance()
        a = reg.get_or_create_sync("nomic-ai/nomic-embed-text-v1.5", "huggingface")
        b = reg.get_or_create_sync(
            "nomic-ai/nomic-embed-text-v1.5",
            "huggingface",
            matryoshka={"enabled": False, "dimension": 512},
        )
        # enabled=False → dim=None → same cache key as no matryoshka
        assert a is b

    def test_two_different_dims_are_separate(self, monkeypatch):
        """dim=256 and dim=512 land in separate slots."""
        counter = {"n": 0}

        def stub_build(self, model_name, model_type, **kwargs):
            counter["n"] += 1
            return MagicMock(name=f"model_{counter['n']}")

        monkeypatch.setattr(EmbeddingRegistry, "_build_model", stub_build)

        reg = EmbeddingRegistry.instance()
        a = reg.get_or_create_sync(
            "nomic-ai/nomic-embed-text-v1.5",
            "huggingface",
            matryoshka={"enabled": True, "dimension": 256},
        )
        b = reg.get_or_create_sync(
            "nomic-ai/nomic-embed-text-v1.5",
            "huggingface",
            matryoshka={"enabled": True, "dimension": 512},
        )
        assert a is not b
        assert counter["n"] == 2

    def test_loaded_models_reports_3tuple_keys(self, monkeypatch):
        """loaded_models() returns the 3-tuple keys."""
        def stub_build(self, model_name, model_type, **kwargs):
            return MagicMock()

        monkeypatch.setattr(EmbeddingRegistry, "_build_model", stub_build)

        reg = EmbeddingRegistry.instance()
        reg.get_or_create_sync(
            "nomic-ai/nomic-embed-text-v1.5",
            "huggingface",
            matryoshka={"enabled": True, "dimension": 512},
        )
        keys = reg.loaded_models()
        assert len(keys) == 1
        assert keys[0] == ("nomic-ai/nomic-embed-text-v1.5", "huggingface", 512)


class TestExtractMatryoshkaDim:
    """Tests for the private _extract_matryoshka_dim helper."""

    def test_no_matryoshka_returns_none(self):
        assert EmbeddingRegistry._extract_matryoshka_dim({}) is None

    def test_none_matryoshka_returns_none(self):
        assert EmbeddingRegistry._extract_matryoshka_dim({"matryoshka": None}) is None

    def test_disabled_returns_none(self):
        assert EmbeddingRegistry._extract_matryoshka_dim(
            {"matryoshka": {"enabled": False, "dimension": 512}}
        ) is None

    def test_enabled_returns_dim(self):
        assert EmbeddingRegistry._extract_matryoshka_dim(
            {"matryoshka": {"enabled": True, "dimension": 512}}
        ) == 512

    def test_enabled_no_dim_returns_none(self):
        # enabled=True but no dimension (would fail Pydantic validation later)
        assert EmbeddingRegistry._extract_matryoshka_dim(
            {"matryoshka": {"enabled": True}}
        ) is None
