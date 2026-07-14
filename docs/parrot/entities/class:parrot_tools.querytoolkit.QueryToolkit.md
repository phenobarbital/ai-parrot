---
type: Wiki Entity
title: QueryToolkit
id: class:parrot_tools.querytoolkit.QueryToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for DB Queries-like Toolkits.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# QueryToolkit

Defined in [`parrot_tools.querytoolkit`](../summaries/mod:parrot_tools.querytoolkit.md).

```python
class QueryToolkit(AbstractToolkit)
```

Abstract base class for DB Queries-like Toolkits.

Use this class to define a toolkit for interacting with a database
using a structured query approach. It provides methods for executing
queries, handling results, and managing database connections.

This class provides a foundation for DB Queries-like toolkits, including
common configurations and methods for interacting with the database.
It is designed to be extended by specific toolkits that implement
functionality related to DB Queries-like operations.

## Methods

- `def program_slug(self) -> str` — Get the program slug.
