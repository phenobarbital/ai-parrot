---
type: Wiki Summary
title: parrot_tools.aws.securityhub
id: mod:parrot_tools.aws.securityhub
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AWS SecurityHub Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.securityhub.GetFindingsInput
  rel: defines
- concept: class:parrot_tools.aws.securityhub.GetSecurityScoreInput
  rel: defines
- concept: class:parrot_tools.aws.securityhub.ListFailedStandardsInput
  rel: defines
- concept: class:parrot_tools.aws.securityhub.SecurityHubToolkit
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.securityhub`

AWS SecurityHub Toolkit for AI-Parrot.

Provides inspection of SecurityHub findings, failed standards, and security scores.

## Classes

- **`GetFindingsInput(BaseModel)`** — Input for getting SecurityHub findings.
- **`ListFailedStandardsInput(BaseModel)`** — Input for listing failed security standards.
- **`GetSecurityScoreInput(BaseModel)`** — Input for getting the account security score.
- **`SecurityHubToolkit(AbstractToolkit)`** — Toolkit for inspecting AWS SecurityHub findings and compliance.
