---
type: Wiki Summary
title: parrot_tools.security.checkov
id: mod:parrot_tools.security.checkov
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Checkov IaC security scanner integration.
relates_to:
- concept: mod:parrot_tools.security
  rel: references
---

# `parrot_tools.security.checkov`

Checkov IaC security scanner integration.

Checkov is a static code analysis tool for infrastructure-as-code (IaC),
scanning Terraform, CloudFormation, Kubernetes, Helm, Dockerfiles, and more
for security misconfigurations and secrets.

Usage:
    from parrot_tools.security.checkov import CheckovConfig, CheckovExecutor

    config = CheckovConfig(frameworks=["terraform"])
    executor = CheckovExecutor(config)

    stdout, stderr, code = await executor.scan_directory("./terraform")
