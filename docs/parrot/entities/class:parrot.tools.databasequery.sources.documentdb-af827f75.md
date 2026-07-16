---
type: Wiki Entity
title: DocumentDBSource
id: class:parrot.tools.databasequery.sources.documentdb.DocumentDBSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: AWS DocumentDB database source.
---

# DocumentDBSource

Defined in [`parrot.tools.databasequery.sources.documentdb`](../summaries/mod:parrot.tools.databasequery.sources.documentdb.md).

```python
class DocumentDBSource(MongoSource)
```

AWS DocumentDB database source.

Extends ``MongoSource`` with DocumentDB-specific credential defaults:
- ``ssl=True`` (required by AWS)
- ``tlsCAFile`` defaults to the AWS global bundle path

Uses the asyncdb ``mongo`` driver with ``dbtype="documentdb"``.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default DocumentDB credentials with SSL enabled.
