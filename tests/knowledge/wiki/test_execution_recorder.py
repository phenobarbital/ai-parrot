"""Unit tests for ExecutionWikiRecorder (crew execution wiki).

Drives the recorder against a real temp-dir SQLite plane — page/edge
mapping, BM25 search over tool-call results, run lifecycle updates, and
``wikitoolkit`` CLI compatibility. No LLM, no crew.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.execution import (
    CATEGORY_AGENT,
    CATEGORY_RUN,
    CATEGORY_TOOL,
    REL_CONTAINS,
    REL_FOLLOWS,
    REL_USED_TOOL,
    ExecutionWikiRecorder,
    crew_slug,
    default_wiki_dir,
)


def _node_result(node_id: str, node_name: str, task: str, text: str):
    """Minimal NodeResult stand-in exposing the attrs the recorder reads."""
    ns = types.SimpleNamespace(node_id=node_id, node_name=node_name, task=task)
    ns.to_text = lambda: text
    return ns


def _flow_result(output: str, summary: str = "", status: str = "completed"):
    return types.SimpleNamespace(
        output=output, summary=summary, status=status, total_time=1.5
    )


@pytest.fixture
def recorder(tmp_path: Path) -> ExecutionWikiRecorder:
    return ExecutionWikiRecorder(tmp_path / "wiki", "Research Crew")


class TestSlugHelpers:
    def test_crew_slug_normalises(self):
        assert crew_slug("My Research Crew!") == "my-research-crew"
        assert crew_slug("") == "crew"

    def test_default_wiki_dir(self, tmp_path):
        path = default_wiki_dir("My Crew", base_dir=tmp_path)
        assert path == tmp_path / ".parrot" / "crew_wiki" / "my-crew"


class TestRecording:
    @pytest.mark.asyncio
    async def test_run_start_creates_run_page(self, recorder):
        await recorder.record_run_start(
            "e1", method="run_sequential", task="find solar prices",
            user_id="u1", session_id="s1", tenant="acme",
        )
        page = await recorder.get_page("run:e1")
        assert page is not None
        assert page["category"] == CATEGORY_RUN
        assert page["source_id"] == "exec:e1"
        assert "find solar prices" in page["body"]
        assert "run_sequential" in page["body"]

    @pytest.mark.asyncio
    async def test_agent_result_pages_and_edges(self, recorder):
        await recorder.record_run_start("e1", method="run_flow", task="t")
        await recorder.record_agent_result(
            "e1",
            _node_result("a1", "Agent One", "research task",
                         "Monocrystalline panels cost $0.28/W"),
            tool_calls=[{
                "id": "c1", "name": "web_search",
                "arguments": {"q": "panel prices"},
                "result": "Price index says $0.28 per watt",
                "execution_time": 0.4,
            }],
        )
        await recorder.record_agent_result(
            "e1",
            _node_result("a2", "Agent Two", "summarize", "Summary text"),
        )

        agent_page = await recorder.get_page("agent:e1:a1")
        assert agent_page["category"] == CATEGORY_AGENT
        assert "Monocrystalline" in agent_page["body"]

        tool_page = await recorder.get_page("tool:e1:a1:c1")
        assert tool_page["category"] == CATEGORY_TOOL
        assert "Price index says $0.28 per watt" in tool_page["body"]
        assert "web_search" in tool_page["title"]

        rels = await recorder.related("agent:e1:a1")
        by_rel = {(r["rel"], r["direction"]) for r in rels}
        assert (REL_CONTAINS, "in") in by_rel      # run contains agent
        assert (REL_USED_TOOL, "out") in by_rel    # agent used tool
        assert (REL_FOLLOWS, "in") in by_rel       # a2 follows a1

    @pytest.mark.asyncio
    async def test_run_end_appends_final_output(self, recorder):
        await recorder.record_run_start("e1", method="run_parallel", task="t")
        await recorder.record_run_end("e1", _flow_result("THE FINAL ANSWER"))
        page = await recorder.get_page("run:e1")
        assert "THE FINAL ANSWER" in page["body"]
        assert "completed" in page["body"]

    @pytest.mark.asyncio
    async def test_record_methods_never_raise(self, recorder):
        # Objects missing every expected attribute must not break a run.
        await recorder.record_agent_result("e1", object())
        await recorder.record_run_end("e1", object())


class TestSearch:
    @pytest.mark.asyncio
    async def test_bm25_finds_tool_call_content(self, recorder):
        await recorder.record_run_start("e1", method="run_flow", task="t")
        await recorder.record_agent_result(
            "e1",
            _node_result("a1", "Agent One", "task", "agent body"),
            tool_calls=[{
                "id": "c1", "name": "db_query",
                "arguments": {"sql": "select revenue"},
                "result": "quarterly revenue was 42 million zorkmids",
            }],
        )
        hits = await recorder.search("zorkmids revenue", top_k=5)
        assert hits
        assert hits[0]["concept_id"] == "tool:e1:a1:c1"
        assert hits[0]["category"] == CATEGORY_TOOL
        assert 0.0 <= hits[0]["score"] <= 1.0
        assert hits[0]["source"] == "lexical"

    @pytest.mark.asyncio
    async def test_category_filter(self, recorder):
        await recorder.record_agent_result(
            "e1",
            _node_result("a1", "Agent One", "task", "shared keyword aardvark"),
            tool_calls=[{
                "id": "c1", "name": "t", "arguments": {},
                "result": "shared keyword aardvark",
            }],
        )
        hits = await recorder.search("aardvark", category=CATEGORY_AGENT)
        assert hits
        assert all(h["category"] == CATEGORY_AGENT for h in hits)

    @pytest.mark.asyncio
    async def test_execution_id_filter(self, recorder):
        for eid in ("e1", "e2"):
            await recorder.record_agent_result(
                eid, _node_result("a1", "Agent", "task", "wombat sighting"),
            )
        hits = await recorder.search("wombat", execution_id="e2")
        assert hits
        assert all(h["source_id"] == "exec:e2" for h in hits)

    @pytest.mark.asyncio
    async def test_empty_wiki_returns_empty(self, recorder):
        assert await recorder.search("anything") == []


class TestEmbedder:
    @pytest.mark.asyncio
    async def test_async_embedder_populates_vector_leg(self, tmp_path):
        async def embed(text: str):
            # Toy 2-d embedding: [has-cat, has-dog]
            return [float("cat" in text), float("dog" in text)]

        rec = ExecutionWikiRecorder(
            tmp_path / "wiki", "c", embedding_model=embed
        )
        await rec.record_agent_result(
            "e1", _node_result("a1", "A", "t", "a page about cat behaviour"),
        )
        stats = await rec.stats()
        assert stats["embeddings"] == 1
        hits = await rec.search("cat", top_k=3)
        assert hits
        assert any(h["source"] == "vector" for h in hits) or hits

    def test_unusable_embedding_model_degrades_to_bm25(self, tmp_path):
        rec = ExecutionWikiRecorder(
            tmp_path / "wiki", "c", embedding_model=object()
        )
        assert rec._embedder is None


class TestCliCompat:
    """The execution wiki is a standard wiki.db — wikitoolkit reads it.

    These tests are synchronous: the click commands call ``asyncio.run``
    internally, which cannot run inside pytest-asyncio's event loop.
    """

    @staticmethod
    def _populate(storage: Path) -> None:
        import asyncio

        async def _fill():
            rec = ExecutionWikiRecorder(storage, "cli-crew")
            await rec.record_agent_result(
                "e1",
                _node_result("a1", "Agent", "t", "body"),
                tool_calls=[{
                    "id": "c1", "name": "search", "arguments": {},
                    "result": "the xylophone factory output doubled",
                }],
            )

        asyncio.run(_fill())

    def test_query_via_store_flag(self, tmp_path):
        storage = tmp_path / "wiki"
        self._populate(storage)
        runner = CliRunner()
        result = runner.invoke(
            wiki, ["query", "xylophone factory", "--store", str(storage)]
        )
        assert result.exit_code == 0, result.output
        assert "tool:e1:a1:c1" in result.output

    def test_query_via_path_uses_written_config(self, tmp_path):
        storage = tmp_path / "wiki"
        self._populate(storage)
        # Recorder wrote {storage}/.parrot/wiki.json with storage_dir="."
        assert (storage / ".parrot" / "wiki.json").exists()
        runner = CliRunner()
        result = runner.invoke(
            wiki, ["query", "xylophone factory", "--path", str(storage)]
        )
        assert result.exit_code == 0, result.output
        assert "tool:e1:a1:c1" in result.output

    def test_page_command_reads_tool_page(self, tmp_path):
        storage = tmp_path / "wiki"
        self._populate(storage)
        runner = CliRunner()
        result = runner.invoke(
            wiki, ["page", "tool:e1:a1:c1", "--store", str(storage)]
        )
        assert result.exit_code == 0, result.output
        assert "xylophone factory" in result.output
