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
from parrot.flows.wiki_ingest.graph import WIKI_KB_GRAPH_WIKI_NAME, rebuild_graph_index


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
