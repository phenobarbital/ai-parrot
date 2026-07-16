---
type: Wiki Summary
title: parrot_tools.cloudsploit.models
id: mod:parrot_tools.cloudsploit.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic data models for CloudSploit security scanning toolkit.
relates_to:
- concept: class:parrot_tools.cloudsploit.models.CloudProvider
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.CloudSploitConfig
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.ComparisonReport
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.ComplianceFramework
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.EcrCollectionPlan
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.EcrCollectionResult
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.EcrRepoFindings
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.EcrRepoPlan
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.EcrScanFinding
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.EcrSeverity
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.ScanFinding
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.ScanResult
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.ScanSummary
  rel: defines
- concept: class:parrot_tools.cloudsploit.models.SeverityLevel
  rel: defines
- concept: mod:parrot.conf
  rel: references
---

# `parrot_tools.cloudsploit.models`

Pydantic data models for CloudSploit security scanning toolkit.

## Classes

- **`SeverityLevel(str, Enum)`** — CloudSploit finding severity levels.
- **`ComplianceFramework(str, Enum)`** — Supported compliance frameworks for filtered scans.
- **`CloudProvider(str, Enum)`** — Supported cloud providers for CloudSploit scans.
- **`ScanFinding(BaseModel)`** — A single finding from a CloudSploit scan.
- **`ScanSummary(BaseModel)`** — Aggregated summary of a CloudSploit scan.
- **`ScanResult(BaseModel)`** — Full scan result container.
- **`CloudSploitConfig(BaseModel)`** — Configuration for CloudSploit execution.
- **`ComparisonReport(BaseModel)`** — Result of comparing two CloudSploit scans.
- **`EcrSeverity(str, Enum)`** — ECR / vulnerability scan severities (distinct from SeverityLevel).
- **`EcrRepoPlan(BaseModel)`** — One ECR repository plus its tag priority order.
- **`EcrCollectionPlan(BaseModel)`** — Plan for ``collect_ecr_findings``. Loaded from a YAML file at runtime.
- **`EcrScanFinding(BaseModel)`** — One vulnerability finding from ECR Basic Scanning.
- **`EcrRepoFindings(BaseModel)`** — Aggregated findings for a single (repo, tag) pair.
- **`EcrCollectionResult(BaseModel)`** — Top-level container — mirrors the JSON output of collect_ecr_findings.js.
