"""DatabaseLoader — Load database table rows as RAG Documents via AsyncDB."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union
from pathlib import PurePath

import yaml
from asyncdb import AsyncDB

from parrot.loaders import AbstractLoader
from parrot.stores.models import Document
from parrot.conf import default_dsn


DEFAULT_EXCLUDE_COLUMNS = frozenset({'created_at', 'updated_at', 'inserted_at'})


class DatabaseLoader(AbstractLoader):
    """Load rows from a database table as RAG Documents.

    Each row becomes a single Document whose ``page_content`` is a YAML or JSON
    representation of the row (minus excluded columns), and whose ``metadata``
    carries table, schema, row index, source, and driver information.

    Args:
        table: Table name (required).
        schema: Database schema. Defaults to ``'public'``.
        driver: AsyncDB driver name. Defaults to ``'pg'`` (PostgreSQL).
        dsn: Connection DSN string. Defaults to ``parrot.conf.default_dsn``.
        params: Alternative connection params dict (mutually exclusive with dsn).
        where: Optional SQL WHERE clause (without the ``WHERE`` keyword).
        content_format: Serialization format for ``page_content``.
            ``'yaml'`` (default) or ``'json'``.
        exclude_columns: Column names to drop from content.
            Defaults to ``['created_at', 'updated_at', 'inserted_at']``.
        **kwargs: Passed to ``AbstractLoader.__init__``.

    Example::

        loader = DatabaseLoader(table='plans', schema='att')
        docs = await loader.load()

        loader = DatabaseLoader(
            table='plans',
            schema='att',
            where="plan_name NOT LIKE '%Online Only%'",
            content_format='json',
        )
        docs = await loader.load()
    """

    def __init__(
        self,
        table: str,
        *,
        schema: str = 'public',
        driver: str = 'pg',
        dsn: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        where: Optional[str] = None,
        content_format: str = 'yaml',
        exclude_columns: Optional[List[str]] = None,
        source_type: str = 'database',
        **kwargs,
    ) -> None:
        super().__init__(source=None, source_type=source_type, **kwargs)
        self.table = table
        self.schema = schema
        self.driver = driver
        self.dsn = dsn or default_dsn
        self.params = params
        self.where = where
        if content_format not in ('yaml', 'json'):
            raise ValueError(
                f"content_format must be 'yaml' or 'json', got {content_format!r}"
            )
        self.content_format = content_format
        if exclude_columns is not None:
            self.exclude_columns: frozenset[str] = frozenset(exclude_columns)
        else:
            self.exclude_columns = DEFAULT_EXCLUDE_COLUMNS

    # -- internal helpers --------------------------------------------------

    def _build_query(self) -> str:
        """Build the SELECT query from table, schema, and optional WHERE."""
        query = f'SELECT * FROM {self.schema}.{self.table}'
        if self.where:
            query += f' WHERE {self.where}'
        return query

    def _filter_columns(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Remove excluded columns from a row dict."""
        return {k: v for k, v in row.items() if k not in self.exclude_columns}

    def _serialize_row(self, row: Dict[str, Any]) -> str:
        """Serialize a row dict to YAML or JSON string.

        In YAML mode, list values are expanded as bullet lists and None renders
        as ``null``.  In JSON mode, arrays are preserved natively.
        """
        if self.content_format == 'json':
            return json.dumps(row, ensure_ascii=False, default=str)
        # YAML mode
        return yaml.dump(
            row,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        ).rstrip('\n')

    # -- loader contract ---------------------------------------------------

    async def _load(
        self,
        source: Union[str, PurePath],
        **kwargs,
    ) -> List[Document]:
        """Load rows from the configured database table.

        Args:
            source: Ignored for DatabaseLoader (table info comes from
                the instance attributes).  Kept for AbstractLoader compatibility.

        Returns:
            List of Document objects, one per table row.
        """
        table_ref = f'{self.schema}.{self.table}'
        query = self._build_query()
        self.logger.info(
            "DatabaseLoader: loading from %s (driver=%s)", table_ref, self.driver
        )
        if self.where:
            self.logger.warning(
                "DatabaseLoader: using raw WHERE clause — ensure input is sanitised"
            )

        docs: List[Document] = []

        if self.params:
            db = AsyncDB(self.driver, params=self.params)
        else:
            db = AsyncDB(self.driver, dsn=self.dsn)

        async with await db.connection() as conn:
            rows = await conn.fetch(query)

        if not rows:
            self.logger.warning(
                "DatabaseLoader: table %s returned 0 rows", table_ref
            )
            return docs

        self.logger.info(
            "DatabaseLoader: fetched %d rows from %s", len(rows), table_ref
        )

        for row_index, record in enumerate(rows):
            row_dict = dict(record)
            filtered = self._filter_columns(row_dict)
            content = self._serialize_row(filtered)

            metadata = self.create_metadata(
                path=table_ref,
                doctype='db_row',
                source_type='database',
                doc_metadata={
                    'table': self.table,
                    'schema': self.schema,
                    'row_index': row_index,
                    'driver': self.driver,
                },
            )

            docs.append(
                Document(page_content=content, metadata=metadata)
            )

        self.logger.info(
            "DatabaseLoader: created %d documents from %s", len(docs), table_ref
        )
        return docs

    # -- convenience override so `load()` works without a source arg -------

    async def load(self, source=None, **kwargs) -> List[Document]:
        """Load documents from the database table.

        Overrides the base ``load()`` to supply the table reference as ``source``
        so callers can simply call ``await loader.load()`` without arguments.
        """
        if source is None:
            source = f'{self.schema}.{self.table}'
        return await super().load(source=source, **kwargs)
