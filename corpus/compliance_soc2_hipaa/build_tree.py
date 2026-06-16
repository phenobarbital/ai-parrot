"""Compliance corpus tree builder for SOC 2 + HIPAA.

Builds PageIndex trees from the downloaded compliance documents using
``PageIndexToolkit`` with dense embedding support (FEAT-237).

Usage::

    # Build all trees (requires documents in raw/):
    python -m corpus.compliance_soc2_hipaa.build_tree \\
        --storage-dir /path/to/trees \\
        --raw-dir corpus/compliance_soc2_hipaa/raw

    # Build with dense embedding index (requires sentence-transformers):
    python -m corpus.compliance_soc2_hipaa.build_tree \\
        --storage-dir /path/to/trees \\
        --embedding-model sentence-transformers/all-MiniLM-L6-v2 \\
        --use-vec-rank

Pre-requisites:
    1. Run ``python -m corpus.compliance_soc2_hipaa.fetch`` to download sources.
    2. Manually place AICPA TSC at ``raw/aicpa_tsc_2017.pdf`` if available.

Note:
    Sources marked ``redistributable: false`` (AICPA TSC) must NEVER be
    committed to public repositories.  The tree JSON built from such sources
    contains verbatim content — treat it with the same confidentiality.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger("corpus.compliance_soc2_hipaa.build_tree")

_MANIFEST_PATH = Path(__file__).parent / "manifest.yaml"
_DEFAULT_RAW_DIR = Path(__file__).parent / "raw"
_DEFAULT_STORAGE_DIR = Path(__file__).parent / "trees"

# Mapping from manifest source name to tree name used in PageIndexToolkit.
_TREE_NAMES: dict[str, str] = {
    "NIST SP 800-53 Rev 5": "nist_800_53",
    "NIST Cybersecurity Framework 2.0": "nist_csf_2_0",
    "AICPA Trust Services Criteria 2017 (with 2022 points)": "aicpa_tsc",
    "HIPAA Security Rule (45 CFR Part 164)": "hipaa_security_rule",
}


async def build_trees(
    storage_dir: Path = _DEFAULT_STORAGE_DIR,
    raw_dir: Path = _DEFAULT_RAW_DIR,
    embedding_model: Optional[str] = None,
    embedding_dimension: int = 256,
    use_vec_rank: bool = False,
    adapter=None,
) -> dict[str, str]:
    """Build PageIndex trees from downloaded compliance documents.

    Args:
        storage_dir: Directory where tree JSON files will be persisted.
        raw_dir: Directory containing downloaded source documents.
        embedding_model: Optional sentence-transformers model for dense
            indexing.  Only used when ``use_vec_rank=True``.
        embedding_dimension: Embedding vector dimension.
        use_vec_rank: Enable FEAT-237 Phase A dense ranking.
        adapter: :class:`PageIndexLLMAdapter` instance.  When ``None``,
            the function returns early with instructions to provide an adapter.

    Returns:
        Mapping of tree name → storage path.
    """
    if adapter is None:
        logger.error(
            "No LLM adapter provided.  Pass a PageIndexLLMAdapter instance "
            "via --adapter or call build_trees() directly."
        )
        return {}

    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

    storage_dir.mkdir(parents=True, exist_ok=True)
    toolkit = PageIndexToolkit(
        adapter=adapter,
        storage_dir=storage_dir,
        embedding_model=embedding_model,
        embedding_dimension=embedding_dimension,
        use_vec_rank=use_vec_rank,
    )

    from corpus.compliance_soc2_hipaa.fetch import _load_manifest  # local import
    manifest = _load_manifest(_MANIFEST_PATH)
    results: dict[str, str] = {}

    for source in manifest.get("sources", []):
        name: str = source.get("name", "")
        filename: Optional[str] = source.get("filename")
        redistributable: bool = source.get("redistributable", True)
        fmt: str = source.get("format", "pdf")

        tree_name = _TREE_NAMES.get(name)
        if not tree_name:
            logger.warning("[%s] No tree name mapping found — skip", name)
            continue

        if not redistributable:
            logger.info("[%s] Non-redistributable source — treating as internal", name)

        raw_path = raw_dir / (filename or "")
        if not raw_path.exists():
            logger.warning("[%s] Source file not found: %s — skip", name, raw_path)
            continue

        logger.info("[%s] Building tree '%s' from %s", name, tree_name, raw_path)
        try:
            if toolkit._store.exists(tree_name):
                logger.info("[%s] Tree '%s' already exists — skip", name, tree_name)
                results[tree_name] = str(storage_dir / f"{tree_name}.json")
                continue

            if fmt == "pdf":
                # Use the toolkit's import_pdf method if available.
                if hasattr(toolkit, "import_pdf"):
                    # import_pdf splices into an *existing* tree, so create
                    # the (empty) tree first — mirrors the example agent's
                    # ensure_tree() flow (create_tree → import_pdf).
                    await toolkit.create_tree(tree_name, doc_name=filename)
                    await toolkit.import_pdf(
                        tree_name=tree_name,
                        pdf_path=str(raw_path),
                    )
                else:
                    logger.error(
                        "[%s] PageIndexToolkit.import_pdf() not found. "
                        "Build manually via create_tree + insert_page.",
                        name,
                    )
                    continue
            elif fmt == "json":
                logger.info("[%s] JSON format — custom import required", name)
            else:
                logger.warning("[%s] Unsupported format: %s", name, fmt)
                continue
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] Failed to build tree: %s", name, exc)
            continue

        tree_path = storage_dir / f"{tree_name}.json"
        results[tree_name] = str(tree_path)
        logger.info("[%s] Tree '%s' built at %s", name, tree_name, tree_path)

    return results


def main() -> None:
    """Entry point for ``python -m corpus.compliance_soc2_hipaa.build_tree``."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(
        description="Build PageIndex trees from compliance corpus"
    )
    parser.add_argument(
        "--storage-dir",
        default=str(_DEFAULT_STORAGE_DIR),
        help="Directory to store tree JSON files",
    )
    parser.add_argument(
        "--raw-dir",
        default=str(_DEFAULT_RAW_DIR),
        help="Directory containing downloaded source documents",
    )
    parser.add_argument(
        "--embedding-model",
        default=None,
        help="Sentence-Transformers model for dense embedding",
    )
    parser.add_argument(
        "--embedding-dimension",
        type=int,
        default=256,
        help="Embedding vector dimension (default: 256)",
    )
    parser.add_argument(
        "--use-vec-rank",
        action="store_true",
        help="Enable FEAT-237 Phase A dense cosine ranking",
    )
    args = parser.parse_args()
    print(
        "Note: build_tree.py requires a PageIndexLLMAdapter. "
        "Import and call build_trees() directly from your agent code."
    )
    print(f"  storage_dir: {args.storage_dir}")
    print(f"  raw_dir:     {args.raw_dir}")
    print(f"  embedding:   {args.embedding_model} (dim={args.embedding_dimension})")


if __name__ == "__main__":
    main()
