---
type: Wiki Entity
title: SecurityHubToolkit
id: class:parrot_tools.aws.securityhub.SecurityHubToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for inspecting AWS SecurityHub findings and compliance.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# SecurityHubToolkit

Defined in [`parrot_tools.aws.securityhub`](../summaries/mod:parrot_tools.aws.securityhub.md).

```python
class SecurityHubToolkit(AbstractToolkit)
```

Toolkit for inspecting AWS SecurityHub findings and compliance.

Available Operations:
- aws_securityhub_get_findings: Get findings with optional filters
- aws_securityhub_list_failed_standards: List failed security standards
- aws_securityhub_get_security_score: Get account security score

## Methods

- `async def aws_securityhub_get_findings(self, limit: int=20, severity: str='ALL', search_term: Optional[str]=None) -> Dict[str, Any]` — Get findings from AWS SecurityHub.
- `async def aws_securityhub_list_failed_standards(self, limit: int=20) -> Dict[str, Any]` — List failed security standards from SecurityHub.
- `async def aws_securityhub_get_security_score(self) -> Dict[str, Any]` — Get the overall security score for the AWS account.
