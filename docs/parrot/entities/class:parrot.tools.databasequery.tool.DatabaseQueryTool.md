---
type: Wiki Entity
title: DatabaseQueryTool
id: class:parrot.tools.databasequery.tool.DatabaseQueryTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Multi-language Database Query Tool for executing queries across multiple
  database systems.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# DatabaseQueryTool

Defined in [`parrot.tools.databasequery.tool`](../summaries/mod:parrot.tools.databasequery.tool.md).

```python
class DatabaseQueryTool(AbstractTool)
```

Multi-language Database Query Tool for executing queries across multiple database systems.

This tool can execute SELECT queries on various databases including BigQuery, PostgreSQL,
MySQL, InfluxDB, SQLite, Oracle, and others supported by asyncdb library.

Supports multiple query languages:
- SQL: PostgreSQL (pg), MySQL, BigQuery, SQLite, Oracle, MS SQL Server (mssql),
    ClickHouse, DuckDB
- Flux: InfluxDB (influx) - time-series database with Flux query language
- DocumentDB: DocumentDB (documentdb) - document-oriented database

DRIVER REFERENCE:
- 'pg' or 'postgres' or 'postgresql' → PostgreSQL
- 'mysql' or 'mariadb' → MySQL/MariaDB
- 'bigquery' or 'bq' → Google BigQuery
- 'mssql' or 'sqlserver' → Microsoft SQL Server
- 'influx' or 'influxdb' → InfluxDB (uses Flux, not SQL)
- 'sqlite' → SQLite
- 'oracle' → Oracle Database
- 'clickhouse' → ClickHouse
- 'duckdb' → DuckDB
- 'documentdb' → DocumentDB (MongoDB-compatible)
- 'elastic' → Elasticsearch (Elasticsearch/OpenSearch)

QUERY LANGUAGE EXAMPLES:

SQL (pg, mysql, bigquery, etc.):
    SELECT column1, column2 FROM table WHERE condition

Flux (influx):
    from(bucket: "my-bucket")
    |> range(start: -12h)
    |> filter(fn: (r) => r["_measurement"] == "temperature")
    |> filter(fn: (r) => r["location"] == "room1")

DocumentDB:
    { find: "collection", filter: { field: "value" } }


IMPORTANT: This tool is designed for data retrieval and analysis queries (SELECT statements).
It should NOT be used for:
- DDL operations (CREATE, ALTER, DROP tables/schemas)
- DML operations (INSERT, UPDATE, DELETE data)
- Administrative operations (GRANT, REVOKE permissions)
- Database structure modifications

Use this tool for:
- Data exploration and analysis
- Generating reports from existing data
- Aggregating and summarizing information
- Filtering and searching database records
- Joining data from multiple tables for analysis

## Methods

- `def get_supported_drivers(self) -> List[str]` — Get list of supported database drivers.
- `async def test_connection(self, driver: str, credentials: Optional[Dict[str, Any]]=None) -> Dict[str, Any]` — Test database connection.
- `def save_query_result(self, result: Union[pd.DataFrame, str], filename: Optional[str]=None, file_format: str='csv') -> Dict[str, Any]` — Save query result to file.
