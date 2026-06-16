#!/usr/bin/env python3
"""Offline PageIndex builder for Odoo documentation reStructuredText sources.

Unlike ``build_odoo_pageindex.py`` (which expects a monolithic PDF per Odoo
version), this builder ingests the **official documentation .rst sources**
directly with ``PageIndexToolkit.import_folder``.  This is the robust path:
``make latexpdf`` on the Odoo docs repo only renders the *legal* documents
(``latex_documents`` in ``conf.py`` is scoped to ``legal/terms/...``), so it
never produces the technical/admin/developer documentation — including the
``odoo-bin`` / CLI reference (``developer/reference/cli.rst``).  The .rst tree,
by contrast, carries the full technical docs as plain UTF-8 text.

Root-cause notes (FEAT-240):
    1. The legacy default model ``gemini-2.0-flash-lite`` was retired by Google
       and now returns ``404 NOT_FOUND`` on every call — silently yielding empty
       trees.  The default here is a current lightweight model.
    2. ``PageIndexLLMAdapter`` drives the client via ``ask()``, which (unlike
       ``complete()``) does NOT auto-enter the client.  The builder fans out
       concurrent calls, so the client MUST be entered with ``async with``
       before ingestion or every concurrent call dies "not initialised".

Source repo:
    Clone produced by ``fetch_odoo_docs.sh`` lives at
    ``scripts/odoo_agent/.cache/documentation``.  Checkout the desired version
    branch (e.g. ``18.0``) before running, or pass ``--content-dir`` explicitly.

Prerequisites:
    - ``GOOGLE_API_KEY`` resolvable (env or navconfig).
    - Activate the venv: ``source .venv/bin/activate``

Usage:
    # Full version tree (checkout 18.0 in the cache repo first)
    python scripts/odoo_agent/build_rst_pageindex.py --version 18.0

    # Validation run on a single subdir (fast, cheap)
    python scripts/odoo_agent/build_rst_pageindex.py --version 18.0 \
        --subdir developer/reference --tree-name odoo_18_ref

    # Custom content dir / glob
    python scripts/odoo_agent/build_rst_pageindex.py --version 18.0 \
        --content-dir /path/to/content --glob '*.rst'
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
DEFAULT_CACHE_CONTENT = str(_SCRIPT_DIR / ".cache" / "documentation" / "content")
# Current lightweight Gemini model (the legacy gemini-2.0-flash-lite is retired).
DEFAULT_MODEL = "gemini-2.5-flash-lite"

# version string ("18.0") → tree name ("odoo_18")
def _tree_name_for(version: str) -> str:
    major = version.split(".")[0]
    return f"odoo_{major}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        default="18.0",
        help="Odoo version string (drives the default tree name, e.g. 18.0 → odoo_18)",
    )
    parser.add_argument(
        "--content-dir",
        default=DEFAULT_CACHE_CONTENT,
        help="Root of the .rst content tree (default: the fetch_odoo_docs.sh cache)",
    )
    parser.add_argument(
        "--subdir",
        default="",
        help="Optional subdirectory under content-dir to ingest (e.g. developer/reference)",
    )
    parser.add_argument(
        "--tree-name",
        default="",
        help="Override the tree name (default: odoo_<major> from --version)",
    )
    parser.add_argument("--storage-dir", default=DEFAULT_STORAGE_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--glob", default="*.rst", help="Glob pattern (default: *.rst)")
    parser.add_argument(
        "--force", action="store_true", help="Rebuild even if the tree exists"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report file count without ingesting",
    )
    return parser.parse_args(argv)


async def build(
    content_dir: str,
    tree_name: str,
    storage_dir: str,
    model: str,
    glob_pattern: str,
    version: str,
    force: bool,
) -> dict:
    """Ingest the .rst content tree into a named PageIndex tree.

    Args:
        content_dir: Root folder of the .rst sources to ingest.
        tree_name: Destination tree name.
        storage_dir: PageIndex persistence directory.
        model: Live Gemini model string.
        glob_pattern: File glob (default ``*.rst``).
        version: Odoo version string (for the doc description).
        force: Rebuild even if the tree exists.

    Returns:
        Outcome dict with node count.
    """
    content_path = Path(content_dir)
    if not content_path.is_dir():
        raise FileNotFoundError(f"Content dir not found: {content_path}")

    rst_count = len(list(content_path.rglob(glob_pattern)))
    logger.info("[%s] %d files match %r under %s", tree_name, rst_count, glob_pattern, content_path)
    if rst_count == 0:
        return {"tree": tree_name, "outcome": "no_files"}

    storage_path = Path(storage_dir)
    storage_path.mkdir(parents=True, exist_ok=True)

    # Enter the client as an async context manager BEFORE concurrent ingestion —
    # ask() does not auto-enter; without this every concurrent call fails with
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
            tree_name, doc_name=f"Odoo {version} Documentation (.rst sources)"
        )

        logger.info("[%s] Importing folder: %s (glob=%s)", tree_name, content_path, glob_pattern)
        result = await toolkit.import_folder(
            tree_name=tree_name,
            folder_path=str(content_path),
            recursive=True,
            glob_pattern=glob_pattern,
        )

    node_count = len(result.get("new_node_ids", []))
    logger.info("[%s] Import complete — %d nodes created.", tree_name, node_count)
    return {"tree": tree_name, "outcome": "built", "nodes": node_count}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    content_dir = args.content_dir
    if args.subdir:
        content_dir = str(Path(content_dir) / args.subdir)

    tree_name = args.tree_name or _tree_name_for(args.version)

    logger.info(
        "Building .rst PageIndex: tree=%s version=%s content=%s glob=%s model=%s",
        tree_name,
        args.version,
        content_dir,
        args.glob,
        args.model,
    )

    if args.dry_run:
        cp = Path(content_dir)
        n = len(list(cp.rglob(args.glob))) if cp.is_dir() else 0
        logger.info("DRY RUN — %d files would be ingested into tree %s", n, tree_name)
        return 0

    outcome = asyncio.run(
        build(
            content_dir=content_dir,
            tree_name=tree_name,
            storage_dir=args.storage_dir,
            model=args.model,
            glob_pattern=args.glob,
            version=args.version,
            force=args.force,
        )
    )
    logger.info("Outcome: %s", outcome)
    return 0 if outcome.get("outcome") in ("built", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
