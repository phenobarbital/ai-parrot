---
type: Wiki Summary
title: parrot_tools.security.secrets_iac_toolkit
id: mod:parrot_tools.security.secrets_iac_toolkit
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Secrets and Infrastructure as Code Security Toolkit.
relates_to:
- concept: class:parrot_tools.security.secrets_iac_toolkit.SecretsIaCToolkit
  rel: defines
- concept: mod:parrot_tools.security.checkov.config
  rel: references
- concept: mod:parrot_tools.security.checkov.executor
  rel: references
- concept: mod:parrot_tools.security.checkov.parser
  rel: references
- concept: mod:parrot_tools.security.models
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.security.secrets_iac_toolkit`

Secrets and Infrastructure as Code Security Toolkit.

Agent-facing toolkit that wraps Checkov for IaC security scanning
and secrets detection. All public async methods automatically become agent tools.

## Classes

- **`SecretsIaCToolkit(AbstractToolkit)`** — Infrastructure as Code and Secrets scanning toolkit powered by Checkov.
