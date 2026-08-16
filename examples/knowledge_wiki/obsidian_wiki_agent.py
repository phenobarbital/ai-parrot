"""Obsidian vault → LLM Wiki end-to-end example (FEAT-392, Module 9).

Demonstrates the three-phase Obsidian ingestion pipeline against a real
vault directory:

1. **Phase 1 — raw ingest (no LLM)**: ``ObsidianVaultLoader`` parses the
   vault (wikilinks, embeds, frontmatter, tags, canvas files) and stores
   one PageIndex node per note.
2. **Phase 1b — graph bridge (no LLM)**: ``ObsidianGraphBridge`` imports
   the hand-curated ``[[wikilink]]`` graph into GraphIndex as
   pre-curated REFERENCES/CONTAINS edges plus tag CONCEPT nodes.
3. **Phase 2 — entity extraction (LLM, opt-in)**:
   ``WikiIngestOrchestrator.extract_entities`` runs LLM entity/concept
   extraction over the ingested pages (``--extract-entities``, needs a
   configured Google GenAI key).

Usage::

    python obsidian_wiki_agent.py /path/to/vault             # phases 1 + 1b
    python obsidian_wiki_agent.py /path/to/vault --query ml  # + BM25 query
    python obsidian_wiki_agent.py /path/to/vault --extract-entities
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import wiki  # noqa: E402  (sibling module with the toolkit builders)

from parrot.loaders.obsidian import (  # noqa: E402
    ObsidianGraphBridge,
    ObsidianVaultLoader,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("obsidian_wiki_agent")

STORE_DIR = Path(__file__).parent / "store" / "obsidian"
TREE_NAME = "obsidian-vault"
HEAVY_MODEL = "gemini-2.5-flash"
LIGHT_MODEL = "gemini-2.5-flash-lite"


def _header(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


async def run(
    vault_path: Path,
    query: str | None,
    extract_entities: bool,
    granularity: str,
) -> int:
    from parrot.knowledge.pageindex import PageIndexLLMAdapter
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
    from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
    from parrot.knowledge.wiki.models import WikiConfig
    from parrot.knowledge.wiki.sources import SourceCollectionManager

    STORE_DIR.mkdir(parents=True, exist_ok=True)

    if extract_entities:
        from parrot.clients.google.client import GoogleGenAIClient

        client_ctx = GoogleGenAIClient()
    else:

        class _NullClient:
            """Placeholder client — Phase 1/1b never call the LLM."""

        client_ctx = None

    # ------------------------------------------------------------------ #
    # Phase 1 — raw vault ingest into PageIndex (no LLM required)
    # ------------------------------------------------------------------ #
    _header("Phase 1 — raw vault ingest (no LLM)")
    if client_ctx is None:
        adapter = PageIndexLLMAdapter(client=_NullClient(), model=HEAVY_MODEL)
    else:
        await client_ctx.__aenter__()
        adapter = PageIndexLLMAdapter(client=client_ctx, model=HEAVY_MODEL)
    try:
        pi = wiki.build_pageindex_toolkit(adapter=adapter, storage_dir=STORE_DIR)
        if TREE_NAME in await pi.list_trees():
            await pi.delete_tree(TREE_NAME)

        sources = SourceCollectionManager(STORE_DIR / "sources", backend="json")
        loader = ObsidianVaultLoader(vault_path)
        report = await loader.ingest(pi, TREE_NAME, sources)
        print(
            f"notes={report.notes_processed} canvas={report.canvas_processed} "
            f"nodes={report.nodes_created} errors={len(report.errors)} "
            f"({report.duration_ms:.0f} ms)"
        )
        for error in report.errors[:5]:
            print(f"  ! {error}")

        # ---------------------------------------------------------------- #
        # Phase 1b — wikilink graph → GraphIndex (no LLM required)
        # ---------------------------------------------------------------- #
        _header("Phase 1b — graph bridge: [[wikilinks]] → GraphIndex")
        notes, canvases = await loader.discover()
        bridge = ObsidianGraphBridge(
            notes,
            canvases,
            await loader.vault.build_index(),
            vault_name=loader.vault.vault_name,
        )
        nodes, edges = bridge.build_graph()
        gi = await wiki.build_graphindex_toolkit(nodes, edges)
        print(f"graph nodes={len(nodes)} edges={len(edges)}")
        central = await gi.find_central_nodes(top_k=5)
        print("most central vault notes:")
        for row in central if isinstance(central, list) else []:
            print(f"  - {row}")

        # ---------------------------------------------------------------- #
        # Query the wiki (BM25 — still no LLM)
        # ---------------------------------------------------------------- #
        if query:
            _header(f"Query — BM25 over the vault wiki: {query!r}")
            hits = await pi.search(
                TREE_NAME, query, top_k=5, use_bm25=True, use_llm_walk=False
            )
            for hit in hits or []:
                print(f"  - {hit}")

        # ---------------------------------------------------------------- #
        # Phase 2 — LLM entity extraction (opt-in)
        # ---------------------------------------------------------------- #
        if extract_entities:
            _header(f"Phase 2 — entity extraction (granularity={granularity})")
            orchestrator = WikiIngestOrchestrator(
                pi, gi, sources, WikiBookkeeper()
            )
            config = WikiConfig(wiki_name=TREE_NAME, storage_dir=STORE_DIR)
            entity_report = await orchestrator.extract_entities(
                TREE_NAME, config, granularity=granularity
            )
            print(
                f"entities={entity_report.pages_created} "
                f"graph_nodes={entity_report.graph_nodes_created} "
                f"status={entity_report.status}"
            )
    finally:
        if client_ctx is not None:
            await client_ctx.__aexit__(None, None, None)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault", type=Path, help="Obsidian vault directory")
    parser.add_argument("--query", default=None, help="BM25 query to run")
    parser.add_argument(
        "--extract-entities",
        action="store_true",
        help="Run Phase 2 LLM entity extraction (needs Google GenAI key)",
    )
    parser.add_argument(
        "--granularity",
        default="standard",
        choices=["minimal", "standard", "fine", "custom"],
    )
    args = parser.parse_args()
    if not args.vault.is_dir():
        parser.error(f"not a directory: {args.vault}")
    return asyncio.run(
        run(args.vault, args.query, args.extract_entities, args.granularity)
    )


if __name__ == "__main__":
    raise SystemExit(main())
