---
id: F013
query_id: Q013
type: glob
intent: Find where parrot_tools.security lives and list its layout.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F013 — `parrot_tools.security` lives in the monorepo at `packages/ai-parrot-tools/src/parrot_tools/security/`

## Summary

The brainstorm correctly identifies the package name. The directory contains
toolkits, per-scanner sub-packages, shared models, and a base parser/executor.
New files declared by the brainstorm (`persistence.py`, `report_toolkit.py`,
`parsers/`, `summarizer.py`) do **not** yet exist.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/security/`
  lines: directory
  symbol: contents
  excerpt: |
    __init__.py
    base_executor.py
    base_parser.py
    models.py                            -- ScanResult, SecurityFinding, ComparisonDelta, ComplianceFramework, SeverityLevel, ConsolidatedReport
    cloud_posture_toolkit.py
    compliance_report_toolkit.py         -- ComplianceReportToolkit
    container_security_toolkit.py        -- ContainerSecurityToolkit
    secrets_iac_toolkit.py
    checkov/                             -- config, executor, parser
    prowler/                             -- config, executor, parser
    trivy/                               -- config, executor, parser
    scoutsuite/                          -- config, executor, parser
    reports/                             -- compliance_mapper, generator

## Notes

- The brainstorm's planned additions (`persistence.py`, `report_toolkit.py`,
  `parsers/`, `summarizer.py`) are all NEW files — none collide with existing
  symbols.
- `models.py` already contains `ScanResult`, `SecurityFinding`,
  `ComparisonDelta`, `ComplianceFramework`, `SeverityLevel`, `ConsolidatedReport`.
  The brainstorm's new `ReportRef`, `ReportFilter`, `SeverityBreakdown`,
  `EmbeddedFinding`, `ReportKind` will live in `parrot/storage/security_reports/models.py`
  (a different package) — no name collision but worth flagging that two
  `SeverityLevel`-like enums will coexist.
