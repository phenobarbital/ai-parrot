"""Unit tests for parrot.rerankers.factory.

Tests cover:
- Empty config returns None.
- Valid ``local_cross_encoder`` config returns a ``LocalCrossEncoderReranker``.
- Valid ``llm`` config with a fake client returns an ``LLMReranker``.
- Missing ``type`` key raises ``ConfigError``.
- Unknown ``type`` value raises ``ConfigError``.
- ``type=llm`` without a client raises ``ConfigError``.
- Importing the factory does NOT eagerly load torch/transformers.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from parrot.exceptions import ConfigError
from parrot.rerankers.factory import create_reranker


class FakeClient:
    """Stand-in for AbstractClient — no network."""

    pass


def test_empty_config_returns_none() -> None:
    """An empty config dict must return None (no reranker)."""
    assert create_reranker({}) is None


def test_local_cross_encoder_returns_instance() -> None:
    """A local_cross_encoder config must return a LocalCrossEncoderReranker."""
    pytest.importorskip("transformers")
    cfg = {
        "type": "local_cross_encoder",
        "model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "device": "cpu",
    }
    r = create_reranker(cfg)
    from parrot.rerankers.local import LocalCrossEncoderReranker

    assert isinstance(r, LocalCrossEncoderReranker)


def test_llm_reranker_reuses_bot_client() -> None:
    """type=llm with bot_llm_client must return LLMReranker with that client."""
    fake = FakeClient()
    r = create_reranker({"type": "llm"}, bot_llm_client=fake)
    from parrot.rerankers.llm import LLMReranker

    assert isinstance(r, LLMReranker)
    assert r.client is fake


def test_llm_reranker_with_client_ref_bot() -> None:
    """client_ref='bot' must use the supplied bot_llm_client."""
    fake = FakeClient()
    r = create_reranker({"type": "llm", "client_ref": "bot"}, bot_llm_client=fake)
    from parrot.rerankers.llm import LLMReranker

    assert isinstance(r, LLMReranker)
    assert r.client is fake


def test_llm_reranker_without_client_raises() -> None:
    """type=llm without any client must raise ConfigError."""
    with pytest.raises(ConfigError):
        create_reranker({"type": "llm"})


def test_missing_type_raises_config_error() -> None:
    """Config without 'type' key must raise ConfigError matching 'missing type'."""
    with pytest.raises(ConfigError, match="missing 'type'"):
        create_reranker({"model_name": "x"})


def test_unknown_type_raises_config_error() -> None:
    """Unknown type must raise ConfigError matching 'unknown reranker type'."""
    with pytest.raises(ConfigError, match="unknown reranker type"):
        create_reranker({"type": "magic"})


def test_factory_import_does_not_load_torch() -> None:
    """Importing parrot.rerankers.factory must NOT eagerly load torch or transformers."""
    # In-process check: if torch/transformers are already loaded by another
    # test, skip to avoid a false positive.
    if "torch" in sys.modules or "transformers" in sys.modules:
        pytest.skip("torch already imported by another test in this process")

    # Re-import the factory module (it should already be imported, this verifies
    # the module-level code doesn't trigger torch/transformers).
    importlib.import_module("parrot.rerankers.factory")
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_config_dict_not_mutated() -> None:
    """create_reranker must not mutate the caller's config dict."""
    original = {"type": "llm"}
    fake = FakeClient()
    _ = create_reranker(original, bot_llm_client=fake)
    # 'type' key must still be present in the original dict
    assert original == {"type": "llm"}
