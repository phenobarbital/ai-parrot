#!/usr/bin/env python
"""Recompute embeddings of an existing PgVector table using metadata-derived
contextual headers (FEAT-127).

This script re-embeds rows that were ingested *before* the
``contextual_embedding=True`` flag was enabled on the store.  It reads each
row's ``document_meta`` from the ``cmetadata`` JSONB column, applies the
same :func:`~parrot.stores.utils.contextual.build_contextual_text` helper
that the store uses at ingestion time, and updates ``embedding`` and
``cmetadata['contextual_header']`` in place.

Usage::

    python scripts/recompute_contextual_embeddings.py \\
        --dsn postgresql://user:pass@host/db \\
        --table my_collection \\
        --schema public \\
        --batch-size 200 \\
        --dry-run

Spec: FEAT-127 §8 Open Question 5 — "create the migration tooling".
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from typing import Any

from sqlalchemy import select, update

from parrot.stores.models import Document
from parrot.stores.postgres import PgVectorStore
from parrot.stores.utils.contextual import (
    DEFAULT_MAX_HEADER_TOKENS,
    DEFAULT_TEMPLATE,
    build_contextual_text,
)

logger = logging.getLogger(__name__)


async def run(args: Any) -> None:
    """Run the recompute job.

    Args:
        args: Parsed arguments from :func:`main`.
    """
    store = PgVectorStore(
        dsn=args.dsn,
        table=args.table,
        schema=args.schema,
        embedding_model=args.embedding_model,
        # Flag stays OFF on the store — we drive augmentation manually so
        # that the inherited hook is not double-applied.
        contextual_embedding=False,
    )
    await store.connection()

    template = args.template or DEFAULT_TEMPLATE
    max_header_tokens: int = args.max_header_tokens

    processed = 0
    updated = 0
    skipped = 0
    start = time.monotonic()

    # Ensure the embedding store ORM object is set up.
    store.embedding_store = store._define_collection_store(
        table=args.table,
        schema=args.schema,
        dimension=store.dimension,
        id_column=store._id_column,
    )

    async with store.session() as session:
        offset = 0
        while True:
            # Paginate with OFFSET/LIMIT — no server-side cursor needed for
            # typical collection sizes.
            rows = (
                await session.execute(
                    select(store.embedding_store)
                    .limit(args.batch_size)
                    .offset(offset)
                )
            ).scalars().all()

            if not rows:
                break

            offset += len(rows)
            new_payloads = []

            for row in rows:
                processed += 1
                if args.limit is not None and processed > args.limit:
                    break

                doc = Document(
                    page_content=getattr(row, "document", "") or "",
                    metadata=dict(getattr(row, "cmetadata", {}) or {}),
                )
                text, header = build_contextual_text(doc, template, max_header_tokens)

                if not header:
                    skipped += 1
                    logger.info("Skipped row %s (no usable document_meta)", getattr(row, "id", "?"))
                    continue

                [emb] = await store._embed_.embed_documents([text])
                new_payloads.append((
                    getattr(row, "id", None),
                    emb.tolist() if hasattr(emb, "tolist") else emb,
                    {**(getattr(row, "cmetadata", {}) or {}), "contextual_header": header},
                ))

            if not args.dry_run and new_payloads:
                for row_id, emb, cmeta in new_payloads:
                    await session.execute(
                        update(store.embedding_store)
                        .where(store.embedding_store.id == row_id)
                        .values(embedding=emb, cmetadata=cmeta)
                    )
                updated += len(new_payloads)
            elif args.dry_run and new_payloads:
                logger.info(
                    "[dry-run] Would update %d rows in this batch.", len(new_payloads)
                )
                updated += len(new_payloads)  # count for summary

            if args.limit is not None and processed >= args.limit:
                break

    duration = time.monotonic() - start
    logger.info(
        "processed=%d updated=%d skipped=%d duration=%.1fs",
        processed, updated, skipped, duration,
    )


def main() -> None:
    """CLI entry point."""
    p = argparse.ArgumentParser(
        description=(
            "Recompute PgVector embeddings using metadata-derived contextual headers "
            "(FEAT-127). Reads document_meta from cmetadata JSONB and updates "
            "embedding + cmetadata['contextual_header'] in place."
        )
    )
    p.add_argument("--dsn", required=True, help="PostgreSQL DSN (postgresql://...)")
    p.add_argument("--table", required=True, help="Table name to recompute")
    p.add_argument("--schema", default="public", help="Schema (default: public)")
    p.add_argument(
        "--embedding-model",
        default=None,
        help="Embedding model name or config JSON; defaults to parrot config.",
    )
    p.add_argument(
        "--template",
        default=None,
        help="Template string (default: parrot DEFAULT_TEMPLATE).",
    )
    p.add_argument(
        "--max-header-tokens",
        type=int,
        default=DEFAULT_MAX_HEADER_TOKENS,
        help=f"Max header tokens (default: {DEFAULT_MAX_HEADER_TOKENS})",
    )
    p.add_argument("--batch-size", type=int, default=200, help="Rows per batch")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N rows (for testing).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Read, render, and embed but do NOT write UPDATEs. "
            "Use to validate connectivity and embedding model."
        ),
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
