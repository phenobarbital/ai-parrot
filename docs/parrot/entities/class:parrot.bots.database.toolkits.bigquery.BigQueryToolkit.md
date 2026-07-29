---
type: Wiki Entity
title: BigQueryToolkit
id: class:parrot.bots.database.toolkits.bigquery.BigQueryToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: BigQuery-specific toolkit.
relates_to:
- concept: class:parrot.bots.database.toolkits.sql.SQLToolkit
  rel: extends
---

# BigQueryToolkit

Defined in [`parrot.bots.database.toolkits.bigquery`](../summaries/mod:parrot.bots.database.toolkits.bigquery.md).

```python
class BigQueryToolkit(SQLToolkit)
```

BigQuery-specific toolkit.

Overrides dialect hooks for BigQuery's introspection, dry-run cost
estimation, and project/dataset DSN format.  Uses asyncdb's BigQuery
driver natively — no SQLAlchemy path.
