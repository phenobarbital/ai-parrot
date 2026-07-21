---
type: Wiki Summary
title: parrot_tools.aws.s3
id: mod:parrot_tools.aws.s3
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: AWS S3 Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.s3.AnalyzeBucketSecurityInput
  rel: defines
- concept: class:parrot_tools.aws.s3.FindPublicBucketsInput
  rel: defines
- concept: class:parrot_tools.aws.s3.GetBucketDetailsInput
  rel: defines
- concept: class:parrot_tools.aws.s3.ListBucketsInput
  rel: defines
- concept: class:parrot_tools.aws.s3.S3Toolkit
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.s3`

AWS S3 Toolkit for AI-Parrot.

Provides inspection and security analysis of S3 buckets.

## Classes

- **`ListBucketsInput(BaseModel)`** — Input for listing S3 buckets.
- **`GetBucketDetailsInput(BaseModel)`** — Input for getting detailed S3 bucket information.
- **`AnalyzeBucketSecurityInput(BaseModel)`** — Input for analyzing S3 bucket security configuration.
- **`FindPublicBucketsInput(BaseModel)`** — Input for finding publicly accessible S3 buckets.
- **`S3Toolkit(AbstractToolkit)`** — Toolkit for inspecting and analyzing AWS S3 buckets.
