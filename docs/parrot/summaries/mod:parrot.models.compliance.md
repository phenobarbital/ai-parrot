---
type: Wiki Summary
title: parrot.models.compliance
id: mod:parrot.models.compliance
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.models.compliance
relates_to:
- concept: class:parrot.models.compliance.BrandComplianceResult
  rel: defines
- concept: class:parrot.models.compliance.ComplianceResult
  rel: defines
- concept: class:parrot.models.compliance.ComplianceStatus
  rel: defines
- concept: class:parrot.models.compliance.TextComplianceResult
  rel: defines
- concept: class:parrot.models.compliance.TextMatcher
  rel: defines
---

# `parrot.models.compliance`

## Classes

- **`ComplianceStatus(str, Enum)`** — Possible compliance statuses for shelf checks
- **`TextComplianceResult(BaseModel)`** — Result of text compliance checking
- **`BrandComplianceResult(BaseModel)`** — Result of brand logo compliance checking
- **`ComplianceResult(BaseModel)`** — Final compliance check result
- **`TextMatcher`** — N-gram + fuzzy text matcher for planogram text compliance.
