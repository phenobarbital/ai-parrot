"""Unit tests for the derived GraphIndex/PageIndex rebuild (FEAT-481, spec
Module 13): the vault ingest MUST exclude ``Private/`` (contract rule #1 —
"Never access Private/. Do not read, list, search, index, summarize, move,
modify, or traverse it.").

Regression test for a code-review finding (post-FEAT-481 PR review): the
loader's own default exclusions are only ``.obsidian``/``.trash``/``.git``,
so a naive ``ingest_obsidian_vault()`` call would silently index every
``Private/`` note into the derived plane on every ingest.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from parrot.flows.wiki_ingest import conf
from parrot.flows.wiki_ingest import graph as graph_module
from parrot.flows.wiki_ingest.graph import (
    WIKI_KB_GRAPH_WIKI_NAME,
    _build_arango_wiki_store,
    _graph_backend,
    build_wiki_kb_graph_toolkit,
    rebuild_graph_index,
)


@pytest.mark.asyncio
async def test_rebuild_graph_index_excludes_private(tmp_path: Path) -> None:
    """``rebuild_graph_index`` must ask the loader to skip ``Private/``."""
    toolkit = AsyncMock()
    toolkit.ingest_obsidian_vault = AsyncMock(return_value={"raw_ingest": {}, "graph_bridge": {}})

    await rebuild_graph_index(toolkit, vault_path=tmp_path)

    toolkit.ingest_obsidian_vault.assert_awaited_once()
    _, kwargs = toolkit.ingest_obsidian_vault.await_args
    assert kwargs.get("extra_skip_patterns") == ["Private"]
    assert kwargs.get("incremental") is True
    assert toolkit.ingest_obsidian_vault.await_args.args[0] == WIKI_KB_GRAPH_WIKI_NAME


@pytest.mark.asyncio
async def test_extra_skip_patterns_actually_excludes_private_notes(tmp_path: Path) -> None:
    """The mechanism ``ingest_obsidian_vault(extra_skip_patterns=...)``
    relies on — merging into the loader's ``vault.skip_patterns`` — must
    genuinely exclude a ``Private/`` note from vault discovery, not just
    be threaded through as an unused kwarg.
    """
    from parrot.loaders.obsidian import ObsidianVaultLoader

    (tmp_path / "Private").mkdir()
    (tmp_path / "Private" / "secret.md").write_text("# Secret\nDo not index.", encoding="utf-8")
    (tmp_path / "Wiki").mkdir()
    (tmp_path / "Wiki" / "public.md").write_text("# Public\nFine to index.", encoding="utf-8")

    loader = ObsidianVaultLoader(tmp_path)
    loader.vault.skip_patterns = loader.vault.skip_patterns | frozenset({"Private"})

    notes, _ = await loader.discover()
    paths = [n.path.as_posix() for n in notes]

    assert not any(p.startswith("Private/") for p in paths)
    assert any(p.startswith("Wiki/") for p in paths)


# ---------------------------------------------------------------------------
# Configurable retrieval-plane backend (Amendment A6)
# ---------------------------------------------------------------------------


def test_graph_backend_default_is_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default (and unset) resolves to sqlite — nothing changes for existing
    deployments unless WIKI_KB_GRAPH_BACKEND is explicitly set."""
    monkeypatch.setattr(conf, "WIKI_KB_GRAPH_BACKEND", "sqlite")
    assert _graph_backend() == "sqlite"


def test_graph_backend_arangodb_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conf, "WIKI_KB_GRAPH_BACKEND", "ArangoDB")
    assert _graph_backend() == "arangodb"


