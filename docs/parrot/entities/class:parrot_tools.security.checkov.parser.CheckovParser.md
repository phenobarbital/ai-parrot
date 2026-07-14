---
type: Wiki Entity
title: CheckovParser
id: class:parrot_tools.security.checkov.parser.CheckovParser
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parser for Checkov JSON output.
relates_to:
- concept: class:parrot_tools.security.base_parser.BaseParser
  rel: extends
---

# CheckovParser

Defined in [`parrot_tools.security.checkov.parser`](../summaries/mod:parrot_tools.security.checkov.parser.md).

```python
class CheckovParser(BaseParser)
```

Parser for Checkov JSON output.

Normalizes Checkov findings from IaC scans into the unified SecurityFinding
format, enabling cross-tool aggregation with Prowler and Trivy.

Checkov scans Terraform, CloudFormation, Kubernetes, Helm, Dockerfiles,
and many other IaC formats.

Example:
    parser = CheckovParser()
    result = parser.parse(checkov_json_output)
    for finding in result.findings:
        print(f"{finding.severity}: {finding.title}")

## Methods

- `def parse(self, raw_output: str) -> ScanResult` — Parse raw Checkov JSON output into a ScanResult.
- `def normalize_finding(self, raw_check: dict, passed: Optional[bool]=None, check_type: str='unknown') -> SecurityFinding` — Normalize a Checkov check finding.
