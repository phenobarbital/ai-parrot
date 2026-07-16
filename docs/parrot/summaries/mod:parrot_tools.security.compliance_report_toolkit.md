---
type: Wiki Summary
title: parrot_tools.security.compliance_report_toolkit
id: mod:parrot_tools.security.compliance_report_toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Compliance Report Toolkit — Multi-scanner orchestration and reporting.
relates_to:
- concept: class:parrot_tools.security.compliance_report_toolkit.ComplianceReportToolkit
  rel: defines
- concept: mod:parrot.storage.security_reports
  rel: references
- concept: mod:parrot_tools.security.checkov.config
  rel: references
- concept: mod:parrot_tools.security.checkov.executor
  rel: references
- concept: mod:parrot_tools.security.checkov.parser
  rel: references
- concept: mod:parrot_tools.security.models
  rel: references
- concept: mod:parrot_tools.security.persistence
  rel: references
- concept: mod:parrot_tools.security.prowler.config
  rel: references
- concept: mod:parrot_tools.security.prowler.executor
  rel: references
- concept: mod:parrot_tools.security.prowler.parser
  rel: references
- concept: mod:parrot_tools.security.reports.compliance_mapper
  rel: references
- concept: mod:parrot_tools.security.reports.generator
  rel: references
- concept: mod:parrot_tools.security.scoutsuite.config
  rel: references
- concept: mod:parrot_tools.security.scoutsuite.executor
  rel: references
- concept: mod:parrot_tools.security.scoutsuite.parser
  rel: references
- concept: mod:parrot_tools.security.trivy.config
  rel: references
- concept: mod:parrot_tools.security.trivy.executor
  rel: references
- concept: mod:parrot_tools.security.trivy.parser
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.security.compliance_report_toolkit`

Compliance Report Toolkit — Multi-scanner orchestration and reporting.

Agent-facing toolkit that orchestrates all security scanners (Prowler, Trivy, Checkov)
and produces unified compliance reports. Uses executors and parsers directly to avoid
circular dependencies with individual toolkits.

All public async methods automatically become agent tools.

## Classes

- **`ComplianceReportToolkit(ReportPersistenceMixin, AbstractToolkit)`** — Multi-scanner compliance reporting toolkit.
