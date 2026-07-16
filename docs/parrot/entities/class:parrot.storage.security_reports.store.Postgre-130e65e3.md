---
type: Wiki Entity
title: PostgresS3SecurityReportStore
id: class:parrot.storage.security_reports.store.PostgresS3SecurityReportStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Postgres (metadata) + S3/FileManager (content) catalog implementation.
---

# PostgresS3SecurityReportStore

Defined in [`parrot.storage.security_reports.store`](../summaries/mod:parrot.storage.security_reports.store.md).

```python
class PostgresS3SecurityReportStore
```

Postgres (metadata) + S3/FileManager (content) catalog implementation.

Constructor:
    dsn: Postgres connection string (asyncdb AsyncDB format).
    file_manager: FileManagerInterface implementation (e.g. S3FileManager).
    s3_prefix: Path prefix for content objects. Defaults to
        'security-reports/' but can be overridden for multi-env isolation.

## Methods

- `async def save_report(self, ref: ReportRef, content: bytes | Path) -> ReportRef` — Upload content to S3 first, then insert metadata into Postgres.
- `async def index(self, ref: ReportRef) -> None` — Insert metadata only (content was already uploaded externally).
- `async def query(self, filter: ReportFilter) -> list[ReportRef]` — Query the catalog.
- `async def get(self, report_id: UUID) -> ReportRef | None` — Fetch a single ReportRef by primary key.
- `async def fetch_content(self, report_id: UUID) -> bytes` — Download and return the content bytes for a report.
- `async def delete(self, report_id: UUID) -> None` — Hard-delete a report (GDPR-only). Removes both Postgres row and S3 content.
- `async def query_distinct_frameworks(self) -> list[str]` — Return distinct non-null framework values via SQL DISTINCT query.
- `async def bootstrap_schema(self) -> None` — Idempotently apply schema.sql to the connected database.
