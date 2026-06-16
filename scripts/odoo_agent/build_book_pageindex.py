#!/usr/bin/env python3
"""Offline PageIndex builder for a single Odoo documentation book PDF.

Unlike ``build_odoo_pageindex.py`` (which expects one PDF per Odoo version
under ``documentation/<ver>/``), this builder ingests **one explicit PDF** into
a named tree.  It exists to produce an informative PageIndex from the bundled
Cybrosys "Odoo Book" (``agents/odoo_agent/docs/odoo-book-by-cybrosys-technologies.pdf``)
without forcing it into the version-directory layout.

Root-cause note (FEAT-240):
    The original default model ``gemini-2.0-flash-lite`` was retired by Google
    and now returns ``404 NOT_FOUND`` on every call, which is why no PageIndex
    was ever produced.  The default here is a current lightweight model.

Prerequisites:
    - ``GOOGLE_API_KEY`` resolvable (env or navconfig).
    - Activate the venv: ``source .venv/bin/activate``

Usage:
    python scripts/odoo_agent/build_book_pageindex.py
    python scripts/odoo_agent/build_book_pageindex.py --tree-name odoo_book \
        --pdf agents/odoo_agent/docs/odoo-book-by-cybrosys-technologies.pdf
    python scripts/odoo_agent/build_book_pageindex.py --no-summaries  # faster
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from parrot.clients.google import GoogleGenAIClient
from parrot.knowledge.pageindex import PageIndexLLMAdapter, PageIndexToolkit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent

DEFAULT_STORAGE_DIR = str(_REPO_ROOT / "agents" / "odoo_agent" / "documentation")
DEFAULT_PDF = str(
    _REPO_ROOT
    / "agents"
    / "odoo_agent"
    / "docs"
    / "odoo-book-by-cybrosys-technologies.pdf"
)
# Current lightweight Gemini model (the legacy gemini-2.0-flash-lite is retired).
DEFAULT_MODEL = "gemini-2.5-flash-lite"
DEFAULT_TREE_NAME = "odoo_book"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pdf", default=DEFAULT_PDF, help="Path to the source PDF")
    parser.add_argument(
        "--tree-name", default=DEFAULT_TREE_NAME, help="Tree name to create"
    )
    parser.add_argument("--storage-dir", default=DEFAULT_STORAGE_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--force", action="store_true", help="Rebuild even if the tree exists"
    )
    parser.add_argument(
        "--no-summaries",
        action="store_true",
        help="Skip per-node LLM summaries (much faster, less informative)",
    )
    return parser.parse_args(argv)


async def build(
    pdf: str,
    tree_name: str,
    storage_dir: str,
    model: str,
    force: bool,
    with_summaries: bool,
) -> dict:
    pdf_path = Path(pdf)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    storage_path = Path(storage_dir)
    storage_path.mkdir(parents=True, exist_ok=True)

    # The GoogleGenAIClient must be entered as an async context manager BEFORE
    # the PageIndex builder fans out concurrent ``ask()`` calls. ``ask()`` (unlike
    # ``complete()``) does not auto-enter, so without this the per-loop SDK client
    # is never initialised and every concurrent call fails with
    # "GoogleGenAIClient not initialised. Use async context manager."
    async with GoogleGenAIClient(model=model) as client:
        adapter = PageIndexLLMAdapter(client=client, model=model)
        toolkit = PageIndexToolkit(adapter=adapter, storage_dir=str(storage_path))

        existing = await toolkit.list_trees()
        if tree_name in existing:
            if not force:
                logger.info(
                    "[%s] Tree already exists — skipping (use --force to rebuild).",
                    tree_name,
                )
                return {"tree": tree_name, "outcome": "skipped"}
            logger.info("[%s] --force: deleting existing tree.", tree_name)
            await toolkit.delete_tree(tree_name)

        logger.info("[%s] Creating tree (storage: %s)", tree_name, storage_path)
        await toolkit.create_tree(
            tree_name, doc_name="Odoo Book — Cybrosys Technologies"
        )

        logger.info(
            "[%s] Importing PDF: %s (summaries=%s)",
            tree_name,
            pdf_path,
            with_summaries,
        )
        result = await toolkit.import_pdf(
            tree_name=tree_name,
            pdf_path=str(pdf_path),
            with_summaries=with_summaries,
            with_doc_description=True,
        )
    node_count = len(result.get("new_node_ids", []))
    logger.info("[%s] Import complete — %d nodes created.", tree_name, node_count)
    return {
        "tree": tree_name,
        "outcome": "built",
        "nodes": node_count,
        "pages": result.get("pages"),
        "doc_description": result.get("doc_description"),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logger.info(
        "Building book PageIndex: tree=%s pdf=%s storage=%s model=%s",
        args.tree_name,
        args.pdf,
        args.storage_dir,
        args.model,
    )
    outcome = asyncio.run(
        build(
            pdf=args.pdf,
            tree_name=args.tree_name,
            storage_dir=args.storage_dir,
            model=args.model,
            force=args.force,
            with_summaries=not args.no_summaries,
        )
    )
    logger.info("Outcome: %s", outcome)
    return 0 if outcome.get("outcome") in ("built", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
