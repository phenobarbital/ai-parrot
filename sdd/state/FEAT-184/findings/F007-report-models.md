# F007 — Report catalog models

**Path**: `packages/ai-parrot/src/parrot/storage/security_reports/models.py`
**Lines**: 1-129

- `ReportKind`: SCAN, DAILY_SUMMARY, WEEKLY_SUMMARY, MONTHLY_SUMMARY, DRIFT_COMPARISON
- `SeverityBreakdown`: critical, high, medium, low, informational (counts)
- `EmbeddedFinding`: finding_id, severity, title, resource_id, rule_id, remediation_hint
- `ReportRef`: Full metadata record — report_id, report_kind, scanner, framework,
  provider, scope, severity_summary, top_findings, uri, content_type, content_bytes,
  produced_at, produced_by, parser_version, retention_class
- `ReportFilter`: scanner, framework, provider, report_kind, since, until,
  scope_match, limit, order_by

The `uri` field on ReportRef points to the S3 key (e.g.,
`security-reports/cloudsploit/security/2026/05/18/<uuid>.json`).
The `content_type` field supports `application/json` (default) and
potentially HTML.
