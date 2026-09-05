"""Shared fixtures for the bookstore test suite.

The fake LLM adapter mirrors the one used by the pageindex toolkit
tests (``tests/knowledge/pageindex/test_toolkit.py``): a ``MagicMock``
whose ``ask``/``ask_structured`` are ``AsyncMock``s, plus the tiktoken
stub so ingestion works offline.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.bookstore.models import CardDraft
from parrot.knowledge.pageindex.ingest import IngestedMarkdown

SAMPLE_MARKDOWN = (
    "# Synthetic Handbook\n\n"
    "Top level introduction to the synthetic handbook with enough "
    "text to clear the thinning threshold of the markdown parser.\n\n"
    "## Chapter One\n"
    "Chapter one covers asynchronous programming patterns in Python "
    "with plenty of descriptive content to keep the node visible.\n\n"
    "## Chapter Two\n"
    "Chapter two covers vector search and retrieval augmented "
    "generation with the remaining descriptive example content.\n"
)


def make_adapter() -> MagicMock:
    """Fake heavy adapter compatible with PageIndexToolkit + carding."""
    adapter = MagicMock()
    adapter.model = "heavy"
    client_response = MagicMock()
    client_response.output = "cot analysis"
    client_response.structured_output = None
    adapter.client = MagicMock()
    adapter.client.ask = AsyncMock(return_value=client_response)
    adapter.client.default_model = "test-model"
    adapter.ask = AsyncMock(return_value="cot analysis")

    def _structured(prompt, schema, **kwargs):
        if schema is CardDraft:
            return CardDraft(
                title="Synthetic Handbook",
                authors=["Ada Example"],
                year=2024,
                language="en",
                topics=["async python", "vector search"],
                summary="A synthetic handbook used by the tests.",
            )
        return IngestedMarkdown(
            title="Synthetic Handbook",
            summary="A short summary.",
            markdown=SAMPLE_MARKDOWN,
        )

    adapter.ask_structured = AsyncMock(side_effect=_structured)
    return adapter


@pytest.fixture
def fake_adapter() -> MagicMock:
    return make_adapter()


@pytest.fixture(autouse=True)
def _stub_tiktoken(monkeypatch):
    # tiktoken downloads encodings on first use; offline environments
    # bypass it with a char-count approximation (same as pageindex tests).
    def _approx(text: str, model: str = "gpt-4o") -> int:
        return max(1, len(text or ""))

    monkeypatch.setattr(
        "parrot.knowledge.pageindex.utils.count_tokens", _approx
    )
    monkeypatch.setattr(
        "parrot.knowledge.pageindex.md_builder.count_tokens", _approx
    )


@pytest.fixture
def sample_tree() -> dict:
    """Hand-built PageIndex tree dict with two levels and page ranges."""
    return {
        "doc_name": "Synthetic Handbook",
        "doc_description": "A synthetic handbook about async Python.",
        "structure": [
            {
                "title": "Chapter One",
                "node_id": "0000",
                "start_index": 1,
                "end_index": 20,
                "summary": "Async patterns.",
                "nodes": [
                    {
                        "title": "Event Loops",
                        "node_id": "0001",
                        "start_index": 3,
                        "end_index": 10,
                        "summary": "Loop internals.",
                        "nodes": [
                            {
                                "title": "Too Deep",
                                "node_id": "0002",
                                "start_index": 4,
                                "end_index": 6,
                            }
                        ],
                    }
                ],
            },
            {
                "title": "Chapter Two",
                "node_id": "0003",
                "start_index": 21,
                "end_index": 40,
                "summary": "Vector search.",
                "nodes": [],
            },
        ],
    }
