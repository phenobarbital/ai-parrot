---
type: Wiki Entity
title: InfluxDBToolkit
id: class:parrot.bots.database.toolkits.influx.InfluxDBToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: InfluxDB toolkit with Flux query language support.
relates_to:
- concept: class:parrot.bots.database.toolkits.base.DatabaseToolkit
  rel: extends
---

# InfluxDBToolkit

Defined in [`parrot.bots.database.toolkits.influx`](../summaries/mod:parrot.bots.database.toolkits.influx.md).

```python
class InfluxDBToolkit(DatabaseToolkit)
```

InfluxDB toolkit with Flux query language support.

Exposes measurement search, Flux query generation/execution, and
bucket exploration as LLM-callable tools.

## Methods

- `async def search_schema(self, search_term: str, schema_name: Optional[str]=None, limit: int=10) -> List[TableMetadata]` — Search for InfluxDB measurements matching the search term.
- `async def execute_query(self, query: str, limit: int=1000, timeout: int=30) -> QueryExecutionResponse` — Execute a Flux query.
- `async def search_measurements(self, search_term: str, bucket: Optional[str]=None, limit: int=10) -> List[TableMetadata]` — Search for InfluxDB measurements matching *search_term*.
- `async def generate_flux_query(self, natural_language: str, bucket: Optional[str]=None, measurement: Optional[str]=None) -> str` — Generate context for Flux query generation.
- `async def execute_flux_query(self, query: str, limit: int=1000, timeout: int=30) -> QueryExecutionResponse` — Execute a Flux query and return results.
- `async def explore_buckets(self) -> List[str]` — List available InfluxDB buckets.
