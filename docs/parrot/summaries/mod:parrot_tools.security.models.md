---
type: Wiki Summary
title: parrot_tools.security.models
id: mod:parrot_tools.security.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Unified security data models for the Security Toolkits Suite.
relates_to:
- concept: class:parrot_tools.security.models.CloudProvider
  rel: defines
- concept: class:parrot_tools.security.models.ComparisonDelta
  rel: defines
- concept: class:parrot_tools.security.models.ComplianceFramework
  rel: defines
- concept: class:parrot_tools.security.models.ConsolidatedReport
  rel: defines
- concept: class:parrot_tools.security.models.FindingSource
  rel: defines
- concept: class:parrot_tools.security.models.ScanResult
  rel: defines
- concept: class:parrot_tools.security.models.ScanSummary
  rel: defines
- concept: class:parrot_tools.security.models.SecurityFinding
  rel: defines
- concept: class:parrot_tools.security.models.SeverityLevel
  rel: defines
---

# `parrot_tools.security.models`

Unified security data models for the Security Toolkits Suite.

These models normalize findings from multiple security scanners (Prowler, Trivy, Checkov)
into a unified format for cross-tool aggregation and compliance reporting.

## Classes

- **`SeverityLevel(str, Enum)`** — Normalized severity levels across all scanners.
- **`FindingSource(str, Enum)`** — Security scanner sources.
- **`ComplianceFramework(str, Enum)`** — Supported compliance frameworks for mapping findings.
- **`CloudProvider(str, Enum)`** — Cloud providers supported by scanners.
- **`SecurityFinding(BaseModel)`** — Unified security finding from any scanner.
- **`ScanSummary(BaseModel)`** — Summary statistics for a single scanner run.
- **`ScanResult(BaseModel)`** — Complete results from a single scanner execution.
- **`ComparisonDelta(BaseModel)`** — Comparison between two scan results for trend analysis.
- **`ConsolidatedReport(BaseModel)`** — Consolidated report aggregating results from multiple scanners.
