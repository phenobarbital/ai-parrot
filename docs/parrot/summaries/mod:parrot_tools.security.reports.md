---
type: Wiki Summary
title: parrot_tools.security.reports
id: mod:parrot_tools.security.reports
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Security Reports Package.
relates_to:
- concept: mod:parrot_tools.security
  rel: references
---

# `parrot_tools.security.reports`

Security Reports Package.

Provides compliance mapping and report generation functionality
for security scan results.

Usage:
    from parrot_tools.security.reports import ComplianceMapper, ReportGenerator

    mapper = ComplianceMapper()
    controls = mapper.map_finding_to_controls(finding, ComplianceFramework.SOC2)

    generator = ReportGenerator(output_dir="/tmp/reports")
    path = await generator.generate_compliance_report(report, ComplianceFramework.SOC2)
