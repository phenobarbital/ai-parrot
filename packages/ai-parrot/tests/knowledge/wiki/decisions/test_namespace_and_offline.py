"""Namespace isolation, CLI/MCP parity and offline guarantees (spec §4)."""

from __future__ import annotations

import asyncio
import json

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.decisions import create_decision_tools
from parrot.knowledge.wiki.decisions.ingest import refresh_decisions
from parrot.knowledge.wiki.decisions.models import DecisionConfig
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle
from parrot.knowledge.wiki.project import WikiNamespaceConfig, WikiProjectConfig
from parrot.knowledge.wiki.store import create_wiki_store


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _build(runner: CliRunner, root) -> None:
    result = runner.invoke(wiki, ["build", "--path", str(root), "--no-graph", "--quiet"])
    assert result.exit_code == 0, result.output


def _make_adr_project(tmp_path, name: str, decision_text: str):
    """A minimal one-ADR project, independent of the shared adr_repo fixture."""
    root = tmp_path / name
    adr_dir = root / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0042-shared-number.md").write_text(
        f"# {decision_text}\n\n## Context\nSome context.\n\n## Decision\n{decision_text}\n\n"
        "## Consequences\nSome consequences.\n",
        encoding="utf-8",
    )
    return root


class TestNamespaceIsolation:
    async def test_same_adr_number_in_two_namespaces_stays_distinct(self, tmp_path):
        """spec §4 test_namespace_isolation.

        Both projects use the SAME ADR filename (so the same rel_path-derived
        decision_id is minted in each plane independently); federating them
        must still keep each namespace's own content distinct.
        """
        other_root = _make_adr_project(tmp_path, "other", "Use milvus")
        other_store = create_wiki_store(other_root / ".wiki-storage", wiki_name="other", backend="sqlite")
        await refresh_decisions(other_store, other_root, DecisionConfig(), None)

        local_root = _make_adr_project(tmp_path, "local", "Use pgvector")
        local_store = create_wiki_store(local_root / ".wiki-storage", wiki_name="local", backend="sqlite")
        await refresh_decisions(local_store, local_root, DecisionConfig(), None)

        handle = NamespaceHandle(name="other", store=other_store, config=WikiNamespaceConfig(path=str(other_root)))
        federated = FederatedWikiStore(local_store, "local", [handle], [])

        tools = create_decision_tools(federated, local_root, WikiProjectConfig())
        why_tool = next(t for t in tools if t.name == "wiki_decision_why")

        local_result = await why_tool._execute(question="pgvector milvus", namespace=None)
        other_result = await why_tool._execute(question="pgvector milvus", namespace="other")

        assert "pgvector" in local_result.result.lower()
        assert "milvus" not in local_result.result.lower()
        assert "milvus" in other_result.result.lower()
        assert "pgvector" not in other_result.result.lower()

    async def test_remote_reads_are_unverified(self, tmp_path):
        """No local root -> freshness is 'unverified', never 'current' (spec §2)."""
        from parrot.knowledge.wiki.decisions.models import DecisionRecord
        from parrot.knowledge.wiki.decisions.service import DecisionService
        from parrot.knowledge.wiki.file_store import InMemoryWikiStore

        store = InMemoryWikiStore(tmp_path / "remote-plane", wiki_name="remote")
        record = DecisionRecord(
            decision_id="adr:doc:remote", decision="a decision with no local root", origin="documented"
        )
        await DecisionRepository(store).save(record, None)

        service = DecisionService(store, None, DecisionConfig())
        dossier = await service.why("decision")
        assert dossier.status == "ok"
        assert all(hit.freshness == "unverified" for hit in dossier.documented)

    async def test_broadcast_writes_are_refused(self, runner, adr_repo):
        """--ns all is ADR_INVALID_ARGUMENT in v1, on both surfaces."""
        # `_build` invokes a Click command that runs `asyncio.run()`
        # internally; called directly from this `async def` test, that
        # collides with pytest-asyncio's already-running loop. Run it on a
        # thread instead, same as a real CLI invocation would (no loop of
        # its own to collide with).
        await asyncio.to_thread(_build, runner, adr_repo)
        cli_result = runner.invoke(wiki, ["adr", "why", "why", "--ns", "all", "--json", "--path", str(adr_repo)])
        assert cli_result.exit_code == 2
        cli_payload = json.loads(cli_result.stderr or cli_result.output)
        assert cli_payload["error"]["code"] == "ADR_INVALID_ARGUMENT"

        config = WikiProjectConfig()
        store = create_wiki_store(adr_repo / ".parrot", wiki_name="w", backend="sqlite")
        tool = next(t for t in create_decision_tools(store, adr_repo, config) if t.name == "wiki_decision_why")
        tool_result = await tool._execute(question="why", namespace="all")
        assert tool_result.success is False
        assert "ADR_INVALID_ARGUMENT" in (tool_result.error or "")


