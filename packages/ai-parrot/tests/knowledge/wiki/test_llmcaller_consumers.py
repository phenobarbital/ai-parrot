"""Wiki triage/inbox depend on LLMCaller, not the PageIndex adapter (FEAT-540 M2)."""

import pytest

from tests.knowledge._support.import_probe import run_import_probe

MODULES = [
    "parrot.knowledge.wiki.triage",
    "parrot.knowledge.wiki.inbox.classify",
    "parrot.knowledge.wiki.inbox.links",
    "parrot.knowledge.wiki.inbox.processor",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_does_not_load_adapter(module: str) -> None:
    """The module imports without loading the PageIndex LLM adapter."""
    result = run_import_probe(module)
    assert result.error is None, result.error
    assert not result.has("parrot.knowledge.pageindex.llm_adapter")
