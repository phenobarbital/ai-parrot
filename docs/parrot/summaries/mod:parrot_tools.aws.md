---
type: Wiki Summary
title: parrot_tools.aws
id: mod:parrot_tools.aws
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AWS Toolkits for AI-Parrot.
relates_to:
- concept: mod:parrot_tools
  rel: references
- concept: mod:parrot_tools.s3
  rel: references
---

# `parrot_tools.aws`

AWS Toolkits for AI-Parrot.

This package provides toolkits for interacting with AWS services,
including Route53, ECS/EKS, CloudWatch, S3, IAM, EC2, ECR,
GuardDuty, SecurityHub, RDS, DocumentDB, Lambda, EKS, and Inspector v2.

IAM policy sidecars for each toolkit are shipped alongside the code under
the ``policies/`` directory (e.g. ``policies/inspector_toolkit_policy.json``).
