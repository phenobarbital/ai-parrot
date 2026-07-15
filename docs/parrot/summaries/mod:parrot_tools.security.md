---
type: Wiki Summary
title: parrot_tools.security
id: mod:parrot_tools.security
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AI-Parrot Security Toolkits Suite.
relates_to:
- concept: mod:parrot_tools
  rel: references
---

# `parrot_tools.security`

AI-Parrot Security Toolkits Suite.

Provides agent-callable tools for cloud security scanning, compliance reporting,
and vulnerability management. Wraps Prowler, Trivy, and Checkov.

Usage:
    # Import toolkits for agent integration
    from parrot_tools.security import (
        CloudPostureToolkit,
        ContainerSecurityToolkit,
        SecretsIaCToolkit,
        ComplianceReportToolkit,
    )

    # Run a full compliance scan
    toolkit = ComplianceReportToolkit()
    report = await toolkit.compliance_full_scan(
        provider="aws",
        target_image="nginx:latest",
        iac_path="./terraform"
    )
    path = await toolkit.compliance_soc2_report()

    # Or import specific components
    from parrot_tools.security.models import SecurityFinding, ScanResult
    from parrot_tools.security.prowler import ProwlerExecutor, ProwlerConfig
    from parrot_tools.security.reports import ComplianceMapper, ReportGenerator
