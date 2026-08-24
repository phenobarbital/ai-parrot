"""Tests for the gestoria wiki plane + Obsidian mirror (FEAT-453, Module 10).

FEAT-453 TASK-2396. Monkeypatches `build_graph_memory_toolkit`, `WikiConfig`,
and `LLMWikiToolkit` at their source modules — the same seam TASK-2379's own
`_build_notes_wiki_toolkit()` test suite uses — so these tests never build a
real GraphIndex/PageIndex plane or call an LLM provider.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from parrot_tools.business_automation.memory import (
    build_gestoria_wiki,
    record_operation_page,
)


class FakeLLMWikiToolkit:
    """Records the config it was built with; create_wiki is idempotent."""

    def __init__(self, pageindex_toolkit, graphindex_toolkit, okf_toolkit, config, agent_id="agent"):
        self.pageindex_toolkit = pageindex_toolkit
        self.graphindex_toolkit = graphindex_toolkit
        self.okf_toolkit = okf_toolkit
        self._config = config
        self.agent_id = agent_id
        self.create_wiki_calls = []
        self.create_page_calls = []

    async def create_wiki(self, wiki_name, description=None):
        self.create_wiki_calls.append(wiki_name)
        return {"status": "created", "wiki_name": wiki_name}

    async def create_page(self, wiki_name, title, content, category="concept", related_pages=None):
        self.create_page_calls.append((wiki_name, title, content, category))
        return {"page_id": f"page-{title}", "title": title, "category": category, "status": "created"}


@pytest.fixture(autouse=True)
def patch_wiki_seams(monkeypatch):
    """Patch the three heavy construction seams at their source modules —
    mirrors TASK-2379's own test pattern for the identical FEAT-452 recipe.
    """
    import parrot.knowledge.graphindex.factory as graph_factory
    import parrot.knowledge.wiki.models as wiki_models
    import parrot.knowledge.wiki.toolkit as wiki_toolkit_module

    async def _fake_build_graph_memory_toolkit(db_dir, tenant_id="default", agent_id="agent", **kwargs):
        return SimpleNamespace(tenant_id=tenant_id, agent_id=agent_id, db_dir=db_dir)

    class FakeWikiConfig:
        def __init__(self, wiki_name, storage_dir, sync_graph=True, **kwargs):
            self.wiki_name = wiki_name
            self.storage_dir = storage_dir
            self.sync_graph = sync_graph

    monkeypatch.setattr(graph_factory, "build_graph_memory_toolkit", _fake_build_graph_memory_toolkit)
    monkeypatch.setattr(wiki_models, "WikiConfig", FakeWikiConfig)
    monkeypatch.setattr(wiki_toolkit_module, "LLMWikiToolkit", FakeLLMWikiToolkit)


class TestGestoriaPlane:
    async def test_distinct_storage_root(self, tmp_path):
        gestoria_dir = tmp_path / "gestoria"
        other_dir = tmp_path / "other-wiki"
        g = await build_gestoria_wiki(storage_dir=gestoria_dir)
        assert g is not None
        assert g._config.storage_dir != other_dir
        assert g._config.storage_dir == gestoria_dir

    async def test_wiki_name_defaults_to_gestoria(self, tmp_path):
        g = await build_gestoria_wiki(storage_dir=tmp_path / "g")
        assert g._config.wiki_name == "gestoria"

    async def test_create_wiki_idempotent(self, tmp_path):
        storage = tmp_path / "g"
        a = await build_gestoria_wiki(storage_dir=storage)
        b = await build_gestoria_wiki(storage_dir=storage)  # must not raise
        assert a is not None
        assert b is not None
        assert a.create_wiki_calls == ["gestoria"]
        assert b.create_wiki_calls == ["gestoria"]

    async def test_graph_tenant_isolated(self, tmp_path):
        g = await build_gestoria_wiki(storage_dir=tmp_path / "g")
        assert g.graphindex_toolkit.tenant_id == "gestoria"

    async def test_failure_is_best_effort(self, tmp_path, caplog, monkeypatch):
        # Force storage.mkdir() to fail — simulates an unwritable directory
        # without depending on actual filesystem permission semantics
        # (which vary by CI runner / root user).
        from pathlib import Path

        def _raise_mkdir(self, *args, **kwargs):
            raise PermissionError("simulated unwritable directory")

        monkeypatch.setattr(Path, "mkdir", _raise_mkdir)
        result = await build_gestoria_wiki(storage_dir=tmp_path / "unwritable")
        assert result is None
        assert "gestoria" in caplog.text

    async def test_create_wiki_failure_does_not_null_toolkit(self, tmp_path, caplog, monkeypatch):
        # A create_wiki() bootstrap failure must be caught separately from
        # toolkit construction — the toolkit itself is still returned.
        import parrot.knowledge.wiki.toolkit as wiki_toolkit_module

        class RaisingWikiToolkit(FakeLLMWikiToolkit):
            async def create_wiki(self, wiki_name, description=None):
                raise RuntimeError("simulated create_wiki failure")

        monkeypatch.setattr(wiki_toolkit_module, "LLMWikiToolkit", RaisingWikiToolkit)
        result = await build_gestoria_wiki(storage_dir=tmp_path / "g")
        assert result is not None
        assert "gestoria" in caplog.text


class TestRecordOperationPage:
    async def test_records_wiki_page_with_expected_fields(self, tmp_path):
        wiki = await build_gestoria_wiki(storage_dir=tmp_path / "g")
        result = await record_operation_page(
            wiki=wiki,
            obsidian=None,
            operation="register_expense",
            params={"client": "ACME", "amount": "100.00"},
            gate_decision="confirmed",
            outcome="done",
            run_id="run_abc123",
        )
        assert result["wiki"] is not None
        assert len(wiki.create_page_calls) == 1
        wiki_name, title, content, category = wiki.create_page_calls[0]
        assert wiki_name == "gestoria"
        assert "register_expense" in title
        assert "run_abc123" in title
        assert "confirmed" in content
        assert "done" in content
        # Raw param values must never leak into the recorded page.
        assert "ACME" not in content
        assert "100.00" not in content

    async def test_mirrors_to_obsidian(self, tmp_path):
        wiki = await build_gestoria_wiki(storage_dir=tmp_path / "g")
        obsidian = AsyncMock()
        obsidian.create_note = AsyncMock(return_value={"status": "created"})

        result = await record_operation_page(
            wiki=wiki,
            obsidian=obsidian,
            operation="register_expense",
            params={"client": "ACME"},
            gate_decision="confirmed",
            outcome="done",
            run_id="run_abc123",
        )
        assert result["obsidian"] is not None
        obsidian.create_note.assert_awaited_once()
        args, kwargs = obsidian.create_note.call_args
        note_path = args[0]
        assert "register_expense" in note_path
        assert "run_abc123" in note_path

    async def test_wiki_failure_is_best_effort(self, tmp_path, caplog):
        wiki = await build_gestoria_wiki(storage_dir=tmp_path / "g")

        async def _raise(*args, **kwargs):
            raise RuntimeError("boom")

        wiki.create_page = _raise
        result = await record_operation_page(
            wiki=wiki,
            obsidian=None,
            operation="register_expense",
            params={},
            gate_decision="confirmed",
            outcome="done",
            run_id="run_1",
        )
        assert result["wiki"] is None  # failed, but did not raise

    async def test_obsidian_failure_is_best_effort(self, tmp_path):
        wiki = await build_gestoria_wiki(storage_dir=tmp_path / "g")
        obsidian = AsyncMock()
        obsidian.create_note = AsyncMock(side_effect=RuntimeError("vault locked"))

        result = await record_operation_page(
            wiki=wiki,
            obsidian=obsidian,
            operation="register_expense",
            params={},
            gate_decision="confirmed",
            outcome="done",
            run_id="run_1",
        )
        assert result["obsidian"] is None  # failed, but did not raise

    async def test_none_wiki_and_none_obsidian_is_a_noop(self):
        result = await record_operation_page(
            wiki=None,
            obsidian=None,
            operation="register_expense",
            params={},
            gate_decision="confirmed",
            outcome="done",
            run_id="run_1",
        )
        assert result == {"wiki": None, "obsidian": None}
