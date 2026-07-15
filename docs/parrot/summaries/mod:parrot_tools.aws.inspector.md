---
type: Wiki Summary
title: parrot_tools.aws.inspector
id: mod:parrot_tools.aws.inspector
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: AWS Inspector v2 Toolkit for AI-Parrot.
relates_to:
- concept: class:parrot_tools.aws.inspector.AggregateFindingsInput
  rel: defines
- concept: class:parrot_tools.aws.inspector.CreateFindingsReportInput
  rel: defines
- concept: class:parrot_tools.aws.inspector.CreateSbomExportInput
  rel: defines
- concept: class:parrot_tools.aws.inspector.GetEcrImageFindingsInput
  rel: defines
- concept: class:parrot_tools.aws.inspector.GetSecurityPostureInput
  rel: defines
- concept: class:parrot_tools.aws.inspector.InspectorToolkit
  rel: defines
- concept: class:parrot_tools.aws.inspector.ListCoverageInput
  rel: defines
- concept: class:parrot_tools.aws.inspector.ListFindingsInput
  rel: defines
- concept: class:parrot_tools.aws.inspector.ListTopVulnerableResourcesInput
  rel: defines
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.aws.inspector`

AWS Inspector v2 Toolkit for AI-Parrot.

Provides stateless read-only access to Amazon Inspector v2 (inspector2) findings,
aggregations, coverage, and async export operations.

## Classes

- **`ListFindingsInput(BaseModel)`** — Input for listing Inspector v2 findings.
- **`AggregateFindingsInput(BaseModel)`** — Input for aggregating Inspector v2 findings.
- **`GetEcrImageFindingsInput(BaseModel)`** — Input for getting Inspector findings for a specific ECR image.
- **`ListCoverageInput(BaseModel)`** — Input for listing Inspector v2 coverage resources.
- **`GetSecurityPostureInput(BaseModel)`** — Input for computing the account-level Inspector security posture.
- **`ListTopVulnerableResourcesInput(BaseModel)`** — Input for listing the most vulnerable resources by weighted severity.
- **`CreateFindingsReportInput(BaseModel)`** — Input for creating an async Inspector findings report in S3.
- **`CreateSbomExportInput(BaseModel)`** — Input for creating an async SBOM export in S3.
- **`InspectorToolkit(AbstractToolkit)`** — Stateless toolkit wrapping Amazon Inspector v2 (inspector2).
