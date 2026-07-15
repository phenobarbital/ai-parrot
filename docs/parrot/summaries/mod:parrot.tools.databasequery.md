---
type: Wiki Summary
title: parrot.tools.databasequery
id: mod:parrot.tools.databasequery
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: parrot.tools.databasequery — Public exports for the database query tools
  package.
relates_to:
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.tool
  rel: references
- concept: mod:parrot.tools.databasequery.toolkit
  rel: references
---

# `parrot.tools.databasequery`

parrot.tools.databasequery — Public exports for the database query tools package.

Provides a multi-tool database interface for AI agents with full driver parity
across PostgreSQL, MySQL, SQLite, BigQuery, MSSQL (with stored procedures),
Oracle, ClickHouse, DuckDB, MongoDB, Atlas, DocumentDB, InfluxDB, and
Elasticsearch/OpenSearch.

Example:
    >>> from parrot.tools.databasequery import DatabaseQueryToolkit
    >>> toolkit = DatabaseQueryToolkit()
    >>> agent = Agent(tools=toolkit.get_tools())

Part of FEAT-105 — databasetoolkit-clash.
Part of FEAT-136 — database-toolkit-parity.
