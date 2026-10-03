"""Tests for the LLM contradiction pack (TASK-4017)."""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import LintOptions
from parrot.knowledge.lint.rule import make_fingerprint
from parrot.knowledge.lint.packs.llm import ContradictionLLMRule, build_llm_rule, resolve_lint_llm_spec


class FakeClient:
    """Fake LLM client for testing."""

    def __init__(self, responses: list[dict[str, Any]] | None = None):
        self.model = "fake-model"
        self.responses = responses or [
            {"contradicts": False, "explanation": "No contradiction"},
            {"contradicts": True, "explanation": "A says X, B says not X"},
        ]
        self.call_count = 0

    async def ask(self, prompt: str, model: str, max_tokens: int, temperature: float) -> MagicMock:
        """Mock ask method."""
        self.call_count += 1
        response = MagicMock()
        response.text = json.dumps(self.responses[self.call_count - 1])
        return response


@pytest.fixture
def fake_client():
    """Create a fake LLM client."""
    return FakeClient()


@pytest.fixture
def lint_context(tmp_path):
    """Create a minimal lint context for testing."""
    from parrot.knowledge.wiki.store import BaseWikiStore

    # Create a minimal in-memory store for testing
    store = MagicMock(spec=BaseWikiStore)

    # Mock the required async methods
    async def mock_dump_pages():
        return [
            {
                "concept_id": "page1",
                "node_id": "n1",
                "title": "Page One",
                "category": "ADR",
                "summary": "First page",
                "body": "Content 1",
                "source_id": "s1",
                "token_count": 10,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "content_hash": "hash1",
            }
        ]

    async def mock_dump_edges():
        return [
            {"src": "memory1", "dst": "page1", "rel": "references"},
            {"src": "memory2", "dst": "page1", "rel": "references"},
        ]

    async def mock_list_pages(origin=None, limit=None):
        return [
            {
                "concept_id": "memory1",
                "node_id": "m1",
                "title": "Memory One",
                "category": "memory",
                "summary": "First memory",
                "body": "Memory content 1",
                "source_id": "s1",
                "token_count": 10,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "content_hash": "hash1",
            },
            {
                "concept_id": "memory2",
                "node_id": "m2",
                "title": "Memory Two",
                "category": "memory",
                "summary": "Second memory",
                "body": "Memory content 2",
                "source_id": "s1",
                "token_count": 10,
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "content_hash": "hash1",
            },
        ]

    async def mock_stats():
        return {"pages": 1, "edges": 1, "sources": 1, "embeddings": 0, "total_tokens": 10, "categories": {}}

    store.dump_pages = mock_dump_pages
    store.dump_edges = mock_dump_edges
    store.list_pages = mock_list_pages
    store.stats = mock_stats

    options = LintOptions(llm=True, llm_model="fake-model", llm_max_pairs=50)
    return LintContext(store=store, options=options)


def test_llm_pair_cap(lint_context):
    """Test that at most max_pairs pairs are checked."""
    # Create a client that will return many pairs
    client = FakeClient()
    rule = ContradictionLLMRule(client, max_pairs=2)

    # Run the check
    findings = asyncio.run(rule.check(lint_context))

    # Should have at most 2 pairs checked
    assert client.call_count <= 2


async def test_llm_skipped_on_failure(lint_context):
    """Test that client failure results in a single llm-skipped info finding."""
    # Create a client that raises an exception
    client = MagicMock()
    client.ask = AsyncMock(side_effect=Exception("Network error"))

    rule = ContradictionLLMRule(client, max_pairs=50)

    # Run the check
    findings = await rule.check(lint_context)

    # Should have exactly one llm-skipped info finding
    assert len(findings) == 1
    assert findings[0].rule_id == "llm-skipped"
    assert findings[0].severity == "info"
    assert "Network error" in findings[0].message


def _clear_llm_env(monkeypatch):
    for name in ("WIKI_LINT_LLM", "WIKI_EXTRACT_LLM", "PARROT_NO_AUTO_LLM"):
        monkeypatch.delenv(name, raising=False)


def test_resolve_spec_order(monkeypatch):
    """Explicit > WIKI_LINT_LLM > WIKI_EXTRACT_LLM > auto-detect (disabled by PARROT_NO_AUTO_LLM)."""
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("PARROT_NO_AUTO_LLM", "1")
    monkeypatch.setenv("WIKI_EXTRACT_LLM", "b:y")
    assert resolve_lint_llm_spec(None) == "b:y"
    monkeypatch.setenv("WIKI_LINT_LLM", "a:x")
    assert resolve_lint_llm_spec(None) == "a:x"
    assert resolve_lint_llm_spec("c:z") == "c:z"
    monkeypatch.delenv("WIKI_LINT_LLM")
    monkeypatch.delenv("WIKI_EXTRACT_LLM")
    assert resolve_lint_llm_spec(None) is None


def test_build_llm_rule_no_spec(monkeypatch):
    """No spec configured (auto-detect disabled) -> None."""
    _clear_llm_env(monkeypatch)
    monkeypatch.setenv("PARROT_NO_AUTO_LLM", "1")
    options = LintOptions(llm=True, llm_model=None, llm_max_pairs=50)
    assert build_llm_rule(options) is None


def test_build_llm_rule_with_spec(monkeypatch):
    """A configured spec builds a temperature-0 client through LLMFactory."""
    _clear_llm_env(monkeypatch)
    with patch("parrot.knowledge.lint.packs.llm.LLMFactory.create", return_value=FakeClient()) as create:
        rule = build_llm_rule(LintOptions(llm=True, llm_model="fake:model", llm_max_pairs=7))
    create.assert_called_once_with("fake:model", model_args={"temperature": 0.0})
    assert isinstance(rule, ContradictionLLMRule)
    assert rule.max_pairs == 7


def test_finding_fingerprint():
    """Fingerprints are deterministic and independent of subject order."""
    assert make_fingerprint("contradiction-llm", ["memory1", "memory2"]) == make_fingerprint(
        "contradiction-llm", ["memory2", "memory1"]
    )
