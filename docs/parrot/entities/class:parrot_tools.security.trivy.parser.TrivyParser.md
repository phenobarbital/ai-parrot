---
type: Wiki Entity
title: TrivyParser
id: class:parrot_tools.security.trivy.parser.TrivyParser
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parser for Trivy JSON output.
relates_to:
- concept: class:parrot_tools.security.base_parser.BaseParser
  rel: extends
---

# TrivyParser

Defined in [`parrot_tools.security.trivy.parser`](../summaries/mod:parrot_tools.security.trivy.parser.md).

```python
class TrivyParser(BaseParser)
```

Parser for Trivy JSON output.

Normalizes Trivy findings from vulnerability scans, secret detection,
and misconfiguration checks into the unified SecurityFinding format.

Supports:
- Container image vulnerabilities
- Filesystem and repository vulnerabilities
- Secret detection findings
- IaC misconfigurations (Dockerfile, Kubernetes, Terraform, etc.)

Example:
    parser = TrivyParser()
    result = parser.parse(trivy_json_output)
    for finding in result.findings:
        print(f"{finding.severity}: {finding.title}")

## Methods

- `def parse(self, raw_output: str) -> ScanResult` — Parse raw Trivy JSON output into a ScanResult.
- `def normalize_finding(self, raw_finding: dict) -> SecurityFinding` — Normalize a raw finding (generic dispatch).
- `def normalize_vulnerability(self, raw_vuln: dict, target: Optional[str]=None) -> SecurityFinding` — Normalize a Trivy vulnerability finding.
- `def normalize_secret(self, raw_secret: dict, target: Optional[str]=None) -> SecurityFinding` — Normalize a Trivy secret detection finding.
- `def normalize_misconfiguration(self, raw_misconfig: dict, target: Optional[str]=None) -> SecurityFinding` — Normalize a Trivy misconfiguration finding.
