---
type: Wiki Summary
title: parrot.tools.databasequery.toolkit
id: mod:parrot.tools.databasequery.toolkit
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DatabaseQueryToolkit — Multi-database tools as an AbstractToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.toolkit.DatabaseQueryToolkit
  rel: defines
- concept: mod:parrot.security
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.tools.databasequery.toolkit`

DatabaseQueryToolkit — Multi-database tools as an AbstractToolkit.

Exposes LLM-callable tools via public async methods:

  - get_database_metadata
  - validate_query
  - execute_database_query
  - fetch_database_row
  - get_table_metadata
  - test_connection
  - save_result

Every query method routes through ``parrot.security.QueryValidator``
to block DDL/DML before reaching the underlying source.

Part of FEAT-105 — databasetoolkit-clash.
Part of FEAT-136 — database-toolkit-parity.

## Classes

- **`DatabaseQueryToolkit(AbstractToolkit)`** — Multi-database toolkit — discover schema, validate queries, execute.
