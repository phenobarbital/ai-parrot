---
type: Wiki Entity
title: DatabaseTool
id: class:parrot_tools.db.DatabaseTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Unified Database Tool that handles the complete database interaction pipeline:'
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# DatabaseTool

Defined in [`parrot_tools.db`](../summaries/mod:parrot_tools.db.md).

```python
class DatabaseTool(AbstractTool)
```

Unified Database Tool that handles the complete database interaction pipeline:

1. Schema Discovery: Extract and cache table schemas from any supported database
2. Knowledge Base Building: Store schema metadata in vector store for RAG
3. Query Generation: Convert natural language to database-specific queries
4. Query Validation: Syntax checking, security validation, cost estimation
5. Query Execution: Safe execution with proper error handling
6. Structured Output: Format results according to specified schemas

This tool consolidates the functionality of SchemaTool, DatabaseQueryTool,
and SQLAgent into a single, cohesive interface.
