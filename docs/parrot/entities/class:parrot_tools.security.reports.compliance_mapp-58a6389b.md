---
type: Wiki Entity
title: ComplianceMapper
id: class:parrot_tools.security.reports.compliance_mapper.ComplianceMapper
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Maps security findings to compliance framework controls.
---

# ComplianceMapper

Defined in [`parrot_tools.security.reports.compliance_mapper`](../summaries/mod:parrot_tools.security.reports.compliance_mapper.md).

```python
class ComplianceMapper
```

Maps security findings to compliance framework controls.

Maintains a mapping database from:
- Prowler check IDs → compliance controls
- Trivy vulnerability types → compliance controls
- Checkov policy IDs → compliance controls

The mapper loads YAML mapping files that define the relationship between
scanner-specific check IDs and framework controls.

Example:
    mapper = ComplianceMapper()
    controls = mapper.map_finding_to_controls(finding, ComplianceFramework.SOC2)
    coverage = mapper.get_framework_coverage(findings, ComplianceFramework.SOC2)

## Methods

- `def map_finding_to_controls(self, finding: SecurityFinding, framework: ComplianceFramework) -> list[str]` — Map a security finding to relevant compliance controls.
- `def get_framework_coverage(self, findings: list[SecurityFinding], framework: ComplianceFramework) -> dict` — Calculate compliance coverage for a framework based on findings.
- `def get_control_details(self, control_id: str, framework: ComplianceFramework) -> Optional[dict]` — Get details for a specific compliance control.
- `def get_all_controls(self, framework: ComplianceFramework) -> dict[str, dict]` — Get all controls for a compliance framework.
- `def get_findings_by_control(self, findings: list[SecurityFinding], framework: ComplianceFramework) -> dict[str, list[SecurityFinding]]` — Group findings by the controls they map to.
- `def get_unmapped_findings(self, findings: list[SecurityFinding], framework: ComplianceFramework) -> list[SecurityFinding]` — Get findings that don't map to any control in the framework.
