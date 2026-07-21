---
type: Wiki Entity
title: S3ReportReaderToolkit
id: class:parrot_tools.s3.report_reader.S3ReportReaderToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agnostic read-only toolkit for LLM agents to explore S3-stored reports.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# S3ReportReaderToolkit

Defined in [`parrot_tools.s3.report_reader`](../summaries/mod:parrot_tools.s3.report_reader.md).

```python
class S3ReportReaderToolkit(AbstractToolkit)
```

Agnostic read-only toolkit for LLM agents to explore S3-stored reports.

Mounts 8 tools with the ``s3_`` prefix, preventing collision when
co-mounted with ``SecurityReportToolkit``.

Works in two modes:

- **Full mode** (``report_store`` provided): catalog-backed queries
  available in addition to raw S3 browsing.
- **File-only mode** (no ``report_store``): only ``s3_list_reports``,
  ``s3_get_report_content``, ``s3_compare_reports``,
  ``s3_summarize_report``, and ``s3_get_report_url`` work.
  Catalog-dependent tools return ``{"error": "...", "hint": "..."}``.

Args:
    file_manager: Required. Provides raw S3 operations (list, download,
        URL generation).
    report_store: Optional. Provides catalog-backed queries.
    default_prefix: S3 key prefix used when ``prefix`` is omitted from
        ``list_reports``. Defaults to ``"security-reports/"``.
    max_diff_changes: Cap on the ``changes`` list returned by
        ``compare_reports``. Defaults to 50.
    **kwargs: Forwarded to ``AbstractToolkit.__init__``.

## Methods

- `async def list_reports(self, prefix: str='', pattern: str='*.json', limit: int=50) -> list[dict]` — List S3 objects under the given prefix. Works without catalog.
- `async def get_latest_report(self, scanner: str | None=None, framework: str | None=None, report_kind: str='scan') -> dict` — Requires catalog. Return the most recent report matching the filters.
- `async def get_report_content(self, report_id_or_path: str, section: str='full') -> dict` — Works without catalog (S3 path) or with catalog (UUID).
- `async def filter_reports(self, scanner: str | None=None, framework: str | None=None, provider: str | None=None, report_kind: str | None=None, since_days: int=30, limit: int=20) -> list[dict]` — Requires catalog. Query the catalog with multiple filters.
- `async def compare_reports(self, report_a: str, report_b: str) -> dict` — Works without catalog (S3 paths) or with catalog (UUIDs).
- `async def summarize_report(self, report_id_or_path: str) -> dict` — Works without catalog (S3 paths) or with catalog (UUIDs).
- `async def get_report_url(self, report_id_or_path: str, expiry: int=3600) -> dict` — Works without catalog. Generate a pre-signed URL for a report.
- `async def list_report_categories(self) -> dict` — Requires catalog. List distinct scanners, frameworks, and report kinds.
