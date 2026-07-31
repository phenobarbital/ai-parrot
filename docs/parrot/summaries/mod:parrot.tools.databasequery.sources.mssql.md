---
type: Wiki Summary
title: parrot.tools.databasequery.sources.mssql
id: mod:parrot.tools.databasequery.sources.mssql
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Microsoft SQL Server database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.mssql.MSSQLSource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.databasequery.sources.mssql`

Microsoft SQL Server database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for MSSQL using the asyncdb ``mssql`` driver.
Overrides ``validate_query()`` to allow EXEC/EXECUTE statements (stored procedures)
in addition to standard T-SQL. Includes stored procedures in metadata discovery.

Part of FEAT-062 — DatabaseToolkit.

## Classes

- **`MSSQLSource(AbstractDatabaseSource)`** — Microsoft SQL Server database source with stored procedure support.
