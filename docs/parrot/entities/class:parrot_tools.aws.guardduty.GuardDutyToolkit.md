---
type: Wiki Entity
title: GuardDutyToolkit
id: class:parrot_tools.aws.guardduty.GuardDutyToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for inspecting AWS GuardDuty detectors and findings.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# GuardDutyToolkit

Defined in [`parrot_tools.aws.guardduty`](../summaries/mod:parrot_tools.aws.guardduty.md).

```python
class GuardDutyToolkit(AbstractToolkit)
```

Toolkit for inspecting AWS GuardDuty detectors and findings.

Available Operations:
- aws_guardduty_list_detectors: List GuardDuty detectors
- aws_guardduty_list_findings: List findings with optional severity filter
- aws_guardduty_get_finding_details: Get detailed finding info
- aws_guardduty_get_findings_statistics: Get findings statistics
- aws_guardduty_list_ip_sets: List trusted IP sets
- aws_guardduty_list_threat_intel_sets: List threat intelligence sets

## Methods

- `async def aws_guardduty_list_detectors(self, max_results: int=50) -> Dict[str, Any]` — List all GuardDuty detectors in the account.
- `async def aws_guardduty_list_findings(self, detector_id: str, max_results: int=50, severity: Optional[str]=None) -> Dict[str, Any]` — List GuardDuty findings for a detector.
- `async def aws_guardduty_get_finding_details(self, detector_id: str, finding_id: str) -> Dict[str, Any]` — Get detailed information about a specific GuardDuty finding.
- `async def aws_guardduty_get_findings_statistics(self, detector_id: str) -> Dict[str, Any]` — Get statistics for GuardDuty findings.
- `async def aws_guardduty_list_ip_sets(self, detector_id: str, max_results: int=50) -> Dict[str, Any]` — List trusted IP sets for a GuardDuty detector.
- `async def aws_guardduty_list_threat_intel_sets(self, detector_id: str, max_results: int=50) -> Dict[str, Any]` — List threat intelligence sets for a GuardDuty detector.
