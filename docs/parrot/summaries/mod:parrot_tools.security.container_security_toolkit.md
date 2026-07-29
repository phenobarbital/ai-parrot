---
type: Wiki Summary
title: parrot_tools.security.container_security_toolkit
id: mod:parrot_tools.security.container_security_toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Container Security Toolkit.
relates_to:
- concept: class:parrot_tools.security.container_security_toolkit.ContainerSecurityToolkit
  rel: defines
- concept: mod:parrot_tools.security.models
  rel: references
- concept: mod:parrot_tools.security.persistence
  rel: references
- concept: mod:parrot_tools.security.trivy.config
  rel: references
- concept: mod:parrot_tools.security.trivy.executor
  rel: references
- concept: mod:parrot_tools.security.trivy.parser
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.security.container_security_toolkit`

Container Security Toolkit.

Agent-facing toolkit that wraps Trivy for container, filesystem,
Kubernetes, and IaC security scanning.
All public async methods automatically become agent tools.

## Classes

- **`ContainerSecurityToolkit(ReportPersistenceMixin, AbstractToolkit)`** — Container and infrastructure security toolkit powered by Trivy.
