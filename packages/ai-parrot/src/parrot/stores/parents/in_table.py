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
from typing import Any, Dict, List

import sqlalchemy
from sqlalchemy import text

from parrot.stores.abstract import AbstractStore
from parrot.stores.models import Document
from parrot.stores.parents.abstract import AbstractParentSearcher


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
        meta_col = 'cmetadata'  # Standard pgvector metadata column name.

        if not table:
            self.logger.warning(
                "InTableParentSearcher.fetch: store has no table_name configured; "
                "cannot fetch parents.  Returning empty dict."
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
        if not getattr(self.store, '_connected', True):
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
