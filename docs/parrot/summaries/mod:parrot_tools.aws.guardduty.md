---
type: Wiki Summary
title: parrot_tools.aws.guardduty
id: mod:parrot_tools.aws.guardduty
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AWS GuardDuty Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.guardduty.GetFindingDetailsInput
  rel: defines
- concept: class:parrot_tools.aws.guardduty.GetFindingsStatisticsInput
  rel: defines
- concept: class:parrot_tools.aws.guardduty.GuardDutyToolkit
  rel: defines
- concept: class:parrot_tools.aws.guardduty.ListDetectorsInput
  rel: defines
- concept: class:parrot_tools.aws.guardduty.ListFindingsInput
  rel: defines
- concept: class:parrot_tools.aws.guardduty.ListIPSetsInput
  rel: defines
- concept: class:parrot_tools.aws.guardduty.ListThreatIntelSetsInput
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.guardduty`

AWS GuardDuty Toolkit for AI-Parrot.

Provides inspection of GuardDuty detectors, findings, IP sets, and threat intel sets.

## Classes

- **`ListDetectorsInput(BaseModel)`** — Input for listing GuardDuty detectors.
- **`ListFindingsInput(BaseModel)`** — Input for listing GuardDuty findings.
- **`GetFindingDetailsInput(BaseModel)`** — Input for getting detailed finding information.
- **`GetFindingsStatisticsInput(BaseModel)`** — Input for getting finding statistics.
- **`ListIPSetsInput(BaseModel)`** — Input for listing GuardDuty IP sets.
- **`ListThreatIntelSetsInput(BaseModel)`** — Input for listing GuardDuty threat intel sets.
- **`GuardDutyToolkit(AbstractToolkit)`** — Toolkit for inspecting AWS GuardDuty detectors and findings.
