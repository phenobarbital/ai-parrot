"""Provision a PgVector table for a RAG agent.

Builders call ``provision_vector_store`` after the LLM has chosen a table
name, schema and embedding dimension. The function creates the table via
``PgVectorStore.create_embedding_table`` and returns a ``StoreConfig`` block
ready to embed in the resulting ``AgentDefinition``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from parrot.tools.decorators import tool


async def provision_vector_store(
    table: str,
    *,
    schema: str = "public",
    dimension: int = 768,
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2",
    extra_columns: Optional[List[str]] = None,
    dsn: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a PgVector table and return a ``StoreConfig``-shaped dict.

    Args:
        table: Target table name.
        schema: Postgres schema (defaults to ``public``).
        dimension: Embedding vector dimension. Match it to ``embedding_model``.
        embedding_model: HuggingFace / sentence-transformers identifier.
        extra_columns: Additional non-vector columns to add to the table.
        dsn: Optional Postgres DSN override; falls back to PgVector defaults
            (driven by env vars: ``PG_HOST``, ``PG_USER``, …).

    Returns:
        Dict with ``provider``, ``table``, ``schema``, ``dimension``,
        ``embedding_model`` ready to use as the ``vector_store`` block of an
        ``AgentDefinition``.
    """
    from parrot.stores.postgres import PgVectorStore  # local import: heavy deps

    store_kwargs: Dict[str, Any] = {
        "table": table,
        "schema": schema,
        "embedding_model": embedding_model,
        "auto_initialize": True,
    }
    if dsn:
        store_kwargs["dsn"] = dsn

    store = PgVectorStore(**store_kwargs)
    await store.create_embedding_table(
        table=table,
        columns=list(extra_columns or []),
        schema=schema,
        dimension=dimension,
    )

    return {
        "provider": "pgvector",
        "table": table,
        "schema": schema,
        "dimension": dimension,
        "embedding_model": embedding_model,
    }


@tool(name="provision_vector_store",
      description="Create a PgVector table for a RAG agent. Call this when the "
                  "user wants a RAG bot and after you have picked a table name "
                  "and embedding model. Returns a vector_store block to embed "
                  "in the AgentDefinition.")
async def _provision_vector_store_tool(
    table: str,
    schema: str = "public",
    dimension: int = 768,
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2",
) -> Dict[str, Any]:
    return await provision_vector_store(
        table=table,
        schema=schema,
        dimension=dimension,
        embedding_model=embedding_model,
    )
