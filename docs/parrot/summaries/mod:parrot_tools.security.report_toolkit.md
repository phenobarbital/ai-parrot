---
type: Wiki Summary
title: parrot_tools.security.report_toolkit
id: mod:parrot_tools.security.report_toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SecurityReportToolkit — LLM-facing read side of the security report catalog.
relates_to:
- concept: class:parrot_tools.security.report_toolkit.SecurityReportToolkit
  rel: defines
- concept: mod:parrot.interfaces.file
  rel: references
- concept: mod:parrot.storage.security_reports
  rel: references
- concept: mod:parrot_tools.security.parsers
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.security.report_toolkit`

SecurityReportToolkit — LLM-facing read side of the security report catalog.

This toolkit exposes the catalog to the LLM as agent tools.  The agent
calls these tools BEFORE running expensive scanners, guided by the freshness
policy in the SecurityAgent BACKSTORY.

Module implements Spec §3 Module 7.

## Classes

- **`SecurityReportToolkit(AbstractToolkit)`** — LLM-facing tools for querying the cross-session security report catalog.
