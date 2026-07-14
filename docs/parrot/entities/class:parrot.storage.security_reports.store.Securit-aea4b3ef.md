---
type: Wiki Entity
title: SecurityReportStore
id: class:parrot.storage.security_reports.store.SecurityReportStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Protocol for the security report catalog persistence layer.
---

# SecurityReportStore

Defined in [`parrot.storage.security_reports.store`](../summaries/mod:parrot.storage.security_reports.store.md).

```python
class SecurityReportStore(Protocol)
```

Protocol for the security report catalog persistence layer.

Implementations back this with any combination of metadata store and
content store. The reference implementation uses Postgres + S3.

## Methods

- `async def save_report(self, ref: ReportRef, content: bytes | Path) -> ReportRef` — Upload content and persist metadata. Returns the ref with uri set.
- `async def index(self, ref: ReportRef) -> None` — Index-only path: insert metadata for a ref whose content was
- `async def query(self, filter: ReportFilter) -> list[ReportRef]` — Query the catalog by filter. Never applies an implicit age filter.
- `async def get(self, report_id: UUID) -> ReportRef | None` — Fetch a single ReportRef by primary key. None if not found.
- `async def fetch_content(self, report_id: UUID) -> bytes` — Download and return the content bytes for a report.
- `async def delete(self, report_id: UUID) -> None` — Hard-delete a report (GDPR-only). Not used by retention logic.
- `async def query_distinct_frameworks(self) -> list[str]` — Return distinct non-null framework values from the catalog.
- `async def bootstrap_schema(self) -> None` — Idempotently apply schema.sql to the Postgres database.
