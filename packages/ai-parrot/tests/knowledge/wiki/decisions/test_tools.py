"""Tool registration, gating and namespace policy (FEAT-578 M6, AC9/AC11)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions import create_decision_tools
from parrot.knowledge.wiki.decisions.models import DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.project import WikiProjectConfig, save_project_config


def _config(generation_enabled: bool = False) -> WikiProjectConfig:
    config = WikiProjectConfig()
    config.decisions.generation_enabled = generation_enabled
    return config


class TestRegistration:
    def test_read_tools_are_always_registered(self, adr_store, tmp_path):
        names = {t.name for t in create_decision_tools(adr_store, tmp_path, _config())}
        assert {"wiki_decisions_for_symbol", "wiki_decision_why"} <= names

    def test_generate_is_absent_by_default(self, adr_store, tmp_path):
        """AC5: the shipped default cannot invoke a model."""
        names = {t.name for t in create_decision_tools(adr_store, tmp_path, _config())}
        assert "wiki_decision_generate" not in names

    def test_generate_appears_only_when_enabled_and_local(self, adr_store, tmp_path):
        with_local = {t.name for t in create_decision_tools(adr_store, tmp_path, _config(True))}
        assert "wiki_decision_generate" in with_local

        remote = {t.name for t in create_decision_tools(adr_store, None, _config(True))}
        assert "wiki_decision_generate" not in remote

    def test_no_review_or_accept_tool_exists(self, adr_store, tmp_path):
        """AC11: an agent can never accept a candidate."""
        names = {t.name for t in create_decision_tools(adr_store, tmp_path, _config(True))}
        assert not any("review" in n or "accept" in n for n in names)

    def test_mcp_server_registers_the_read_tools(self, tmp_path):
        from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server

        save_project_config(tmp_path, WikiProjectConfig(wiki_name="decisions-test"))
        server = create_wiki_mcp_server(tmp_path)
        assert {"wiki_decisions_for_symbol", "wiki_decision_why"} <= set(server.tools)
        assert "wiki_decision_generate" not in server.tools


class TestNamespacePolicy:
    async def test_all_namespace_is_rejected(self, adr_store, tmp_path):
        """spec §2 Module 6: 'all' is ADR_INVALID_ARGUMENT in v1."""
        tool = next(t for t in create_decision_tools(adr_store, tmp_path, _config()) if t.name == "wiki_decision_why")
        result = await tool._execute(question="why", namespace="all")
        assert result.success is False
        assert "ADR_INVALID_ARGUMENT" in (result.error or "")

    async def test_unknown_namespace_is_a_structured_error(self, adr_store, tmp_path):
        """A plain store treats any namespace as a no-op (`_scoped_store`'s own
        contract), so this needs a genuinely federated store — with zero
        opened namespaces — to exercise the KeyError -> ValueError -> error
        ToolResult path at all."""
        from parrot.knowledge.wiki.federation import FederatedWikiStore

        federated = FederatedWikiStore(adr_store, "local", [], [])
        tool = next(t for t in create_decision_tools(federated, tmp_path, _config()) if t.name == "wiki_decision_why")
        result = await tool._execute(question="why", namespace="nope-does-not-exist")
        assert result.success is False
        assert result.error


class TestOutputLabels:
    async def test_candidates_are_labeled_in_the_text_body(self, adr_store, tmp_path):
        """AC9: labels survive the tool's own output budget."""
        record = DecisionRecord(decision_id="adr:candidate:x", decision="use exponential backoff", origin="inferred")
        await DecisionRepository(adr_store).save(record, None)
        tool = next(t for t in create_decision_tools(adr_store, tmp_path, _config()) if t.name == "wiki_decision_why")
        result = await tool._execute(question="backoff", budget_tokens=256)
        assert result.success is not False
        assert "INFERRED" in result.result


class TestToolkit:
    def test_tool_prefix_and_methods(self, adr_store, tmp_path):
        from parrot.knowledge.wiki.decisions import DecisionToolkit

        toolkit = DecisionToolkit(root=tmp_path, store=adr_store)
        assert toolkit.tool_prefix == "decision"
        names = {t.name for t in toolkit.get_tools_sync()}
        assert names == {"decision_for_symbol", "decision_why"}

    def test_toolkit_never_exposes_review(self, adr_store, tmp_path):
        from parrot.knowledge.wiki.decisions import DecisionToolkit

        toolkit = DecisionToolkit(root=tmp_path, store=adr_store, include_generation=True)
        assert not any("review" in t.name for t in toolkit.get_tools_sync())
