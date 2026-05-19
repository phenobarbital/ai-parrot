# F002 — PostgresS3SecurityReportStore

**Path**: `packages/ai-parrot/src/parrot/storage/security_reports/store.py`
**Lines**: 144-389

Implements `SecurityReportStore` Protocol. Constructor: `(dsn, file_manager, *, s3_prefix)`.

Key methods:
- `save_report(ref, content)` → ReportRef (S3 upload + PG insert)
- `query(filter: ReportFilter)` → list[ReportRef] (PG query)
- `get(report_id)` → ReportRef | None (PG lookup)
- `fetch_content(report_id)` → bytes (S3 download via FileManagerInterface)
- `query_distinct_frameworks()` → list[str]
- `bootstrap_schema()` → idempotent DDL

S3 key pattern: `{prefix}{scanner}/{framework}/{date}/{report_id}.json`

Internal `_build_key(ref)` produces human-browsable paths.
Uses asyncdb.AsyncDB for Postgres.
