"""Standalone probe for WebScrapingLoader → PgVectorStore → retrieval.

End-to-end smoke test that does NOT require restarting the aiohttp server.
Mirrors what the VectorStoreHandler does when POST /api/v1/ai/stores receives
a URL payload, but in a single-process script that prints diagnostics at
every stage.

Pipeline
--------
1. Scrape https://www.att.com/prepaid/plans/ via WebScrapingLoader with
   content_extraction="markdown" (handler default). Prints per-chunk stats.
2. Pre-flight check the target table's embedding column dimension against
   the probe's configured embedding model. On mismatch: either reset the
   table (with PROBE_RESET_TABLE=1) or abort with a clear message.
3. Instantiate PgVectorStore and add_documents().
4. similarity_search for a phrase known to exist on the page and print
   the top matches with distance + preview.

Run
---
    source .venv/bin/activate
    python artifacts/probe_webscraping_ingest.py

Environment variables
---------------------
PROBE_EMBEDDING_MODEL
    HuggingFace model name. Default: sentence-transformers/all-mpnet-base-v2
    (768 dim). Known models with auto-detected dimensions:
      - sentence-transformers/all-mpnet-base-v2        → 768
      - sentence-transformers/all-MiniLM-L6-v2         → 384
      - thenlper/gte-base                              → 768
      - intfloat/e5-large-v2                           → 1024
      - intfloat/multilingual-e5-large                 → 1024
    Any other model: pass PROBE_EMBEDDING_DIM too.

PROBE_EMBEDDING_DIM
    Override dimension when the model isn't in the known table.

PROBE_RESET_TABLE
    If set to 1/true/yes, the probe DROPs and recreates the target table
    before inserting. Required when the existing column dim doesn't match
    the probe's model. OFF by default to avoid accidental data loss.

PROBE_TABLE, PROBE_SCHEMA
    Override target table (default: att.concierge).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import textwrap
from typing import List, Optional

from sqlalchemy import text as sql_text

from parrot_loaders.webscraping import WebScrapingLoader
from parrot.stores.postgres import PgVectorStore
from parrot.stores.models import Document, SearchResult


# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

KNOWN_MODEL_DIMS: dict[str, int] = {
    "sentence-transformers/all-mpnet-base-v2": 768,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "sentence-transformers/all-MiniLM-L12-v2": 384,
    "thenlper/gte-base": 768,
    "thenlper/gte-small": 384,
    "thenlper/gte-large": 1024,
    "intfloat/e5-base-v2": 768,
    "intfloat/e5-large-v2": 1024,
    "intfloat/multilingual-e5-large": 1024,
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
}

EMBEDDING_MODEL_NAME = os.environ.get(
    "PROBE_EMBEDDING_MODEL",
    "sentence-transformers/all-mpnet-base-v2",
)
_dim_env = os.environ.get("PROBE_EMBEDDING_DIM")
if _dim_env:
    EMBEDDING_DIM = int(_dim_env)
else:
    EMBEDDING_DIM = KNOWN_MODEL_DIMS.get(EMBEDDING_MODEL_NAME)
    if EMBEDDING_DIM is None:
        raise SystemExit(
            f"Unknown embedding model {EMBEDDING_MODEL_NAME!r}. "
            f"Set PROBE_EMBEDDING_DIM=<int> to override, or use one of: "
            f"{sorted(KNOWN_MODEL_DIMS)}"
        )

EMBEDDING_CONFIG = {
    "model": EMBEDDING_MODEL_NAME,
    "model_type": "huggingface",
}

RESET_TABLE = os.environ.get("PROBE_RESET_TABLE", "").lower() in (
    "1", "true", "yes", "y",
)

TARGET_URL = "https://www.att.com/prepaid/plans/"
SCHEMA = os.environ.get("PROBE_SCHEMA", "att")
TABLE = os.environ.get("PROBE_TABLE", "concierge")
QUERY = "phone for Order now"


# ──────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s :: %(message)s",
    datefmt="%H:%M:%S",
)
for noisy in (
    "trafilatura",
    "urllib3",
    "selenium",
    "asyncio",
    "sqlalchemy.engine",
    "faker.factory",
    "WDM",
    "hpack",
    "httpcore",
):
    logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("probe")


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _preview(text: str, n: int = 240) -> str:
    """Return a single-line preview of text, truncated at n chars."""
    compact = " ".join((text or "").split())
    if len(compact) <= n:
        return compact
    return compact[:n] + "…"


def _print_chunk_stats(documents: List[Document]) -> None:
    """Print a per-chunk summary to stdout."""
    print()
    print("=" * 78)
    print(f"CHUNK STATS — {len(documents)} documents returned by loader.load()")
    print("=" * 78)

    if not documents:
        print("  (no documents — something went wrong in the loader)")
        return

    kinds: dict[str, int] = {}
    for d in documents:
        ck = d.metadata.get("content_kind", "<unset>")
        kinds[ck] = kinds.get(ck, 0) + 1
    print(f"  content_kind distribution: {kinds}")
    print()

    total_chars = 0
    for i, d in enumerate(documents):
        chars = len(d.page_content or "")
        total_chars += chars
        token_count = d.metadata.get("token_count", "?")
        ck = d.metadata.get("content_kind", "<unset>")
        splitter = d.metadata.get("splitter_type", "<unset>")
        print(
            f"  [{i:02d}] kind={ck:<20} splitter={splitter:<24} "
            f"tokens={token_count} chars={chars}"
        )
        print(f"       preview: {_preview(d.page_content, 140)}")
    print()
    print(f"  TOTAL CHARS across all chunks: {total_chars}")


async def _detect_existing_column_dim(
    store: PgVectorStore,
    schema: str,
    table: str,
) -> Optional[int]:
    """Return the embedding column's pgvector dimension, or None if the
    table doesn't exist yet.

    Reads pg_attribute to extract the Vector(N) atttypmod. The column is
    assumed to be named 'embedding'.
    """
    async with store.session() as session:
        # Does the table exist?
        exists_stmt = sql_text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM information_schema.tables "
            "  WHERE table_schema = :schema AND table_name = :table"
            ")"
        )
        exists = (await session.execute(
            exists_stmt, {"schema": schema, "table": table}
        )).scalar()
        if not exists:
            return None

        # Column dimension: format_type returns e.g. "vector(768)".
        dim_stmt = sql_text(
            "SELECT format_type(a.atttypid, a.atttypmod) "
            "FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :schema "
            "  AND c.relname = :table "
            "  AND a.attname = 'embedding' "
            "  AND a.attnum > 0"
        )
        row = (await session.execute(
            dim_stmt, {"schema": schema, "table": table}
        )).scalar()
        if not row:
            return None
        # row is e.g. 'vector(768)' or 'USER-DEFINED'
        if "(" in row and ")" in row:
            try:
                return int(row.split("(", 1)[1].rstrip(")"))
            except ValueError:
                return None
        return None


async def _drop_table(store: PgVectorStore, schema: str, table: str) -> None:
    """DROP the target table so the probe can recreate it on the next
    add_documents() call (PgVectorStore auto-creates via metadata.create_all).
    """
    log.warning("PROBE_RESET_TABLE enabled — dropping %s.%s", schema, table)
    async with store.session() as session:
        await session.execute(sql_text(f'DROP TABLE IF EXISTS "{schema}"."{table}" CASCADE'))


async def _row_count(store: PgVectorStore, schema: str, table: str) -> int:
    """Return SELECT COUNT(*) for the target table, or -1 if unreachable."""
    try:
        async with store.session() as session:
            result = await session.execute(
                sql_text(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
            )
            return result.scalar() or 0
    except Exception as exc:  # noqa: BLE001
        log.warning("_row_count failed: %s", exc)
        return -1


async def _sample_embedding_info(
    store: PgVectorStore,
    schema: str,
    table: str,
) -> None:
    """Fetch one row and print the raw embedding's actual length for sanity."""
    try:
        async with store.session() as session:
            result = await session.execute(
                sql_text(
                    f'SELECT id, vector_dims(embedding) AS dim, '
                    f"substring(document, 1, 80) AS preview "
                    f'FROM "{schema}"."{table}" LIMIT 1'
                )
            )
            row = result.fetchone()
            if row is None:
                log.warning("Sample row: (table empty)")
                return
            log.info(
                "Sample row: id=%s vector_dims=%s preview=%r",
                row[0], row[1], row[2],
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("_sample_embedding_info failed: %s", exc)


# ──────────────────────────────────────────────────────────────────────
# Stages
# ──────────────────────────────────────────────────────────────────────

async def stage_load() -> List[Document]:
    """Run WebScrapingLoader and return the chunked documents."""
    log.info("Stage 1/3 — Scrape + chunk: %s", TARGET_URL)

    loader = WebScrapingLoader(
        source=TARGET_URL,
        content_extraction="markdown",
        parse_videos=False,
        parse_navs=False,
        parse_tables=True,
        headless=True,
    )
    documents = await loader.load()
    _print_chunk_stats(documents)
    return documents


async def stage_store(documents: List[Document]) -> PgVectorStore:
    """Initialise PgVectorStore, verify dim, and insert the documents."""
    log.info(
        "Stage 2/3 — Init PgVectorStore (model=%s, dim=%d)",
        EMBEDDING_MODEL_NAME, EMBEDDING_DIM,
    )

    store = PgVectorStore(
        table=TABLE,
        schema=SCHEMA,
        embedding_model=EMBEDDING_CONFIG,
        dimension=EMBEDDING_DIM,  # explicit — store defaults to 384 otherwise
    )
    await store.connection()

    # Pre-flight: check the table's current column dim.
    existing_dim = await _detect_existing_column_dim(store, SCHEMA, TABLE)
    if existing_dim is None:
        log.info(
            "Target %s.%s does not exist yet — it will be created at dim=%d",
            SCHEMA, TABLE, EMBEDDING_DIM,
        )
    elif existing_dim != EMBEDDING_DIM:
        log.warning(
            "Dimension mismatch: %s.%s has vector(%d), probe model needs %d",
            SCHEMA, TABLE, existing_dim, EMBEDDING_DIM,
        )
        if not RESET_TABLE:
            raise RuntimeError(
                f"Cannot ingest: table {SCHEMA}.{TABLE} is vector({existing_dim}) "
                f"but probe model {EMBEDDING_MODEL_NAME} produces {EMBEDDING_DIM}-dim "
                f"vectors. Options:\n"
                f"  1) Rerun with PROBE_RESET_TABLE=1 to DROP and recreate the table.\n"
                f"  2) Switch the probe model to one with dim={existing_dim} via "
                f"PROBE_EMBEDDING_MODEL=... (see KNOWN_MODEL_DIMS in this script).\n"
                f"  3) Use a scratch table via PROBE_TABLE=concierge_probe."
            )
        await _drop_table(store, SCHEMA, TABLE)
        # Force the store to re-define the ORM on the next call by
        # clearing the cache entry keyed by fq_table_name.
        fq = f"{SCHEMA}.{TABLE}"
        store._embedding_store_cache.pop(fq, None)
        store.embedding_store = None
    else:
        log.info(
            "Target %s.%s already at matching dim=%d ✓",
            SCHEMA, TABLE, existing_dim,
        )

    if not documents:
        log.warning("No documents to insert — skipping add_documents().")
        return store

    pre_count = await _row_count(store, SCHEMA, TABLE)
    log.info("Pre-insert row count in %s.%s = %d", SCHEMA, TABLE, pre_count)

    try:
        await store.add_documents(
            documents=documents,
            table=TABLE,
            schema=SCHEMA,
        )
        log.info(
            "Inserted %d document(s) into %s.%s",
            len(documents), SCHEMA, TABLE,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("add_documents() failed: %s", exc)
        raise

    post_count = await _row_count(store, SCHEMA, TABLE)
    log.info("Post-insert row count in %s.%s = %d", SCHEMA, TABLE, post_count)
    if post_count == pre_count:
        log.error(
            "Row count did not grow after add_documents() — insert was NOT "
            "committed (transaction issue). similarity_search will return "
            "zero rows."
        )
    await _sample_embedding_info(store, SCHEMA, TABLE)
    return store


async def _raw_similarity_probe(
    store: PgVectorStore,
    query: str,
    schema: str,
    table: str,
) -> None:
    """Run a staircase of progressively complex SQL probes to isolate where
    ``similarity_search()`` is losing rows.

    Stages:
        0. SELECT * LIMIT 5 — does the table return ANY rows?
        1. SELECT vector_dims, embedding IS NULL — are embeddings valid?
        2. SELECT embedding <=> inline-literal — does pgvector compute distances?
        3. SELECT embedding <=> :q::vector (SQLAlchemy bind) — does the bind path work?
    """
    # ── Pre: embed query ──────────────────────────────────────────────
    query_vec = await store._embed_.embed_query(query)
    vec_literal = "[" + ",".join(f"{x:.6f}" for x in query_vec) + "]"
    log.info(
        "Raw probe — query_vec dim=%d first5=%s",
        len(query_vec),
        [round(x, 4) for x in list(query_vec)[:5]],
    )

    tbl = f'"{schema}"."{table}"'

    async with store.session() as session:
        # ── Stage 0: does the table return rows at all? ───────────────
        print()
        print("-" * 78)
        print("STAGE 0 — bare SELECT (no vector ops)")
        print("-" * 78)
        try:
            rows0 = (await session.execute(
                sql_text(f'SELECT id, substring(document, 1, 80) FROM {tbl} LIMIT 5')
            )).fetchall()
            print(f"  returned {len(rows0)} rows")
            for r in rows0:
                print(f"    id={r[0]}  preview={r[1]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}")

        # ── Stage 1: embedding integrity ──────────────────────────────
        print()
        print("-" * 78)
        print("STAGE 1 — embedding column integrity")
        print("-" * 78)
        try:
            rows1 = (await session.execute(sql_text(
                f'SELECT id, '
                f'  (embedding IS NULL) AS is_null, '
                f'  vector_dims(embedding) AS dim '
                f'FROM {tbl} LIMIT 5'
            ))).fetchall()
            print(f"  returned {len(rows1)} rows")
            for r in rows1:
                print(f"    id={r[0]}  is_null={r[1]}  dim={r[2]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}")

        # ── Stage 2: pgvector distance with INLINE literal ────────────
        print()
        print("-" * 78)
        print("STAGE 2 — distance with INLINE vector literal (no bind)")
        print("-" * 78)
        # Inline the vector into the SQL string. NOT safe for production
        # but fine for a probe — isolates the bind-parameter path.
        try:
            inline_sql = sql_text(
                f"SELECT id, substring(document, 1, 80) AS preview, "
                f"embedding <=> '{vec_literal}'::vector AS distance "
                f"FROM {tbl} ORDER BY distance ASC LIMIT 5"
            )
            rows2 = (await session.execute(inline_sql)).fetchall()
            print(f"  returned {len(rows2)} rows")
            for i, r in enumerate(rows2):
                print(f"    #{i + 1} distance={r[2]:.4f} id={r[0]}")
                print(f"        preview={r[1]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}")

        # ── Stage 3: distance with bind parameter ─────────────────────
        print()
        print("-" * 78)
        print("STAGE 3 — distance with :q bind parameter + CAST")
        print("-" * 78)
        try:
            bind_sql = sql_text(
                f'SELECT id, substring(document, 1, 80) AS preview, '
                f'embedding <=> CAST(:q AS vector) AS distance '
                f'FROM {tbl} ORDER BY distance ASC LIMIT 5'
            )
            rows3 = (await session.execute(bind_sql, {"q": vec_literal})).fetchall()
            print(f"  returned {len(rows3)} rows")
            for i, r in enumerate(rows3):
                print(f"    #{i + 1} distance={r[2]:.4f} id={r[0]}")
                print(f"        preview={r[1]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}")


async def stage_retrieve(store: PgVectorStore) -> List[SearchResult]:
    """Run a similarity_search and print the top-k results."""
    log.info("Stage 3/3 — similarity_search(query=%r)", QUERY)

    pre_search_count = await _row_count(store, SCHEMA, TABLE)
    log.info("Row count seen by retrieval session = %d", pre_search_count)
    if pre_search_count == 0:
        log.warning(
            "Table is empty from the retrieval session's POV — "
            "the insert transaction did not persist."
        )

    # Diagnostic: run the bare SQL equivalent first.
    await _raw_similarity_probe(store, QUERY, SCHEMA, TABLE)

    results = await store.similarity_search(
        query=QUERY,
        table=TABLE,
        schema=SCHEMA,
        limit=5,
    )

    print()
    print("=" * 78)
    print(f"RETRIEVAL — top {len(results)} for query: {QUERY!r}")
    print("=" * 78)
    if not results:
        print("  (no results — the ingest may have failed or embeddings are off)")
        return results

    for rank, r in enumerate(results, start=1):
        print(
            f"  #{rank}  distance={r.score:.4f}  "
            f"kind={r.metadata.get('content_kind', '<unset>')}"
        )
        print(f"        id={r.id}")
        print(
            "        preview: "
            + textwrap.shorten(" ".join((r.content or "").split()), width=240)
        )
        print()
    return results


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

async def main() -> int:
    log.info(
        "Probe config: model=%s dim=%d target=%s.%s reset=%s",
        EMBEDDING_MODEL_NAME, EMBEDDING_DIM, SCHEMA, TABLE, RESET_TABLE,
    )

    try:
        documents = await stage_load()
    except Exception as exc:  # noqa: BLE001
        log.exception("Stage 1 failed: %s", exc)
        return 2

    store = None
    try:
        store = await stage_store(documents)
        await stage_retrieve(store)
    except Exception as exc:  # noqa: BLE001
        log.exception("Stage 2/3 failed: %s", exc)
        return 3
    finally:
        if store is not None:
            try:
                await store.disconnect()
            except Exception as exc:  # noqa: BLE001
                log.warning("Error disconnecting store: %s", exc)

    log.info("Probe finished OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
