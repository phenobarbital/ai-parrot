import logging
from unittest.mock import patch

import pytest

from parrot.knowledge.bookstore import _llm


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("PARROT_BOOKSTORE_LLM", raising=False)
    monkeypatch.delenv("PARROT_BOOKSTORE_LLM_LIGHT", raising=False)
    monkeypatch.delenv("PARROT_NO_AUTO_LLM", raising=False)


def test_uses_detection_when_unset(monkeypatch):
    with patch(
        "parrot.clients.detection.detect_coding_agent_llm",
        return_value="claude-code:claude-haiku-4-5-20251001",
    ):
        with (
            patch("parrot.clients.factory.LLMFactory.create") as mock_create,
            patch(
                "parrot.clients.factory.LLMFactory.parse_llm_string",
                return_value=("claude-code", "claude-haiku-4-5-20251001"),
            ),
        ):
            adapter, light, client = _llm.resolve_adapter()
    assert adapter is not None


def test_respects_opt_out(monkeypatch, caplog):
    monkeypatch.setenv("PARROT_NO_AUTO_LLM", "1")
    with patch("parrot.clients.detection.detect_coding_agent_llm") as mock_detect:
        adapter, light, client = _llm.resolve_adapter()
    mock_detect.assert_not_called()
    assert (adapter, light, client) == (None, None, None)


def test_explicit_config_wins(monkeypatch):
    monkeypatch.setenv("PARROT_BOOKSTORE_LLM", "anthropic:claude-sonnet-5")
    with patch("parrot.clients.detection.detect_coding_agent_llm") as mock_detect:
        with (
            patch("parrot.clients.factory.LLMFactory.create"),
            patch("parrot.clients.factory.LLMFactory.parse_llm_string", return_value=("anthropic", "claude-sonnet-5")),
        ):
            _llm.resolve_adapter()
    mock_detect.assert_not_called()


def test_degrades_when_detection_misses(monkeypatch, caplog):
    caplog.set_level(logging.WARNING)
    with patch("parrot.clients.detection.detect_coding_agent_llm", return_value=None):
        adapter, light, client = _llm.resolve_adapter()
    assert (adapter, light, client) == (None, None, None)
    assert "bookstore runs BM25/catalog only" in caplog.text


def test_degrades_when_detection_itself_raises(monkeypatch, caplog):
    """Code-review fix: detection failures (entry-point discovery blowing
    up, shutil.which raising, etc.) must never escape resolve_adapter() —
    spec §7 requires graceful degradation on any detection/resolution
    failure, matching the existing except-Exception pattern."""
    caplog.set_level(logging.WARNING)
    with patch(
        "parrot.clients.detection.detect_coding_agent_llm",
        side_effect=RuntimeError("boom"),
    ):
        adapter, light, client = _llm.resolve_adapter()
    assert (adapter, light, client) == (None, None, None)
