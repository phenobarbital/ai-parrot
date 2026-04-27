"""In-table parent searcher for pgvector stores.

This module implements :class:`InTableParentSearcher`, the default
``AbstractParentSearcher`` for deployments that store both chunks and their
parent documents in the same vector table (postgres / pgvector).

**Implementation approach (Approach A — direct connection access)**:

The searcher uses the store's ``session()`` async context manager and issues
a single parameterised SQL query per ``fetch()`` call.  This avoids the N+1
pattern that would arise from fetching each parent individually.

The SQL semantics are:

.. code-block:: sql

    SELECT <id_col>, <doc_col>, <meta_col>
    FROM <schema>.<table>
    WHERE <id_col> = ANY(:ids)
      AND (
        (<meta_col>->>'is_full_document')::boolean = true
        OR <meta_col>->>'document_type' = 'parent_chunk'
      )

This single round trip covers both 2-level parents (``is_full_document=True``)
and 3-level intermediate parent chunks (``document_type='parent_chunk'``).
"""
import logging
import re
from typing import Any, Dict, List

from sqlalchemy import text

from parrot.stores.abstract import AbstractStore
from parrot.stores.models import Document
from parrot.stores.parents.abstract import AbstractParentSearcher

# Allowlist for SQL identifier characters — prevents SQL injection via
# store attribute values interpolated into the query template.
_SAFE_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _safe_identifier(name: str, value: str) -> str:
    """Validate that *value* is a safe SQL identifier.

    Args:
        name: Human-readable label used in the error message.
        value: Identifier string to validate (table name, column name, etc.).

    Returns:
        The original *value* if it matches ``[a-zA-Z_][a-zA-Z0-9_]*``.

    Raises:
        ValueError: If *value* contains characters that could allow SQL injection.
    """
    if not _SAFE_IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Unsafe SQL identifier for {name!r}: {value!r}. "
            "Identifiers must match [a-zA-Z_][a-zA-Z0-9_]*."
        )
    return value


class InTableParentSearcher(AbstractParentSearcher):
    """Fetch parents from the same vector table by metadata filter.

    Default implementation for postgres / pgvector.  Issues a single SQL
    query per :meth:`fetch` call regardless of how many parent IDs are
    requested — no N+1.

    **Implementation**: Approach A (direct connection access).  Uses the
    store's ``session()`` async context manager to issue a raw parameterised
    SELECT.  The parent filter covers both legacy ``is_full_document=True``
    parents and the new ``document_type='parent_chunk'`` intermediate
    parents introduced by FEAT-128.

    Args:
        store: An :class:`~parrot.stores.abstract.AbstractStore` instance.
            The store MUST expose a ``session()`` async context manager
            (as implemented by :class:`~parrot.stores.postgres.PgVectorStore`).
    """

    def __init__(self, store: AbstractStore) -> None:
        self.store = store
        self.logger = logging.getLogger(__name__)

    async def fetch(self, parent_ids: List[str]) -> Dict[str, Document]:
        """Fetch parent documents by ID in a single SQL round trip.

        Args:
            parent_ids: List of parent document IDs to retrieve.  An empty
                list returns an empty dict immediately (no DB call).

        Returns:
            Mapping of ``{parent_document_id: Document}`` containing only
            rows whose metadata marks them as parents
            (``is_full_document=True`` OR ``document_type='parent_chunk'``).
            IDs that are not found or are not parent rows are simply absent.

        Raises:
            Exception: Only for infrastructure failures (DB connection
                errors, SQL errors).  Individual misses are silently omitted.
        """
        if not parent_ids:
            return {}

        # Resolve table-level configuration from the store (duck-typed).
        table = getattr(self.store, 'table_name', None)
        schema = getattr(self.store, 'schema', 'public') or 'public'
        id_col = getattr(self.store, '_id_column', 'id')
        doc_col = getattr(self.store, '_document_column', 'document')
        # Read metadata column name from the store; fall back to the pgvector default.
        meta_col = getattr(self.store, '_metadata_column', 'cmetadata') or 'cmetadata'

        if not table:
            self.logger.warning(
                "InTableParentSearcher.fetch: store has no table_name configured; "
                "cannot fetch parents.  Returning empty dict."
            )
            return {}

        # Validate all identifier values before interpolating them into SQL.
        # The :ids bind parameter is safe; structural identifiers are not.
        try:
            table = _safe_identifier('table_name', table)
            schema = _safe_identifier('schema', schema)
            id_col = _safe_identifier('id_column', id_col)
            doc_col = _safe_identifier('document_column', doc_col)
            meta_col = _safe_identifier('metadata_column', meta_col)
        except ValueError:
            self.logger.exception(
                "InTableParentSearcher.fetch: store configuration contains an "
                "unsafe SQL identifier — aborting fetch to prevent injection."
            )
            return {}

        # Build parameterised query.  The ANY(:ids) clause ensures a single
        # round trip regardless of input size.
        sql = text(
            f"""
            SELECT {id_col}, {doc_col}, {meta_col}
            FROM {schema}.{table}
            WHERE {id_col} = ANY(:ids)
              AND (
                ({meta_col}->>'is_full_document')::boolean = true
                OR {meta_col}->>'document_type' = 'parent_chunk'
              )
            """
        )

        results: Dict[str, Document] = {}

        # Ensure DB connection is established before using session().
        # Default is False: assume disconnected if the attribute is absent.
        if not getattr(self.store, '_connected', False):
            await self.store.connection()  # type: ignore[attr-defined]

        async with self.store.session() as session:  # type: ignore[attr-defined]
            rows = await session.execute(sql, {'ids': parent_ids})
            for row in rows.fetchall():
                doc_id: str = row[0]
                content: str = row[1] or ''
                metadata: Dict[str, Any] = row[2] or {}
                results[doc_id] = Document(
                    page_content=content,
                    metadata=metadata,
                )

        self.logger.debug(
            "InTableParentSearcher.fetch: requested=%d, found=%d",
            len(parent_ids),
            len(results),
        )
        return results
