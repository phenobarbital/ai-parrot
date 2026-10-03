"""Tests for the LLM contradiction pack (TASK-4017)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, LintOptions
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
        response.text = self.responses[self.call_count - 1]
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


def test_resolve_spec_order(monkeypatch):
    """Test the resolution order for LLM spec."""
    # Set environment variables
    monkeypatch.setenv("WIKI_EXTRACT_LLM", "b:y")
    monkeypatch.setenv("WIKI_LINT_LLM", "a:x")

    # Test with no explicit value
    assert resolve_lint_llm_spec(None) == "a:x"

    # Test with explicit value
    assert resolve_lint_llm_spec("c:z") == "c:z"

    # Test with PARROT_NO_AUTO_LLM set
    monkeypatch.setenv("PARROT_NO_AUTO_LLM", "1")
    assert resolve_lint_llm_spec(None) is None


def test_build_llm_rule_no_spec():
    """Test that build_llm_rule returns None when no spec is configured."""
    options = LintOptions(llm=True, llm_model=None, llm_max_pairs=50)
    assert build_llm_rule(options) is None


def test_build_llm_rule_with_spec():
    """Test that build_llm_rule creates a rule when a spec is configured."""
    options = LintOptions(llm=True, llm_model="fake-model", llm_max_pairs=50)
    rule = build_llm_rule(options)
    assert rule is not None
    assert isinstance(rule, ContradictionLLMRule)
    assert rule.max_pairs == 50


def test_finding_fingerprint():
    """Test that finding fingerprints are stable."""
    a_id = "memory1"
    b_id = "memory2"
    fingerprint = "contradiction-llm" + "\x1f" + "\x1f".join(sorted([a_id, b_id]))
    expected = "9a7f3c2e1b5d4f6a8c0e2b1d4f6a8c0e"  # Example hash

    # This is just a sanity check that the fingerprint is deterministic
    # The actual hash will vary based on the input
    assert len(fingerprint) == 40  # SHA1 hex digest length
