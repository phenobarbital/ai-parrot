---
type: Wiki Entity
title: MongoSource
id: class:parrot.tools.dataset_manager.sources.mongo.MongoSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: DataSource for MongoDB/DocumentDB collections via asyncdb's mongo driver.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# MongoSource

Defined in [`parrot.tools.dataset_manager.sources.mongo`](../summaries/mod:parrot.tools.dataset_manager.sources.mongo.md).

```python
class MongoSource(DataSource)
```

DataSource for MongoDB/DocumentDB collections via asyncdb's mongo driver.

Read-only. Every fetch() call requires both a ``filter`` dict and a
``projection`` dict to prevent full-collection scans and limit the fields
returned.

``prefetch_schema()`` calls ``find_one()`` on the collection to infer field
names and Python types from a single document.

Args:
    collection: MongoDB collection name, e.g. "orders".
    name: Dataset name/identifier for this source.
    database: MongoDB database name, e.g. "mydb".
    credentials: Optional credentials dict with host/port/user/password.
        Used when dsn is None.
    dsn: Optional MongoDB connection string (DSN). Takes priority over
        the credentials dict.
    required_filter: If True (default), fetch() raises ValueError when
        no filter is provided. Set False to allow unrestricted queries
        (not recommended for production).

## Methods

- `async def prefetch_schema(self) -> Dict[str, str]` — Infer schema from a single MongoDB document via find_one().
- `async def fetch(self, **params) -> pd.DataFrame` — Query the MongoDB collection and return a DataFrame.
- `def describe(self) -> str` — Return a human-readable description for the LLM guide.
- `def cache_key(self) -> str` — Stable Redis cache key for this MongoDB source.
