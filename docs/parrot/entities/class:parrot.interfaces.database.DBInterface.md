---
type: Wiki Entity
title: DBInterface
id: class:parrot.interfaces.database.DBInterface
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Interface for relational database operations using AsyncDB.
---

# DBInterface

Defined in [`parrot.interfaces.database`](../summaries/mod:parrot.interfaces.database.md).

```python
class DBInterface
```

Interface for relational database operations using AsyncDB.

Provides high-level CRUD helpers that build parameterised SQL,
handle object serialisation, and delegate execution to the asyncdb driver.

## Methods

- `def get_driver(self, driver: str='pg', dsn: str=None, params: dict=None, timeout: int=60, **kwargs) -> AsyncDB` — Create an AsyncDB driver instance.
- `def get_database(self, driver: str='pg', dsn: str=None, params: dict=None, timeout: int=60, **kwargs) -> AsyncDB` — Deprecated – use ``get_driver`` instead.
- `async def execute(self, sentence: str, *args, driver: str='pg', dsn: str=None, **kwargs) -> Any` — Execute a raw SQL statement via the asyncdb driver.
- `async def prepared_statement(self, sentence: str, driver: str='pg', dsn: str=None) -> Any` — Create a prepared statement on the underlying driver connection.
- `async def ensure_indexes(self, table: str, schema: str, fields: List[str], index_type: str='btree', driver: str='pg', dsn: str=None) -> str` — Create an index on *fields* if it does not already exist.
- `async def insert(self, table: str, schema: str, obj: Any, driver: str='pg', dsn: str=None, **kwargs) -> Any` — Insert a single record.
- `async def update(self, table: str, schema: str, obj: Any, unique_fields: List[str], driver: str='pg', dsn: str=None) -> Any` — Update a record identified by *unique_fields*.
- `async def delete(self, table: str, schema: str, obj: Any, unique_fields: List[str], driver: str='pg', dsn: str=None) -> Any` — Delete a record identified by *unique_fields*.
- `async def filter(self, table: str, schema: str, conditions: Dict[str, Any], fields: Optional[List[str]]=None, driver: str='pg', dsn: str=None) -> Optional[List[Any]]` — Select rows matching *conditions*.
- `async def get(self, table: str, schema: str, conditions: Dict[str, Any], fields: Optional[List[str]]=None, driver: str='pg', dsn: str=None) -> Optional[Any]` — Fetch a single row matching *conditions*.
