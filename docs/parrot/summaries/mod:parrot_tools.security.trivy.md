---
type: Wiki Summary
title: parrot_tools.security.trivy
id: mod:parrot_tools.security.trivy
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Trivy security scanner integration.
relates_to:
- concept: mod:parrot_tools.security
  rel: references
---

# `parrot_tools.security.trivy`

Trivy security scanner integration.

Trivy is a comprehensive vulnerability scanner for containers, filesystems,
Git repositories, Kubernetes clusters, and IaC configurations.

Usage:
    from parrot_tools.security.trivy import TrivyConfig, TrivyExecutor, TrivyParser

    config = TrivyConfig(severity_filter=["CRITICAL", "HIGH"])
    executor = TrivyExecutor(config)
    parser = TrivyParser()

    stdout, stderr, code = await executor.scan_image("nginx:latest")
    result = parser.parse(stdout)
