"""Derived GraphIndex/PageIndex rebuild (FEAT-481, spec Module 13, D3).

Mirrors the ``LLMWikiToolkit`` construction pattern already used by
``agents/fireflies_wiki.py`` (``_build_wiki_toolkit``/
``_build_pageindex_toolkit``) — a **new**, independent wiring for this
subsystem's own wiki plane (never a shared instance with that agent,
G11). **Derived only (D3/R1):** this plane is rebuilt from the vault
every ingest; it is never the content authority (the Obsidian vault
pages are) and never the dedup gate (``MeetingRegistry`` is, spec
Module 2) — a missing/stale GraphIndex must never block ingest or cause
a re-download.

**Storage location.** No new ``conf.py`` key is needed: this plane's
storage lives at ``<vault>/.wiki_kb/graph`` — a hidden directory
alongside the vault (like ``.obsidian/``), never inside ``Wiki/`` (which
holds only Claude-managed *content* pages, spec §4) and never confused
with Obsidian-visible material.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from parrot.clients.factory import LLMFactory
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

from . import conf

logger = logging.getLogger(__name__)

#: This subsystem's own wiki plane name — distinct from
#: ``agents/fireflies_wiki.py``'s ``wiki_name`` (no shared instance, G11).
WIKI_KB_GRAPH_WIKI_NAME = "fireflies_wiki_kb"


def graph_storage_dir(vault_path: str | Path) -> Path:
    """Directory backing this subsystem's own GraphIndex/PageIndex plane.

    Args:
        vault_path: The Obsidian vault root.

    Returns:
        ``<vault_path>/.wiki_kb/graph`` — see the module docstring.
    """
    return Path(vault_path) / ".wiki_kb" / "graph"


def _build_pageindex_toolkit(storage: Path) -> PageIndexToolkit | None:
    """Build the PageIndex authoring plane (mirrors ``agents/fireflies_wiki.py``).

    Args:
        storage: This subsystem's wiki storage root.

    Returns:
        A :class:`PageIndexToolkit`, or ``None`` when construction fails
        (retrieval-only degradation — never blocks ingest).
    """
    try:
        _, model_id = LLMFactory.parse_llm_string(conf.WIKI_KB_LLM_CHEAP)
        adapter = PageIndexLLMAdapter(LLMFactory.create(conf.WIKI_KB_LLM_CHEAP), model=model_id)
        pageindex_dir = storage / "pageindex"
        pageindex_dir.mkdir(parents=True, exist_ok=True)
        return PageIndexToolkit(adapter, storage_dir=pageindex_dir)
    except Exception:  # noqa: BLE001 — authoring plane is optional
        logger.warning("PageIndexToolkit unavailable; wiki pages will be written to the retrieval plane only.")
        return None


async def build_wiki_kb_graph_toolkit(
    vault_path: str | Path,
    *,
    wiki_name: str = WIKI_KB_GRAPH_WIKI_NAME,
) -> LLMWikiToolkit:
    """Construct this subsystem's own :class:`LLMWikiToolkit`.

    Args:
        vault_path: The Obsidian vault root.
        wiki_name: The wiki plane name (default
            :data:`WIKI_KB_GRAPH_WIKI_NAME`).

    Returns:
        The wired :class:`LLMWikiToolkit`.
    """
    storage = graph_storage_dir(vault_path)
    storage.mkdir(parents=True, exist_ok=True)

    pageindex_toolkit = _build_pageindex_toolkit(storage)
    graph_toolkit = await build_graph_memory_toolkit(storage / "graphindex", tenant_id=wiki_name, agent_id=wiki_name)

    wiki_config = WikiConfig(wiki_name=wiki_name, storage_dir=storage, sync_graph=True)
    return LLMWikiToolkit(pageindex_toolkit, graph_toolkit, None, wiki_config, agent_id=wiki_name)


async def rebuild_graph_index(
    toolkit: LLMWikiToolkit,
    *,
    vault_path: str | Path,
    wiki_name: str = WIKI_KB_GRAPH_WIKI_NAME,
) -> dict[str, Any]:
    """Rebuild the derived plane from the vault (D3 — after every ingest).

    Args:
        toolkit: The :class:`LLMWikiToolkit` from
            :func:`build_wiki_kb_graph_toolkit`.
        vault_path: The Obsidian vault root.
        wiki_name: The wiki plane name.

    Returns:
        The ``ingest_obsidian_vault`` report dict. A failure here is
        never fatal to the ingest that triggered it — the derived plane
        being stale must never block ingest or a fetch decision (D3/R1);
        callers should catch and log, not abort the operation.
    """
    # Contract rule #1 (spec references, obsidian-wiki-operating-contract.md
    # line 36): "Never access Private/. Do not read, list, search, index,
    # summarize, move, modify, or traverse it." The loader's own defaults
    # only exclude .obsidian/.trash/.git — Private/ must be excluded here
    # explicitly, or every derived-plane rebuild would silently index it.
    return await toolkit.ingest_obsidian_vault(
        wiki_name, str(vault_path), incremental=True, extra_skip_patterns=["Private"]
    )
