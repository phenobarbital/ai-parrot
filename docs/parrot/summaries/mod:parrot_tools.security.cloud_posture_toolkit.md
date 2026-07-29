---
type: Wiki Summary
title: parrot_tools.security.cloud_posture_toolkit
id: mod:parrot_tools.security.cloud_posture_toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Cloud Security Posture Management Toolkit.
relates_to:
- concept: class:parrot_tools.security.cloud_posture_toolkit.CloudPostureToolkit
  rel: defines
- concept: mod:parrot_tools.security.models
  rel: references
- concept: mod:parrot_tools.security.prowler.config
  rel: references
- concept: mod:parrot_tools.security.prowler.executor
  rel: references
- concept: mod:parrot_tools.security.prowler.parser
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.security.cloud_posture_toolkit`

Cloud Security Posture Management Toolkit.

Agent-facing toolkit that wraps Prowler for multi-cloud security scanning.
All public async methods automatically become agent tools.

## Classes

- **`CloudPostureToolkit(AbstractToolkit)`** — Cloud Security Posture Management toolkit powered by Prowler.
