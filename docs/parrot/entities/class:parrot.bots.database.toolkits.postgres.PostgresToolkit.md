---
type: Wiki Entity
title: PostgresToolkit
id: class:parrot.bots.database.toolkits.postgres.PostgresToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: PostgreSQL-specific toolkit with first-class CRUD tools.
relates_to:
- concept: class:parrot.bots.database.toolkits.sql.SQLToolkit
  rel: extends
---

# PostgresToolkit

Defined in [`parrot.bots.database.toolkits.postgres`](../summaries/mod:parrot.bots.database.toolkits.postgres.md).

```python
class PostgresToolkit(SQLToolkit)
```

PostgreSQL-specific toolkit with first-class CRUD tools.

Overrides dialect hooks for PostgreSQL's richer introspection and
EXPLAIN output.  When ``read_only=False``, five LLM-callable tools are
exposed: ``db_insert_row``, ``db_upsert_row``, ``db_update_row``,
``db_delete_row``, and ``db_select_rows``.

All write tools enforce a table whitelist (``self.tables``), validate
input via a per-table dynamic Pydantic model, and cache parameterized
SQL templates per instance.

## Methods

- `async def insert_row(self, table: str, data: Dict[str, Any], returning: Optional[List[str]]=None, conn: Optional[Any]=None) -> Dict[str, Any]` — Insert a single row into *table*.
- `async def upsert_row(self, table: str, data: Dict[str, Any], conflict_cols: Optional[List[str]]=None, update_cols: Optional[List[str]]=None, returning: Optional[List[str]]=None, conn: Optional[Any]=None) -> Dict[str, Any]` — Upsert a single row into *table* using ``ON CONFLICT``.
- `async def update_row(self, table: str, data: Dict[str, Any], where: Dict[str, Any], returning: Optional[List[str]]=None, conn: Optional[Any]=None) -> Dict[str, Any]` — Update columns in *table* matching *where*.
- `async def delete_row(self, table: str, where: Dict[str, Any], returning: Optional[List[str]]=None, conn: Optional[Any]=None) -> Dict[str, Any]` — Delete rows from *table* matching *where*.
- `async def select_rows(self, table: str, where: Optional[Dict[str, Any]]=None, columns: Optional[List[str]]=None, order_by: Optional[List[str]]=None, limit: Optional[int]=None, conn: Optional[Any]=None, distinct: bool=False, column_casts: Optional[Dict[str, str]]=None) -> List[Dict[str, Any]]` — Select rows from *table*.
- `async def execute_sql(self, sql: str, params: tuple[Any, ...]=(), conn: Optional[Any]=None, returning: bool=True, single_row: bool=False) -> Any` — Execute a parameterized SQL statement, optionally within a transaction.
- `async def transaction(self) -> AsyncIterator[Any]` — Yield a raw asyncpg connection inside a transaction block.
- `async def reload_metadata(self, schema_name: str, table: str) -> None` — Purge and lazily re-warm cached metadata + templates for (schema_name, table).
