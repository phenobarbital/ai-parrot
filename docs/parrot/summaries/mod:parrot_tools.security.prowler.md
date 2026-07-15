---
type: Wiki Summary
title: parrot_tools.security.prowler
id: mod:parrot_tools.security.prowler
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Prowler security scanner integration.
relates_to:
- concept: mod:parrot_tools.security
  rel: references
---

# `parrot_tools.security.prowler`

Prowler security scanner integration.

Prowler is a cloud security posture assessment tool supporting
AWS, Azure, GCP, and Kubernetes.

Usage:
    from parrot_tools.security.prowler import ProwlerExecutor, ProwlerConfig, ProwlerParser

    config = ProwlerConfig(
        provider="aws",
        filter_regions=["us-east-1"],
        services=["s3", "iam"],
    )
    executor = ProwlerExecutor(config)
    stdout, stderr, code = await executor.run_scan()

    # Parse results
    parser = ProwlerParser()
    result = parser.parse(stdout)
