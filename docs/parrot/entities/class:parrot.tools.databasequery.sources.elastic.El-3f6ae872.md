---
type: Wiki Entity
title: ElasticSource
id: class:parrot.tools.databasequery.sources.elastic.ElasticSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Elasticsearch/OpenSearch database source.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: extends
---

# ElasticSource

Defined in [`parrot.tools.databasequery.sources.elastic`](../summaries/mod:parrot.tools.databasequery.sources.elastic.md).

```python
class ElasticSource(AbstractDatabaseSource)
```

Elasticsearch/OpenSearch database source.

Validates queries as JSON DSL bodies containing recognized
Elasticsearch query keys. Discovers schema via index ``_mapping`` API.
Works with both Elasticsearch and OpenSearch (asyncdb handles differences).

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default Elasticsearch credentials from environment variables.
- `async def test_connection(self, credentials: dict[str, Any]) -> bool` — Test Elasticsearch/OpenSearch connectivity using the ``info()`` call.
- `async def validate_query(self, query: str) -> ValidationResult` — Validate an Elasticsearch/OpenSearch JSON DSL query body.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover Elasticsearch schema via index mappings.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute an Elasticsearch JSON DSL query and return all hits.
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute an Elasticsearch JSON DSL query and return the first hit.
