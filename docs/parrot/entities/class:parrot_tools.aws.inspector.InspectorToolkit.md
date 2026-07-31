---
type: Wiki Entity
title: InspectorToolkit
id: class:parrot_tools.aws.inspector.InspectorToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Stateless toolkit wrapping Amazon Inspector v2 (inspector2).
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# InspectorToolkit

Defined in [`parrot_tools.aws.inspector`](../summaries/mod:parrot_tools.aws.inspector.md).

```python
class InspectorToolkit(AbstractToolkit)
```

Stateless toolkit wrapping Amazon Inspector v2 (inspector2).

Available Operations (read-only, no mutation):

Direct reads:
- aws_inspector_list_findings: List findings with optional filters
- aws_inspector_aggregate_findings: Aggregate findings by dimension
- aws_inspector_get_ecr_image_findings: Convenience ECR image finder
- aws_inspector_list_coverage: List scanned resources
- aws_inspector_get_coverage_statistics: Coverage stats summary
- aws_inspector_batch_get_account_status: Scan type enablement

Composite reads:
- aws_inspector_get_security_posture: Weighted security score + coverage
- aws_inspector_list_top_vulnerable_resources: Top N by weighted severity

Async exports:
- aws_inspector_create_findings_report: Start S3 findings export
- aws_inspector_get_findings_report_status: Poll export status
- aws_inspector_create_sbom_export: Start S3 SBOM export
- aws_inspector_get_sbom_export: Poll SBOM export status

## Methods

- `async def aws_inspector_list_findings(self, limit: int=20, severity: str='ALL', resource_type: Optional[str]=None, status: str='ACTIVE', fix_available: Optional[str]=None, repository_name: Optional[str]=None, search_term: Optional[str]=None, next_token: Optional[str]=None) -> Dict[str, Any]` — List Amazon Inspector v2 findings with optional filters.
- `async def aws_inspector_aggregate_findings(self, aggregation_type: str='REPOSITORY', limit: int=25, severity: Optional[str]=None, resource_type: Optional[str]=None) -> Dict[str, Any]` — Aggregate Inspector v2 findings by a chosen dimension.
- `async def aws_inspector_get_ecr_image_findings(self, repository_name: str, image_digest: Optional[str]=None, image_tag: Optional[str]=None, severity: str='ALL', limit: int=50) -> Dict[str, Any]` — Get Inspector v2 findings for a specific ECR container image.
- `async def aws_inspector_list_coverage(self, resource_type: Optional[str]=None, scan_status: Optional[str]=None, scan_status_reason: Optional[str]=None, repository_name: Optional[str]=None, limit: int=50, next_token: Optional[str]=None) -> Dict[str, Any]` — List resources covered by Amazon Inspector v2 scanning.
- `async def aws_inspector_get_coverage_statistics(self) -> Dict[str, Any]` — Get Amazon Inspector v2 coverage statistics summary.
- `async def aws_inspector_batch_get_account_status(self) -> Dict[str, Any]` — Get Inspector v2 scan type enablement status for the current account.
- `async def aws_inspector_get_security_posture(self, weights: Optional[Dict[str, int]]=None) -> Dict[str, Any]` — Get the overall Inspector v2 security posture for the account.
- `async def aws_inspector_list_top_vulnerable_resources(self, resource_type: Optional[str]=None, limit: int=10, weights: Optional[Dict[str, int]]=None) -> Dict[str, Any]` — List the most vulnerable resources by weighted Inspector severity.
- `async def aws_inspector_create_findings_report(self, s3_bucket: str, s3_key_prefix: str='inspector-reports/', kms_key_arn: str='', report_format: str='JSON', severity: Optional[str]=None, resource_type: Optional[str]=None) -> Dict[str, Any]` — Start an async Amazon Inspector findings report export to S3.
- `async def aws_inspector_get_findings_report_status(self, report_id: str) -> Dict[str, Any]` — Poll the status of an Inspector findings report export.
- `async def aws_inspector_create_sbom_export(self, s3_bucket: str, s3_key_prefix: str='inspector-sboms/', kms_key_arn: str='', report_format: str='CYCLONEDX_1_4', resource_type: Optional[str]=None, repository_name: Optional[str]=None) -> Dict[str, Any]` — Start an async Amazon Inspector SBOM export to S3.
- `async def aws_inspector_get_sbom_export(self, report_id: str) -> Dict[str, Any]` — Poll the status of an Inspector SBOM export.
