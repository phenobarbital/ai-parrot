---
type: Wiki Summary
title: parrot_tools.security.soc2_advisory
id: mod:parrot_tools.security.soc2_advisory
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SOC2AdvisoryToolkit — LLM-facing read-only SOC2 advisory tools.
relates_to:
- concept: class:parrot_tools.security.soc2_advisory.SOC2AdvisoryToolkit
  rel: defines
- concept: mod:parrot.storage.security_reports
  rel: references
- concept: mod:parrot_tools.security.advisory_engine
  rel: references
- concept: mod:parrot_tools.security.models
  rel: references
- concept: mod:parrot_tools.security.reports
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.security.soc2_advisory`

SOC2AdvisoryToolkit — LLM-facing read-only SOC2 advisory tools.

Wraps ``SecurityAdvisoryEngine`` and the existing ``ComplianceMapper`` as
agent-callable tools.  All tools return structured dicts; narrative is left
to the caller's LLM.  The store is required; the toolkit is strictly
read-only (never calls ``save_report`` or any write path).

Implements FEAT-226 spec §3 Module 2.

## Classes

- **`SOC2AdvisoryToolkit(AbstractToolkit)`** — LLM-facing tools for SOC2-oriented security advisory.
