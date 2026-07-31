---
type: Wiki Summary
title: parrot_tools.cloudsploit.ecr_collector
id: mod:parrot_tools.cloudsploit.ecr_collector
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ECR image-scan collector for CloudSploit toolkit (FEAT-165).
relates_to:
- concept: class:parrot_tools.cloudsploit.ecr_collector.EcrScanCollector
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.aws.ecr
  rel: references
- concept: mod:parrot_tools.cloudsploit.models
  rel: references
---

# `parrot_tools.cloudsploit.ecr_collector`

ECR image-scan collector for CloudSploit toolkit (FEAT-165).

Implements multi-repo / tag-priority aggregation against ECR Basic Scanning,
with bounded concurrency via ``asyncio.Semaphore``.

## Classes

- **`EcrScanCollector`** — Aggregate ECR vulnerability scan findings across many repos.
