---
type: Wiki Summary
title: parrot_tools.cloudsploit.toolkit
id: mod:parrot_tools.cloudsploit.toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CloudSploit Security Scanning Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.cloudsploit.toolkit.CloudSploitToolkit
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.cloudsploit.comparator
  rel: references
- concept: mod:parrot_tools.cloudsploit.ecr_collector
  rel: references
- concept: mod:parrot_tools.cloudsploit.executor
  rel: references
- concept: mod:parrot_tools.cloudsploit.models
  rel: references
- concept: mod:parrot_tools.cloudsploit.parser
  rel: references
- concept: mod:parrot_tools.cloudsploit.reports
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.security.persistence
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.cloudsploit.toolkit`

CloudSploit Security Scanning Toolkit for AI-Parrot.

Orchestrates CloudSploit executor, parser, report generator, and
comparator into a single AbstractToolkit subclass.  Every public
async method is automatically exposed as an agent tool.

## Classes

- **`CloudSploitToolkit(ReportPersistenceMixin, AbstractToolkit)`** — Cloud Security Posture Management toolkit powered by CloudSploit.
