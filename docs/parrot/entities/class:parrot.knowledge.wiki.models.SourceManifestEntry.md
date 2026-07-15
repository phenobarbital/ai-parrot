---
type: Wiki Entity
title: SourceManifestEntry
id: class:parrot.knowledge.wiki.models.SourceManifestEntry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tracks an ingested source document in the wiki's source manifest.
---

# SourceManifestEntry

Defined in [`parrot.knowledge.wiki.models`](../summaries/mod:parrot.knowledge.wiki.models.md).

```python
class SourceManifestEntry(BaseModel)
```

Tracks an ingested source document in the wiki's source manifest.

Attributes:
    source_id: Stable deterministic identifier for the source (e.g.,
        SHA-1 of the URI path).
    source_uri: Absolute URI / path to the original source file.
    file_hash: SHA-1 hex digest of the source file contents at ingest time.
    mtime: File modification timestamp (``os.stat().st_mtime``) at
        ingest time, used for quick staleness pre-check.
    ingested_at: ISO-8601 UTC timestamp of when the ingest completed.
    pages_generated: Ordered list of wiki page IDs that were created or
        updated during this ingest.
    status: Lifecycle status.  ``"ingested"`` after a successful ingest;
        may be ``"stale"`` or ``"error"`` as appropriate.
