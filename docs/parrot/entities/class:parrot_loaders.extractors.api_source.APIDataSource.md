---
type: Wiki Entity
title: APIDataSource
id: class:parrot_loaders.extractors.api_source.APIDataSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for REST API data extraction.
relates_to:
- concept: class:parrot_loaders.extractors.base.ExtractDataSource
  rel: extends
---

# APIDataSource

Defined in [`parrot_loaders.extractors.api_source`](../summaries/mod:parrot_loaders.extractors.api_source.md).

```python
class APIDataSource(ExtractDataSource)
```

Base class for REST API data extraction.

Subclass this for specific APIs (Workday, Jira, etc.). Handles pagination,
authentication, and rate limiting.

Config:
    base_url: str — API base URL.
    auth_type: str — "bearer", "basic", "oauth2".
    credentials: dict — Auth credentials (token, username/password, etc.).
    headers: dict — Additional HTTP headers.
    page_size: int — Records per page (default: 100).
    max_pages: int — Safety limit on pagination (default: 100).

Args:
    name: Human-readable name for logging and reporting.
    config: Source-specific configuration.

## Methods

- `async def extract(self, fields: list[str] | None=None, filters: dict[str, Any] | None=None) -> ExtractionResult` — Paginated extraction from the API.
- `async def list_fields(self) -> list[str]` — Fetch first page and return keys from first record.