def test_graph_backend_invalid_falls_back_to_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unknown backend never crashes the (non-fatal, D3) rebuild — it
    falls back to sqlite."""
    monkeypatch.setattr(conf, "WIKI_KB_GRAPH_BACKEND", "postgres")
    assert _graph_backend() == "sqlite"


def test_build_arango_wiki_store_honours_config_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """WIKI_KB_ARANGO_* drive the store's database, credentials (via the env
    prefix), and text analyzer — and the constructor opens NO connection."""
    monkeypatch.setattr(conf, "WIKI_KB_ARANGO_DATABASE", "meetings_kb")
    monkeypatch.setattr(conf, "WIKI_KB_ARANGO_CREDENTIALS_PREFIX", "WIKIKBTEST")
    monkeypatch.setattr(conf, "WIKI_KB_ARANGO_TEXT_ANALYZER", "text_en,text_es")
    monkeypatch.setenv("WIKIKBTEST_HOST", "10.0.0.5")
    monkeypatch.setenv("WIKIKBTEST_PORT", "9999")
    monkeypatch.setenv("WIKIKBTEST_USERNAME", "kb")
    monkeypatch.setenv("WIKIKBTEST_PASSWORD", "s3cret")

    store = _build_arango_wiki_store("fireflies_wiki_kb")

    assert store._database == "meetings_kb"
    assert store._params["host"] == "10.0.0.5"
    assert store._params["port"] == 9999
    assert store._params["username"] == "kb"
    assert store._params["password"] == "s3cret"
    assert store._text_analyzer == "text_en,text_es"


def test_build_arango_wiki_store_database_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty WIKI_KB_ARANGO_DATABASE falls back to wiki_<wiki_name>."""
    monkeypatch.setattr(conf, "WIKI_KB_ARANGO_DATABASE", "")
    monkeypatch.setattr(conf, "WIKI_KB_ARANGO_CREDENTIALS_PREFIX", "ARANGODB")
    store = _build_arango_wiki_store("fireflies_wiki_kb")
    assert store._database == "wiki_fireflies_wiki_kb"


@pytest.mark.asyncio
async def test_build_toolkit_sqlite_backend_injects_no_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the default sqlite backend, no pre-built store is injected —
    LLMWikiToolkit builds its own local plane (historical behaviour)."""
    captured: dict = {}

    def _fake_toolkit(pi, gi, okf, config, *, agent_id, store, **kwargs):
        captured["storage_backend"] = config.storage_backend
        captured["store"] = store
        return object()

    monkeypatch.setattr(conf, "WIKI_KB_GRAPH_BACKEND", "sqlite")
    monkeypatch.setattr(graph_module, "_build_pageindex_toolkit", lambda storage: object())
    monkeypatch.setattr(graph_module, "build_graph_memory_toolkit", AsyncMock(return_value=object()))
    monkeypatch.setattr(graph_module, "LLMWikiToolkit", _fake_toolkit)

    await build_wiki_kb_graph_toolkit(tmp_path)

    assert captured["storage_backend"] == "sqlite"
    assert captured["store"] is None


@pytest.mark.asyncio
async def test_build_toolkit_arangodb_backend_injects_arango_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With WIKI_KB_GRAPH_BACKEND=arangodb, the toolkit is built with
    storage_backend='arangodb' and a pre-built ArangoDBWikiStore injected
    (no connection is opened)."""
    from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore

    captured: dict = {}

    def _fake_toolkit(pi, gi, okf, config, *, agent_id, store, **kwargs):
        captured["storage_backend"] = config.storage_backend
        captured["store"] = store
        return object()

    monkeypatch.setattr(conf, "WIKI_KB_GRAPH_BACKEND", "arangodb")
    monkeypatch.setattr(conf, "WIKI_KB_ARANGO_DATABASE", "meetings_kb")
    monkeypatch.setattr(graph_module, "_build_pageindex_toolkit", lambda storage: object())
    monkeypatch.setattr(graph_module, "build_graph_memory_toolkit", AsyncMock(return_value=object()))
    monkeypatch.setattr(graph_module, "LLMWikiToolkit", _fake_toolkit)

    await build_wiki_kb_graph_toolkit(tmp_path)

    assert captured["storage_backend"] == "arangodb"
    assert isinstance(captured["store"], ArangoDBWikiStore)
    assert captured["store"]._database == "meetings_kb"
