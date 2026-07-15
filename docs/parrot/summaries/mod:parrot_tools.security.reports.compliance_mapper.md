---
type: Wiki Summary
title: parrot_tools.security.reports.compliance_mapper
id: mod:parrot_tools.security.reports.compliance_mapper
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compliance Mapper for security findings.
relates_to:
- concept: class:parrot_tools.security.reports.compliance_mapper.ComplianceMapper
  rel: defines
- concept: mod:parrot_tools.security.models
  rel: references
---

# `parrot_tools.security.reports.compliance_mapper`

Compliance Mapper for security findings.

Maps normalized SecurityFinding objects to compliance framework controls
(SOC2, HIPAA, PCI-DSS, etc.), enabling cross-tool compliance reporting.

## Classes

- **`ComplianceMapper`** — Maps security findings to compliance framework controls.
