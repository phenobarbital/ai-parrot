# F001 — Existing SecurityReportToolkit

**Path**: `packages/ai-parrot-tools/src/parrot_tools/security/report_toolkit.py`
**Lines**: 1-249

The `SecurityReportToolkit(AbstractToolkit)` already exists (FEAT-162). It exposes:
- `find_security_report(scanner, framework, provider, scope_match, max_age_days, report_kind, limit)` → list[dict]
- `read_security_report(report_id, section)` → dict (sections: summary/critical/high/medium/low/executive/full)
- `search_findings(query, scanner, severity, since_days, limit)` → list[dict]
- `list_available_frameworks()` → list[str]

Constructor takes `report_store: SecurityReportStore` + `file_manager: FileManagerInterface`.
Read-only — no write, no compare, no summarize, no raw S3 browsing.

Tightly coupled to security-report models (ReportFilter, ReportKind, ReportRef).
Not suitable for generic S3 document access.
