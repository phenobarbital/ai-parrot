"""FEAT-498 TASK-2750 — structural AbstractTool wrappers + CodeStructuralToolkit."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.project import WikiProjectConfig, load_effective_config
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store
from parrot.knowledge.wiki.structural import (
    CodeStructuralToolkit,
    create_structural_tools,
)
from parrot.knowledge.wiki.tools import WikiQueryTool
from parrot.tools.abstract import ToolResult


def _snapshot(root: Path) -> dict[str, str]:
    """SHA-1 every non-``.parrot`` file under ``root`` (read-only guard)."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".parrot" not in path.parts:
            out[str(path.relative_to(root))] = hashlib.sha1(path.read_bytes()).hexdigest()
    return out


@pytest.fixture
def built_repo(tmp_path: Path) -> Path:
    """A built wiki project with a caller and a callee in two files."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "b.py").write_text("from a import helper\n\n\ndef run():\n    return helper()\n", encoding="utf-8")
    result = CliRunner().invoke(wiki, ["build", "--path", str(root), "--no-git", "-q"])
    assert result.exit_code == 0, result.output
    return root


def _store_and_config(root: Path) -> tuple[BaseWikiStore, WikiProjectConfig]:
    config = load_effective_config(root).config
    storage = config.storage_path(root)
    store = create_wiki_store(storage, wiki_name=config.wiki_name, backend=config.backend)
    return store, config


class TestCreateStructuralTools:
    def test_three_tools_with_expected_names(self, built_repo: Path):
        store, config = _store_and_config(built_repo)
        tools = create_structural_tools(store, built_repo, config)
        assert sorted(t.name for t in tools) == [
            "wiki_blast_radius",
            "wiki_code_outline",
            "wiki_symbol_lookup",
        ]

    @pytest.mark.asyncio
    async def test_symbol_lookup_tool(self, built_repo: Path):
        store, config = _store_and_config(built_repo)
        tools = create_structural_tools(store, built_repo, config)
        lookup = next(t for t in tools if t.name == "wiki_symbol_lookup")
        result = await lookup._execute(query="helper")
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.result["total"] >= 1
        assert result.result["hits"][0]["qualname"] == "helper"
        assert "text" in result.result

    @pytest.mark.asyncio
    async def test_code_outline_tool(self, built_repo: Path):
        store, config = _store_and_config(built_repo)
        tools = create_structural_tools(store, built_repo, config)
        outline = next(t for t in tools if t.name == "wiki_code_outline")
        result = await outline._execute(target="file:a.py")
        assert any(s["qualname"] == "helper" for s in result.result["symbols"])
        assert result.result["language"] == "python"

    @pytest.mark.asyncio
    async def test_blast_radius_tool(self, built_repo: Path):
        store, config = _store_and_config(built_repo)
        tools = create_structural_tools(store, built_repo, config)
        blast = next(t for t in tools if t.name == "wiki_blast_radius")
        result = await blast._execute(symbol="sym:a.py#helper")
        assert "b.py" in result.result["files"]
        assert result.result["root"]["qualname"] == "helper"

    def test_args_schema_fields_match_spec(self, built_repo: Path):
        store, config = _store_and_config(built_repo)
        tools = {t.name: t for t in create_structural_tools(store, built_repo, config)}
        assert set(tools["wiki_symbol_lookup"].args_schema.model_fields) == {
            "query",
            "kind",
            "language",
            "path_prefix",
            "limit",
            "namespace",
        }
        assert set(tools["wiki_code_outline"].args_schema.model_fields) == {
            "target",
            "depth",
            "include_source",
            "namespace",
        }
        assert set(tools["wiki_blast_radius"].args_schema.model_fields) == {
            "symbol",
            "relations",
            "depth",
            "include_inferred",
            "include_tests",
            "namespace",
        }

    def test_read_only_no_writes_to_source_tree(self, built_repo: Path):
        store, config = _store_and_config(built_repo)
        tools = create_structural_tools(store, built_repo, config)
        before = _snapshot(built_repo)

        async def _call_all() -> None:
            for tool in tools:
                if tool.name == "wiki_symbol_lookup":
                    await tool._execute(query="helper")
                elif tool.name == "wiki_code_outline":
                    await tool._execute(target="file:a.py")
                else:
                    await tool._execute(symbol="sym:a.py#helper")

        import asyncio

        asyncio.run(_call_all())
        assert _snapshot(built_repo) == before


class TestCodeStructuralToolkit:
    def test_toolkit_names(self, built_repo: Path):
        tk = CodeStructuralToolkit(root=built_repo)
        assert sorted(t.name for t in tk.get_tools_sync()) == [
            "code_blast_radius",
            "code_outline",
            "code_symbol_lookup",
        ]

    @pytest.mark.asyncio
    async def test_toolkit_methods_share_one_service(self, built_repo: Path):
        tk = CodeStructuralToolkit(root=built_repo)
        lookup = await tk.symbol_lookup("helper")
        outline = await tk.outline("file:a.py")
        blast = await tk.blast_radius("sym:a.py#helper")
        assert lookup["hits"][0]["qualname"] == "helper"
        assert any(s["qualname"] == "helper" for s in outline["symbols"])
        assert "b.py" in blast["files"]

    def test_toolkit_accepts_injected_store_and_config(self, built_repo: Path):
        store, config = _store_and_config(built_repo)
        tk = CodeStructuralToolkit(root=built_repo, store=store, config=config)
        assert tk._store is store
        assert tk._config is config


class TestWikiQueryIncludeSymbols:
    """FEAT-498: wiki_query hides sym: stubs by default (AC in spec §2/§8)."""

    @pytest.mark.asyncio
    async def test_hides_symbols_by_default(self, built_repo: Path):
        store, _config = _store_and_config(built_repo)
        tool = WikiQueryTool(store)
        text = await tool._execute(question="helper")
        assert "sym:a.py#helper" not in text

    @pytest.mark.asyncio
    async def test_shows_symbols_when_included(self, built_repo: Path):
        store, _config = _store_and_config(built_repo)
        tool = WikiQueryTool(store)
        text = await tool._execute(question="helper", include_symbols=True)
        assert "sym:a.py#helper" in text
