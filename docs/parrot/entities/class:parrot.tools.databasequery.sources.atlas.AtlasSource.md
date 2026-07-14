---
type: Wiki Entity
title: AtlasSource
id: class:parrot.tools.databasequery.sources.atlas.AtlasSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: MongoDB Atlas database source.
---

# AtlasSource

Defined in [`parrot.tools.databasequery.sources.atlas`](../summaries/mod:parrot.tools.databasequery.sources.atlas.md).

```python
class AtlasSource(MongoSource)
```

MongoDB Atlas database source.

Extends ``MongoSource`` with Atlas-specific credential handling:
the ``mongodb+srv://`` URI scheme is expected for Atlas connections.

Uses the asyncdb ``mongo`` driver with ``dbtype="atlas"``.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default MongoDB Atlas credentials from environment variables.