class TestCliMcpParity:
    async def test_cli_mcp_parity(self, runner, adr_repo):
        """spec §4: equivalent data and identical error codes on both surfaces."""
        # `runner.invoke` runs a Click command that calls `asyncio.run()`
        # internally; every invocation in this async test is threaded for
        # the same reason `_build` is (see `test_broadcast_writes_are_refused`).
        await asyncio.to_thread(_build, runner, adr_repo)
        await asyncio.to_thread(runner.invoke, wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])

        cli_result = await asyncio.to_thread(
            runner.invoke, wiki, ["adr", "why", "pgvector", "--json", "--path", str(adr_repo)]
        )
        assert cli_result.exit_code == 0, cli_result.output
        cli_dossier = json.loads(cli_result.output)

        from parrot.knowledge.wiki.cli import _open_store, _resolve_project

        root, config = _resolve_project(str(adr_repo))
        store = _open_store(root, config)
        tool = next(t for t in create_decision_tools(store, root, config) if t.name == "wiki_decision_why")
        tool_result = await tool._execute(question="pgvector")
        tool_dossier = json.loads(tool_result.result.rsplit("\n\n", 1)[-1])

        cli_ids = sorted(h["decision_id"] for h in cli_dossier["documented"])
        tool_ids = sorted(h["decision_id"] for h in tool_dossier["documented"])
        assert cli_ids == tool_ids
        assert [h["origin"] for h in cli_dossier["documented"]] == [h["origin"] for h in tool_dossier["documented"]]

        # Trigger the same failure on both surfaces and assert the SAME code.
        cli_fail = await asyncio.to_thread(
            runner.invoke, wiki, ["adr", "why", "q", "--ns", "all", "--json", "--path", str(adr_repo)]
        )
        cli_fail_payload = json.loads(cli_fail.stderr or cli_fail.output)
        tool_fail = await tool._execute(question="q", namespace="all")
        assert cli_fail_payload["error"]["code"] == "ADR_INVALID_ARGUMENT"
        assert "ADR_INVALID_ARGUMENT" in (tool_fail.error or "")

    def test_stdout_remains_protocol_safe(self, runner, adr_repo):
        """--json stdout must always parse, even when warnings are logged."""
        _build(runner, adr_repo)
        result = runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])
        # sync exits 1 on diagnostics (the fixture's malformed-frontmatter ADR),
        # but stdout must still be valid JSON — diagnostics go to stderr in the
        # non-JSON branch only; in --json mode the whole payload is one blob.
        json.loads(result.output)


class TestOfflineAndDisabledGeneration:
    def test_build_lookup_why_never_construct_an_llm(self, runner, adr_repo, monkeypatch):
        """AC5: spec §4 test_offline_and_disabled_generation."""
        from parrot.clients.factory import LLMFactory

        def _boom_create(*args, **kwargs):
            raise AssertionError("LLMFactory.create must never be called on a read path")

        monkeypatch.setattr(LLMFactory, "create", staticmethod(_boom_create))

        _build(runner, adr_repo)
        sync_result = runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])
        assert sync_result.exit_code in (0, 1)
        lookup_result = runner.invoke(
            wiki, ["adr", "lookup", "sym:src/citing_module.py#ClassA.run", "--json", "--path", str(adr_repo)]
        )
        assert lookup_result.exit_code == 0, lookup_result.output
        why_result = runner.invoke(wiki, ["adr", "why", "pgvector", "--json", "--path", str(adr_repo)])
        assert why_result.exit_code == 0, why_result.output

    def test_generation_failure_leaves_ordinary_wiki_working(self, runner, adr_repo, monkeypatch):
        """A broken model must not degrade the read surfaces."""
        monkeypatch.setenv("WIKI_ADR_LLM", "openai:gpt-does-not-exist")
        _build(runner, adr_repo)
        runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])

        # Enable generation via the project config so `adr generate` attempts
        # to resolve a (bogus) client instead of refusing with UNCONFIGURED.
        from parrot.knowledge.wiki.project import load_project_config, save_project_config

        config = load_project_config(adr_repo)
        config.decisions.generation_enabled = True
        save_project_config(adr_repo, config)

        generate_result = runner.invoke(
            wiki, ["adr", "generate", "src/citing_module.py", "--json", "--path", str(adr_repo)]
        )
        assert generate_result.exit_code == 1, generate_result.output

        why_result = runner.invoke(wiki, ["adr", "why", "pgvector", "--json", "--path", str(adr_repo)])
        assert why_result.exit_code == 0, why_result.output
        query_result = runner.invoke(wiki, ["query", "pgvector", "--json", "--path", str(adr_repo)])
        assert query_result.exit_code == 0, query_result.output

    def test_existing_search_and_source_slices_are_unaffected(self, runner, adr_repo):
        """AC10: existing symbol ids and search behaviour are unchanged."""
        _build(runner, adr_repo)
        before_query = runner.invoke(wiki, ["query", "ClassA", "--json", "--path", str(adr_repo)])
        before_symbols = runner.invoke(wiki, ["symbols", "lookup", "ClassA.run", "--json", "--path", str(adr_repo)])
        assert before_query.exit_code == 0
        assert before_symbols.exit_code == 0

        runner.invoke(wiki, ["adr", "sync", "--json", "--path", str(adr_repo)])

        after_query = runner.invoke(wiki, ["query", "ClassA", "--json", "--path", str(adr_repo)])
        after_symbols = runner.invoke(wiki, ["symbols", "lookup", "ClassA.run", "--json", "--path", str(adr_repo)])
        assert after_query.exit_code == 0
        assert after_symbols.exit_code == 0
        assert json.loads(before_symbols.output) == json.loads(after_symbols.output)
