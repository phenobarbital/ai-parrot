"""Build the real PageIndex tree + FAISS index from the markdown sources.

Run once before starting the orchestrator to enable the real retrieval
backends. Without running this script the example still works — the
``pageindex_lookup`` and ``handbook_search`` tools fall back to a
substring scan over the markdown files.

Usage:
    python -m examples.orchestrator.knowledge.ingest [--reset]

Requires:
    - GOOGLE_API_KEY (for PageIndex's LLM walk).
    - sentence-transformers (already a dependency of FAISSStore).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from examples.orchestrator.knowledge.retrieval import (
    FAISS_DIR,
    HANDBOOKS_DIR,
    MANUALS_DIR,
    PAGEINDEX_DIR,
    attach_faiss,
    attach_pageindex,
)


_LOG = logging.getLogger("orchestrator.ingest")


async def _build_pageindex() -> tuple[object, list[str], object]:
    """Build a PageIndex tree per manual; returns toolkit, tree names, client.

    The client is returned so the caller can keep it alive (as an async
    context manager) for the lifetime of the orchestrator — the toolkit
    holds a reference to it but does not own its session lifecycle.
    """
    from parrot.clients.google.client import GoogleGenAIClient
    from parrot.models.google import GoogleModel
    from parrot.knowledge.pageindex import PageIndexLLMAdapter, PageIndexToolkit

    PAGEINDEX_DIR.mkdir(parents=True, exist_ok=True)
    heavy = GoogleModel.GEMINI_3_FLASH_PREVIEW.value
    light = GoogleModel.GEMINI_3_FLASH_LITE_PREVIEW.value

    client = GoogleGenAIClient()
    async with client:
        adapter = PageIndexLLMAdapter(client=client, model=heavy)
        toolkit = PageIndexToolkit(
            adapter=adapter,
            storage_dir=PAGEINDEX_DIR,
            lightweight_model=light,
        )

        tree_names: list[str] = []
        existing = set(await toolkit.list_trees())
        for md_path in sorted(MANUALS_DIR.glob("*.md")):
            tree_name = md_path.stem
            if tree_name in existing:
                _LOG.info("Tree %r already exists — skipping.", tree_name)
                tree_names.append(tree_name)
                continue
            _LOG.info("Ingesting %s → tree %r", md_path.name, tree_name)
            await toolkit.create_tree(tree_name=tree_name, doc_name=tree_name)
            await toolkit.insert_markdown(
                tree_name=tree_name,
                markdown=md_path.read_text(encoding="utf-8"),
                doc_name=tree_name,
            )
            tree_names.append(tree_name)

    return toolkit, tree_names, client


async def _build_faiss() -> object:
    """Build an in-memory FAISS index over the handbooks."""
    from parrot.stores.faiss_store import FAISSStore
    from parrot.stores.models import Document

    FAISS_DIR.mkdir(parents=True, exist_ok=True)
    store = FAISSStore(collection_name="handbooks")

    from examples.orchestrator.knowledge.retrieval import split_into_sections

    documents: list[Document] = []
    for md_path in sorted(HANDBOOKS_DIR.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        # Chunk by ## headings, same as the fallback scanner.
        for heading, body in split_into_sections(text):
            if not body.strip():
                continue
            documents.append(Document(
                page_content=f"{heading}\n\n{body}",
                metadata={"source": md_path.name, "section": heading},
            ))

    if documents:
        async with store as opened:
            await opened.add_documents(documents)
        _LOG.info(
            "FAISS index built — %d chunks across %d handbook(s).",
            len(documents),
            sum(1 for _ in HANDBOOKS_DIR.glob("*.md")),
        )
    return store


async def build_all(reset: bool = False) -> None:
    """Build both indexes and attach them to the retrieval module."""
    if reset:
        for d in (PAGEINDEX_DIR, FAISS_DIR):
            if d.exists():
                for child in d.rglob("*"):
                    if child.is_file():
                        child.unlink()

    toolkit, tree_names, client = await _build_pageindex()
    attach_pageindex(toolkit, tree_names, client)

    faiss = await _build_faiss()
    attach_faiss(faiss)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true",
        help="Wipe and rebuild the indexes from scratch."
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable debug logging."
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    try:
        asyncio.run(build_all(reset=args.reset))
    except Exception as exc:
        _LOG.exception("Ingest failed: %s", exc)
        return 1
    _LOG.info("✅ Indexes ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
