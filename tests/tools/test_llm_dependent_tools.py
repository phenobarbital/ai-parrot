"""Unit tests for llm_dependent_tools metadata attribute.

FEAT-485: Tests for the new AbstractToolkit.llm_dependent_tools class attribute
which marks tools that require an LLM client for execution.
"""

import pytest
from parrot.tools.toolkit import AbstractToolkit


def test_default_empty():
    """AbstractToolkit.llm_dependent_tools defaults to empty frozenset."""
    assert AbstractToolkit.llm_dependent_tools == frozenset()


def test_scraping_tags_plan_create():
    """WebScrapingToolkit.llm_dependent_tools includes 'plan_create'."""
    pytest.importorskip("parrot_tools.scraping.toolkit")
    from parrot_tools.scraping.toolkit import WebScrapingToolkit

    assert WebScrapingToolkit.llm_dependent_tools == frozenset({"plan_create"})
    assert "scrape" not in WebScrapingToolkit.llm_dependent_tools


def test_browsing_inherits():
    """WebBrowsingToolkit inherits plan_create from WebScrapingToolkit."""
    pytest.importorskip("parrot_tools.browsing.toolkit")
    from parrot_tools.browsing.toolkit import WebBrowsingToolkit

    assert "plan_create" in WebBrowsingToolkit.llm_dependent_tools
    # Verify it's inherited (not redefined)
    assert WebBrowsingToolkit.llm_dependent_tools == frozenset({"plan_create"})
